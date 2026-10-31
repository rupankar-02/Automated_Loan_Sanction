from datetime import date

import pytest

from core.config.loader import get_policy
from core.models import FieldStatus
from core.pipeline import (clear_slot, process_many, process_upload, remove_part,
                           request_manual_review, submit_correction)
from core.state import new_application, progress, readiness, slot_status
from core.validation.field_rules import make_context
from core.vlm.fake import FakeExtractor
from tests import synth

CTX = make_context(date(2026, 10, 31))
PAN = {"pan_number": "ABCDE1234F", "name": "RAHUL SHARMA", "father_name": "MOHAN SHARMA", "dob": "15/08/1990"}
BANK = {"account_holder_name": "RAHUL SHARMA", "bank_name": "HDFC Bank", "account_number": "123456789012",
        "ifsc": "HDFC0001234", "statement_from": "01/07/2026", "statement_to": "30/09/2026"}


@pytest.fixture
def app():
    return new_application("personal", "salaried")


def jpg(img=None, seed_text=""):
    img = img or synth.good_card()
    if seed_text:                                # make files differ so hashes differ
        from PIL import ImageDraw
        ImageDraw.Draw(img).text((5, 5), seed_text, fill=(100, 100, 100))
    return synth.to_jpeg(img)


def upload(app, slot, data, fake, name="f.jpg"):
    return process_upload(app, slot, name, data, fake, ctx=CTX)


def slip_page(month, n=0):
    return synth.text_page([f"SALARY SLIP FOR THE MONTH OF {month}", "Employee Name: RAHUL SHARMA", f"Net Pay {n}"] * 3)


def slip_fields(month, **kw):
    d = {"employee_name": "RAHUL SHARMA", "employer_name": "ACME", "pay_month": month,
         "gross_salary": "85000", "net_salary": "72500", "total_deductions": "12500"}
    return {**d, **kw}


def test_slots_for_personal_salaried(app):
    assert list(app.slots) == ["pan", "aadhaar_front", "aadhaar_back", "salary_slip", "bank_statement", "form16_or_itr"]
    assert app.slots["salary_slip"].required_parts == 3 and app.slots["salary_slip"].max_pages == 4
    assert app.slots["form16_or_itr"].extractable and app.slots["form16_or_itr"].optional
    assert app.slots["bank_statement"].max_pages == 30


def test_good_pan_is_accepted_and_valid(app):
    out = upload(app, "pan", jpg(), FakeExtractor(PAN))
    assert out.status == "accepted"
    assert slot_status(app.slots["pan"]) == "verified"
    assert progress(app) == (1, 5)
    assert app.api_calls == 2                    # one classify + one extract


def test_blurry_upload_is_rejected_locally_and_free(app):
    fake = FakeExtractor(PAN)
    out = upload(app, "pan", synth.to_jpeg(synth.blurry(synth.good_card())), fake)
    assert out.status == "rejected" and out.notice.code == "BLURRY" and "PAN Card" in out.notice.message
    assert app.api_calls == 0 and app.slots["pan"].api_uploads == 0 and fake.calls == {"classify": 0, "extract": 0}


def test_same_file_twice_costs_nothing(app):
    fake, data = FakeExtractor(PAN), jpg()
    upload(app, "pan", data, fake)
    assert upload(app, "pan", data, fake).status == "cached"
    assert app.api_calls == 2


def test_same_file_in_two_slots_is_a_duplicate(app):
    data = jpg()
    upload(app, "pan", data, FakeExtractor(PAN))
    out = upload(app, "aadhaar_front", data, FakeExtractor(detected="aadhaar_front"))
    assert out.status == "rejected" and out.notice.code == "DUPLICATE_FILE" and "PAN Card" in out.notice.message


def test_wrong_document_names_what_we_saw_and_what_we_need(app):
    fake = FakeExtractor(PAN, detected="aadhaar_front")
    out = upload(app, "pan", jpg(), fake)
    assert out.notice.code == "WRONG_DOCUMENT"
    assert "Aadhaar card (front)" in out.notice.message and "PAN card" in out.notice.message
    assert fake.calls["extract"] == 0 and app.api_calls == 1 and app.slots["pan"].api_uploads == 1


