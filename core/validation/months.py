"""Which months must the documents cover? One anchor shared by salary slips and bank statements.

Policy (all configurable in policy.yaml -> months):
  required_latest = previous complete month, or the month before it while today.day <= slip_grace_days.
  The window is the `required_months` months ending at required_latest.
  The current month is accepted but never required.
"""
import calendar
from collections import Counter
from datetime import date

from core.config.loader import Policy
from core.models import DocIssue

Month = tuple[int, int]  # (year, month)

_NAMES = ["January", "February", "March", "April", "May", "June", "July",
          "August", "September", "October", "November", "December"]


def add_months(m: Month, n: int) -> Month:
    idx = m[0] * 12 + (m[1] - 1) + n
    return idx // 12, idx % 12 + 1


def month_name(m: Month) -> str:
    return f"{_NAMES[m[1] - 1]} {m[0]}"


def range_label(months: list[Month]) -> str:
    """[(2026,7),(2026,9)] -> 'Jul-Sep 2026'; crosses a year -> 'Dec 2025-Feb 2026'."""
    lo, hi = min(months), max(months)
    a, b = _NAMES[lo[1] - 1][:3], _NAMES[hi[1] - 1][:3]
    if lo[0] == hi[0]:
        return f"{a}-{b} {hi[0]}" if lo != hi else f"{a} {hi[0]}"
    return f"{a} {lo[0]}-{b} {hi[0]}"


def required_window(today: date, policy: Policy) -> list[Month]:
    mp = policy.months
    latest = add_months((today.year, today.month), -1)
    if today.day <= mp.slip_grace_days:
        latest = add_months(latest, -1)
    return [add_months(latest, -(mp.required_months - 1) + i) for i in range(mp.required_months)]


def window_bounds(window: list[Month]) -> tuple[date, date]:
    first, last = window[0], window[-1]
    return date(first[0], first[1], 1), date(last[0], last[1], calendar.monthrange(*last)[1])


def _list_names(ms: list[Month]) -> str:
    names = [month_name(m) for m in ms]
    return names[0] if len(names) == 1 else ", ".join(names[:-1]) + " and " + names[-1]


def check_salary_months(pay_months: list[Month], today: date, policy: Policy) -> list[DocIssue]:
    mp, n = policy.months, policy.months.required_months
    issues: list[DocIssue] = []
    cur = (today.year, today.month)
    cutoff = cur if mp.allow_current_month else add_months(cur, -1)
    window = required_window(today, policy)
    need = range_label(window)

    future = sorted(m for m in set(pay_months) if m > cutoff)
    if future:
        issues.append(DocIssue(
            rule_id="SALARY_MONTH_FUTURE",
            message=f"A salary slip is dated {_list_names(future)}, which is in the future. Please check the date on that slip.",
            action="reupload"))
    months = [m for m in pay_months if m <= cutoff]

    dups = sorted(m for m, c in Counter(months).items() if c > 1)
    if dups:
        issues.append(DocIssue(
            rule_id="SALARY_DUPLICATE_MONTH",
            message=f"You uploaded more than one slip for {_list_names(dups)}. It counts only once, so please upload a different month.",
            action="reupload"))

    distinct = sorted(set(months))
    if not distinct:
        issues.append(DocIssue(rule_id="SALARY_MONTHS_MISSING",
                               message=f"We need salary slips for {need}. Please upload them.", action="reupload",
                               metric={"missing": [month_name(m) for m in window]}))
        return issues

    newest = max(distinct)
    if newest < window[-1]:
        issues.append(DocIssue(
            rule_id="SALARY_MONTHS_STALE",
            message=f"Your newest slip is for {month_name(newest)}. We need slips for {need}.",
            action="reupload", metric={"newest": month_name(newest), "required": need}))
        return issues

    target = [add_months(newest, -(n - 1) + i) for i in range(n)]
    missing = [m for m in target if m not in distinct]
    if missing:
        noun = "Salary slip for" if len(missing) == 1 else "Salary slips for"
        issues.append(DocIssue(
            rule_id="SALARY_MONTHS_MISSING",
            message=f"{noun} {_list_names(missing)} {'is' if len(missing) == 1 else 'are'} missing.",
            action="reupload", metric={"missing": [month_name(m) for m in missing]}))
    return issues


def check_bank_period(start: date, end: date, today: date, policy: Policy) -> list[DocIssue]:
    mp = policy.months
    if start > end:
        return [DocIssue(rule_id="BANK_PERIOD_ORDER", action="edit",
                         message="The statement start date is after its end date. Please check both dates.")]
    window = required_window(today, policy)
    w_start, w_end = window_bounds(window)
    need = range_label(window)
    from datetime import timedelta
    covered = start <= w_start + timedelta(days=mp.bank_start_tolerance_days) and end >= w_end
    if not covered:
        have = range_label([(start.year, start.month), (end.year, end.month)])
        return [DocIssue(
            rule_id="BANK_PERIOD_COVERAGE", action="reupload",
            message=f"This statement covers {have}, but we need {need}. "
                    f"Please upload a statement for the last {mp.required_months} months.",
            metric={"covers": have, "required": need})]
    if end < today - timedelta(days=mp.bank_recency_days):
        return [DocIssue(rule_id="BANK_RECENCY", action="reupload",
                         message=f"This statement ends on {end:%d %b %Y}, which is too old. Please download a recent one.")]
    return []
