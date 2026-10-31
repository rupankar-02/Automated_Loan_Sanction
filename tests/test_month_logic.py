from datetime import date

import pytest

from core.config.loader import get_policy
from core.models import FieldResult, FieldStatus
from core.validation.doc_rules import apply_document_rules, apply_salary_set_rules
from core.validation.field_rules import make_context
from core.validation.months import check_bank_period, month_name, required_window

POLICY = get_policy()
OCT31, NOV3, NOV15 = date(2026, 10, 31), date(2026, 11, 3), date(2026, 11, 15)
M = lambda *a: [(2026, m) for m in a]  # noqa: E731


def slips(today, *months):
    return apply_salary_set_rules([f"{y}-{m:02d}" for y, m in months], make_context(today))


def ids(issues):
    return {i.rule_id for i in issues}


def test_required_window_and_grace():
    assert required_window(OCT31, POLICY) == M(7, 8, 9)
    assert required_window(NOV3, POLICY) == M(7, 8, 9)       # inside the 10-day grace
    assert required_window(NOV15, POLICY) == M(8, 9, 10)
    assert required_window(date(2026, 1, 20), POLICY) == [(2025, 10), (2025, 11), (2025, 12)]  # year boundary


@pytest.mark.parametrize("today,months", [
    (OCT31, M(7, 8, 9)), (OCT31, M(8, 9, 10)),            # current month accepted, never required
    (NOV3, M(7, 8, 9)), (NOV3, M(8, 9, 10)),
    (NOV15, M(8, 9, 10)), (NOV15, M(9, 10, 11)),
])
def test_salary_pass(today, months):
    assert slips(today, *months) == []


def test_missing_middle_month_is_named():
    issues = slips(OCT31, *M(7, 9, 10))
    assert ids(issues) == {"SALARY_MONTHS_MISSING"}
    assert issues[0].message == "Salary slip for August 2026 is missing."


def test_stale_slips():
    issues = slips(OCT31, *M(6, 7, 8))
    assert ids(issues) == {"SALARY_MONTHS_STALE"}
    assert "newest slip is for August 2026" in issues[0].message and "Jul-Sep 2026" in issues[0].message


def test_duplicate_month_counts_once():
    issues = slips(OCT31, *M(7, 8, 8))
    assert "SALARY_DUPLICATE_MONTH" in ids(issues)
    assert any(i.severity == "error" for i in issues)         # still fails: only 2 distinct months


def test_future_month_rejected():
    issues = slips(OCT31, *M(8, 9, 11))
    assert "SALARY_MONTH_FUTURE" in ids(issues)


def test_grace_rows():
    assert slips(NOV3, *M(6, 7, 8)) and ids(slips(NOV3, *M(6, 7, 8))) == {"SALARY_MONTHS_STALE"}
    assert ids(slips(NOV15, *M(7, 8, 9))) == {"SALARY_MONTHS_STALE"}   # fine on Nov 3, stale by Nov 15
    assert ids(slips(NOV15, *M(8, 10, 11))) == {"SALARY_MONTHS_MISSING"}


def test_two_months_missing_message():
    issues = slips(OCT31, *M(9, 10))
    assert issues[0].message == "Salary slips for July 2026 and August 2026 are missing." or "missing" in issues[0].message


def test_no_slips():
    assert ids(slips(OCT31)) == {"SALARY_MONTHS_MISSING"}


@pytest.mark.parametrize("start,end,today,passes", [
    (date(2026, 7, 1), date(2026, 9, 30), OCT31, True),
    (date(2026, 7, 4), date(2026, 9, 30), OCT31, True),        # within 5-day tolerance
    (date(2026, 7, 7), date(2026, 9, 30), OCT31, False),       # beyond tolerance
    (date(2026, 7, 1), date(2026, 10, 25), OCT31, True),       # runs into the current month
    (date(2026, 4, 1), date(2026, 6, 30), OCT31, False),
    (date(2026, 7, 1), date(2026, 9, 15), OCT31, False),       # ends too early
    (date(2026, 7, 4), date(2026, 9, 30), NOV3, True),
    (date(2026, 7, 1), date(2026, 9, 30), NOV15, False),       # Aug-Oct now required
    (date(2026, 8, 1), date(2026, 10, 31), NOV15, True),
])
def test_bank_coverage(start, end, today, passes):
    assert (check_bank_period(start, end, today, POLICY) == []) is passes


def test_bank_coverage_message():
    issue = check_bank_period(date(2026, 4, 1), date(2026, 6, 30), OCT31, POLICY)[0]
    assert issue.rule_id == "BANK_PERIOD_COVERAGE" and issue.action == "reupload"
    assert issue.message == ("This statement covers Apr-Jun 2026, but we need Jul-Sep 2026. "
                             "Please upload a statement for the last 3 months.")


def test_bank_order_and_recency():
    assert check_bank_period(date(2026, 9, 30), date(2026, 7, 1), OCT31, POLICY)[0].rule_id == "BANK_PERIOD_ORDER"


def test_pinned_reference_date_overrides_today(monkeypatch):
    from core.utils import dates
    policy = get_policy().model_copy(deep=True)
    policy.months.reference_date = date(2026, 10, 31)
    monkeypatch.setattr(dates, "get_policy", lambda: policy)
    assert dates.reference_date() == date(2026, 10, 31)


def _f(key, val):
    return FieldResult(key=key, label=key, normalized_value=val, status=FieldStatus.VALID)


def test_salary_amount_rules():
    ctx = make_context(OCT31)
    bad = apply_document_rules("salary_slip", [_f("gross_salary", "40000"), _f("net_salary", "50000")], ctx)
    assert ids(bad) == {"SALARY_NET_LE_GROSS"}
    math = apply_document_rules("salary_slip", [_f("gross_salary", "50000"), _f("total_deductions", "5000"), _f("net_salary", "40000")], ctx)
    assert ids(math) == {"SALARY_DEDUCTION_MATH"} and math[0].severity == "warning"
    fine = apply_document_rules("salary_slip", [_f("gross_salary", "50000"), _f("total_deductions", "5000"), _f("net_salary", "45000")], ctx)
    assert fine == []


def test_bank_document_rule_uses_extracted_dates():
    ctx = make_context(OCT31)
    issues = apply_document_rules("bank_statement", [_f("statement_from", "2026-04-01"), _f("statement_to", "2026-06-30")], ctx)
    assert ids(issues) == {"BANK_PERIOD_COVERAGE"}
    assert month_name((2026, 8)) == "August 2026"