def test_aadhaar_back_in_front_slot(app):
    out = upload(app, "aadhaar_front", jpg(), FakeExtractor(detected="aadhaar_back"))
    assert "Aadhaar card (back)" in out.notice.message


def test_reupload_cap_counts_only_api_uploads(app):
    fake = FakeExtractor(PAN, detected="other")
    cap = get_policy().limits.max_reuploads_per_slot + 1
    for i in range(cap):
        assert upload(app, "pan", jpg(seed_text=f"v{i}"), fake).notice.code == "WRONG_DOCUMENT"
        upload(app, "pan", synth.to_jpeg(synth.blurry(synth.good_card())), fake)     # free local rejections
    assert app.slots["pan"].api_uploads == cap
    out = upload(app, "pan", jpg(seed_text="one-too-many"), fake)
    assert out.status == "blocked" and out.notice.code == "REUPLOAD_LIMIT" and out.notice.offer_manual_review


def test_api_budget_circuit_breaker(app, monkeypatch):
    monkeypatch.setattr(get_policy().limits, "max_api_calls_per_application", 3)
    fake = FakeExtractor(PAN)
    assert upload(app, "pan", jpg(seed_text="a"), fake).status == "accepted"          # 2 calls
    out = upload(app, "aadhaar_front", jpg(seed_text="b"), FakeExtractor(detected="aadhaar_front"))   # 3rd ok, 4th trips
    assert out.status == "blocked" and out.notice.code == "API_BUDGET" and out.notice.offer_manual_review
    assert app.api_calls == 3


def test_extraction_failure_leaves_blank_fields_for_manual_entry(app):
    out = upload(app, "pan", jpg(), FakeExtractor(PAN, fail=True))
    assert out.status == "accepted"
    fields = app.slots["pan"].parts[0].fields
    assert all(f.status == FieldStatus.NOT_EXTRACTED for f in fields)
    for k, v in PAN.items():
        submit_correction(app, "pan", 0, k, v, CTX)
    assert slot_status(app.slots["pan"]) == "verified"


def test_correction_loop_three_strikes_then_manual_review(app):
    bad = dict(BANK, ifsc="HDFC1001234")
    upload(app, "bank_statement", synth.to_jpeg(synth.text_page(["BANK STATEMENT"] * 6)),
           FakeExtractor(bad, detected="bank_statement"), "stmt.jpg")
    assert slot_status(app.slots["bank_statement"]) == "needs_attention"
    f = submit_correction(app, "bank_statement", 0, "ifsc", "HDFC1001234x", CTX)
    assert f.status == FieldStatus.INVALID and f.attempts == 1 and f.failed_rule_id == "IFSC_FORMAT"
    submit_correction(app, "bank_statement", 0, "ifsc", "nope", CTX)
    f = submit_correction(app, "bank_statement", 0, "ifsc", "still bad", CTX)
    assert f.status == FieldStatus.NEEDS_MANUAL_REVIEW and f.attempts == 3
    assert slot_status(app.slots["bank_statement"]) == "manual_review"
    ok, problems = readiness(app)
    assert any("acknowledge" in p for p in problems)
    app.manual_review_ack = True
    assert not any("acknowledge" in p for p in readiness(app)[1])


def test_correction_success_is_flagged_and_reverified(app):
    bad = dict(BANK, ifsc="HDFC1001234")
    upload(app, "bank_statement", synth.to_jpeg(synth.text_page(["BANK STATEMENT"] * 6)),
           FakeExtractor(bad, detected="bank_statement"), "stmt.jpg")
    f = submit_correction(app, "bank_statement", 0, "ifsc", "hdfc0001234", CTX)
    assert f.status == FieldStatus.USER_ENTERED_VALID and f.source == "user" and f.normalized_value == "HDFC0001234"
    assert slot_status(app.slots["bank_statement"]) == "verified"


