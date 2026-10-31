from datetime import date

import pymupdf

from core.extraction import extract_document, prepare_pdf
from core.models import FieldStatus
from core.validation.field_rules import make_context
from core.vlm.fake import FakeExtractor
from tests import synth

CTX = make_context(date(2026, 10, 31))
PAGES = [synth.good_card()]
GOOD_PAN = {"pan_number": "ABCDE1234F", "name": "RAHUL SHARMA", "father_name": "MOHAN SHARMA", "dob": "15/08/1990"}


def run(fake, doc="pan", expected=("pan",)):
    return extract_document(doc, list(expected), PAGES, fake, ctx=CTX)


def test_clean_extraction_all_valid():
    out = run(FakeExtractor(GOOD_PAN))
    assert out.status == "ok" and out.issues == []
    assert all(f.status == FieldStatus.VALID for f in out.fields)


def test_wrong_document_skips_extraction():
    fake = FakeExtractor(GOOD_PAN, detected="aadhaar_front")
    out = run(fake)
    assert out.status == "wrong_document" and out.classification["detected_doc_type"] == "aadhaar_front"
    assert fake.calls["extract"] == 0                         # no extraction cost


def test_unreadable_and_failures():
    assert run(FakeExtractor(detected="unreadable")).status == "unreadable"
    assert run(FakeExtractor(GOOD_PAN, fail=True)).status == "failed"


def test_bad_values_and_gaps_are_surfaced():
    out = run(FakeExtractor({"pan_number": "ABCD1234F", "name": "RAHUL SHARMA", "dob": None}))
    st = {f.key: f.status for f in out.fields}
    assert st["pan_number"] == FieldStatus.INVALID
    assert st["dob"] == FieldStatus.NOT_EXTRACTED
    assert st["name"] == FieldStatus.VALID


def test_bank_statement_with_wrong_period_gets_reupload_issue():
    raw = {"account_holder_name": "RAHUL SHARMA", "bank_name": "HDFC Bank", "account_number": "123456789012",
           "ifsc": "HDFC0001234", "statement_from": "01/04/2026", "statement_to": "30/06/2026"}
    out = run(FakeExtractor(raw, detected="bank_statement"), "bank_statement", ("bank_statement",))
    assert [i.rule_id for i in out.issues] == ["BANK_PERIOD_COVERAGE"] and out.issues[0].action == "reupload"


def test_bank_pdf_keeps_first_and_last_page_only():
    doc = pymupdf.open()
    for i in range(8):
        doc.new_page().insert_text((72, 100), f"page {i}")
    sliced = pymupdf.open(stream=prepare_pdf("bank_statement", doc.tobytes()), filetype="pdf")
    assert sliced.page_count == 2
    assert "page 0" in sliced[0].get_text() and "page 7" in sliced[1].get_text()


def test_classifier_outage_does_not_blank_the_document():
    out = run(FakeExtractor(GOOD_PAN, classify_fail=True))
    assert out.status == "ok" and out.classification.get("unchecked")
    assert all(f.status == FieldStatus.VALID for f in out.fields)


def test_a_failed_read_is_retried_once():
    class Flaky(FakeExtractor):
        def extract(self, *a, **k):
            if self.calls["extract"] == 0:
                self.calls["extract"] += 1
                raise RuntimeError("blip")
            return super().extract(*a, **k)
    fake = Flaky(GOOD_PAN)
    assert run(fake).status == "ok" and fake.calls["extract"] == 2
