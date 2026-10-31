"""Build a fully-uploaded, ready-to-save application from synthetic documents and a fake extractor."""
from datetime import date

from core.pipeline import process_upload
from core.state import new_application, readiness
from core.validation import verhoeff
from core.validation.field_rules import make_context
from core.vlm.fake import FakeExtractor
from tests import synth

CTX = make_context(date(2026, 10, 31))
PAN_NO = "ABCDE1234F"
AADHAAR_NO = "234567890123"[:11] + verhoeff.check_digit("23456789012")
ACCOUNT_NO = "123456789012"
PAN = {"pan_number": PAN_NO, "name": "RAHUL SHARMA", "father_name": "MOHAN SHARMA", "dob": "15/08/1990"}
BANK = {"account_holder_name": "RAHUL SHARMA", "bank_name": "HDFC Bank", "account_number": ACCOUNT_NO,
        "ifsc": "HDFC0001234", "statement_from": "01/07/2026", "statement_to": "30/09/2026"}


def slip(month):
    return {"employee_name": "RAHUL SHARMA", "employer_name": "ACME", "pay_month": month,
            "gross_salary": "85000", "net_salary": "72500", "total_deductions": "12500"}


def build_ready_app(store=None):
    app = new_application("personal", "salaried")
    results = {"pan": PAN, "aadhaar_front": {"name": "RAHUL SHARMA", "dob": "15/08/1990", "aadhaar_number": AADHAAR_NO},
               "aadhaar_back": {"address": "1 MG Road, Bengaluru", "pincode": "560001"}, "bank_statement": BANK}
    for i, (sid, det) in enumerate([("pan", "pan"), ("aadhaar_front", "aadhaar_front"),
                                    ("aadhaar_back", "aadhaar_back"), ("bank_statement", "bank_statement")]):
        img = synth.good_card() if sid != "bank_statement" else synth.text_page(["BANK STATEMENT"] * 6)
        from PIL import ImageDraw
        ImageDraw.Draw(img).text((5, 5), f"doc{i}", fill=(90, 90, 90))
        out = process_upload(app, sid, f"{sid}.jpg", synth.to_jpeg(img), FakeExtractor(by_type=results, detected=det),
                             ctx=CTX, store=store)
        assert out.status == "accepted", (sid, out.notice)
    sf = FakeExtractor([slip("July 2026"), slip("August 2026"), slip("September 2026")], detected="salary_slip")
    for i in range(3):
        out = process_upload(app, "salary_slip", f"s{i}.jpg", synth.to_jpeg(synth.text_page([f"SLIP {i}"] * 6)), sf,
                             ctx=CTX, store=store)
        assert out.status == "accepted"
    ok, problems = readiness(app)
    assert ok, problems
    return app