def test_wrong_bank_period_needs_reupload_not_edit(app):
    wrong = dict(BANK, statement_from="01/04/2026", statement_to="30/06/2026")
    upload(app, "bank_statement", synth.to_jpeg(synth.text_page(["BANK STATEMENT"] * 6)),
           FakeExtractor(wrong, detected="bank_statement"), "stmt.jpg")
    slot = app.slots["bank_statement"]
    assert slot_status(slot) == "needs_attention"
    issue = slot.parts[0].issues[0]
    assert issue.rule_id == "BANK_PERIOD_COVERAGE" and issue.action == "reupload"
    assert "Apr-Jun 2026" in issue.message and "Jul-Sep 2026" in issue.message
    # editing a date to something covering the window clears the issue (same rules re-run)
    submit_correction(app, "bank_statement", 0, "statement_from", "01/07/2026", CTX)
    submit_correction(app, "bank_statement", 0, "statement_to", "30/09/2026", CTX)
    assert slot_status(slot) == "verified"


def test_three_salary_slips_as_separate_files(app):
    fake = FakeExtractor([slip_fields("July 2026"), slip_fields("August 2026"), slip_fields("September 2026")],
                         detected="salary_slip")
    for i, m in enumerate(["JULY", "AUGUST", "SEPTEMBER"]):
        out = upload(app, "salary_slip", synth.to_jpeg(slip_page(m, i)), fake, f"slip{i}.jpg")
        assert out.status == "accepted"
    slot = app.slots["salary_slip"]
    assert len(slot.parts) == 3 and slot.set_issues == [] and slot_status(slot) == "verified"


def test_missing_salary_month_is_named_and_needs_reupload(app):
    fake = FakeExtractor([slip_fields("July 2026"), slip_fields("September 2026"), slip_fields("October 2026")],
                         detected="salary_slip")
    for i in range(3):
        upload(app, "salary_slip", synth.to_jpeg(slip_page("X", i)), fake, f"s{i}.jpg")
    slot = app.slots["salary_slip"]
    assert slot.set_issues[0].message == "Salary slip for August 2026 is missing."
    assert slot_status(slot) == "needs_attention"
    # remove the wrong slip, upload the missing month: the set rules re-run
    remove_part(app, "salary_slip", 2, CTX)
    fake2 = FakeExtractor(slip_fields("August 2026"), detected="salary_slip")
    upload(app, "salary_slip", synth.to_jpeg(slip_page("AUG", 9)), fake2, "aug.jpg")
    assert slot_status(slot) == "verified"


def test_slip_pdf_with_continuation_page(app):
    pages = [slip_fields("July 2026"), slip_fields("August 2026"),
             {"employee_name": "RAHUL SHARMA", "designation": "Engineer", "employee_id": "E7"},   # no pay month
             slip_fields("September 2026")]
    fake = FakeExtractor(pages, detected="salary_slip")
    out = upload(app, "salary_slip", synth.text_pdf(4), fake, "slips.pdf")
    slot = app.slots["salary_slip"]
    assert out.status == "accepted" and len(slot.parts) == 3 and slot.pages_used == 4
    aug = slot.parts[1]
    assert aug.pages == 2
    assert next(f for f in aug.fields if f.key == "designation").normalized_value == "Engineer"   # filled from page 3
    assert slot_status(slot) == "verified"


def test_slip_page_limit(app):
    out = upload(app, "salary_slip", synth.text_pdf(5), FakeExtractor(slip_fields("July 2026"), detected="salary_slip"), "five.pdf")
    assert out.status == "rejected" and out.notice.code == "SLIP_PAGE_LIMIT"
    assert app.api_calls == 0


def test_slip_pdf_over_six_pages_rejected_locally(app):
    out = upload(app, "salary_slip", synth.text_pdf(7), FakeExtractor(), "seven.pdf")
    assert out.notice.code == "PDF_TOO_MANY_PAGES"


def test_unreadable_pay_month_is_entered_by_user(app):
    fake = FakeExtractor([slip_fields("??")] * 1, detected="salary_slip")
    upload(app, "salary_slip", synth.to_jpeg(slip_page("X")), fake, "s.jpg")
    pm = next(f for f in app.slots["salary_slip"].parts[0].fields if f.key == "pay_month")
    assert pm.status == FieldStatus.NOT_EXTRACTED
    assert submit_correction(app, "salary_slip", 0, "pay_month", "Sep-26", CTX).normalized_value == "2026-09"


def test_manual_review_and_clear_slot(app):
    upload(app, "pan", jpg(), FakeExtractor({"pan_number": "BAD", "name": "RAHUL SHARMA", "dob": "15/08/1990"}))
    request_manual_review(app, "pan")
    assert slot_status(app.slots["pan"]) == "manual_review"
    uploads = app.slots["pan"].api_uploads
    clear_slot(app, "pan")
    assert app.slots["pan"].parts == [] and app.slots["pan"].api_uploads == uploads   # cap survives a clear


def test_optional_form16_is_not_required(app):
    ok, problems = readiness(app)
    assert not any("Form 16" in p for p in problems)


FORM16 = {"employee_name": "RAHUL SHARMA", "employee_pan": "ABCDE1234F", "employer_name": "ACME",
          "financial_year": "2025-26", "gross_salary": "1020000", "taxable_income": "900000", "tax_deducted": "60000"}
ITR = {"name": "RAHUL SHARMA", "pan": "ABCDE1234F", "assessment_year": "2026-27", "total_income": "900000"}


def test_form16_is_read_with_the_form16_schema(app):
    out = upload(app, "form16_or_itr", synth.to_jpeg(synth.text_page(["FORM 16"] * 6)), FakeExtractor(FORM16, detected="form16"))
    assert out.status == "accepted"
    part = app.slots["form16_or_itr"].parts[0]
    assert part.schema_type == "form16" and slot_status(app.slots["form16_or_itr"]) == "verified"


def test_itr_picks_the_itr_schema_for_the_same_slot(app):
    upload(app, "form16_or_itr", synth.to_jpeg(synth.text_page(["FORM 16"] * 6)), FakeExtractor(ITR, detected="itr"))
    part = app.slots["form16_or_itr"].parts[0]
    assert part.schema_type == "itr" and {f.key for f in part.fields} >= {"pan", "total_income"}
    assert slot_status(app.slots["form16_or_itr"]) == "verified"


def test_a_pan_in_the_form16_slot_is_a_wrong_document(app):
    out = upload(app, "form16_or_itr", synth.to_jpeg(synth.text_page(["FORM 16"] * 6)), FakeExtractor(detected="pan"))
    assert out.notice.code == "WRONG_DOCUMENT"


def test_full_application_becomes_ready(app):
    aadhaar_f = {"name": "RAHUL SHARMA", "dob": "15/08/1990", "aadhaar_number": None}
    from core.validation import verhoeff
    aadhaar_f["aadhaar_number"] = "2345 6789 012" + verhoeff.check_digit("23456789012")
    jobs = [
        ("pan", "pan.jpg", jpg(seed_text="1")),
        ("aadhaar_front", "af.jpg", jpg(seed_text="2")),
        ("aadhaar_back", "ab.jpg", jpg(seed_text="3")),
        ("bank_statement", "b.jpg", synth.to_jpeg(synth.text_page(["BANK STATEMENT"] * 6))),
    ]

    results = {"pan": PAN, "aadhaar_front": aadhaar_f, "aadhaar_back": {"address": "1 MG Road", "pincode": "560001"},
               "bank_statement": BANK}
    types = {"pan": "pan", "aadhaar_front": "aadhaar_front", "aadhaar_back": "aadhaar_back", "bank_statement": "bank_statement"}

    for sid, name, data in jobs:
        upload(app, sid, data, FakeExtractor(by_type=results, detected=types[sid]), name)
    sfake = FakeExtractor([slip_fields("July 2026"), slip_fields("August 2026"), slip_fields("September 2026")], detected="salary_slip")
    for i in range(3):
        upload(app, "salary_slip", synth.to_jpeg(slip_page("M", i)), sfake, f"s{i}.jpg")
    ok, problems = readiness(app)
    assert ok, problems
    assert progress(app) == (5, 5)


def test_process_many_runs_jobs_in_parallel_and_all_finish(app):
    fake = FakeExtractor(PAN)
    jobs = [("pan", "pan.jpg", jpg(seed_text="p")),
            ("aadhaar_front", "x.jpg", synth.to_jpeg(synth.blurry(synth.good_card())))]
    seen = []
    outs = process_many(app, jobs, fake, on_progress=lambda s, m: seen.append((s, m)), ctx=CTX)
    assert [o.status for o in outs] == ["accepted", "rejected"]
    assert any(s == "pan" and "Reading" in m for s, m in seen)
