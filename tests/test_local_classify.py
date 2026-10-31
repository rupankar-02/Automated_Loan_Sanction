from pathlib import Path

import pytest

from core.chat.llm import LangChainChat, get_chat_llm
from core.quality.gate import run_quality_checks
from core.requirements import build_checklist
from core.vlm.local_classify import classify_text

DEMO = Path(__file__).resolve().parents[1] / "demo_data"
SPECS = {d.id: d for d in build_checklist("personal", "salaried")}

TEXTS = {
    "pan": "INCOME TAX DEPARTMENT GOVT. OF INDIA Permanent Account Number ABCPE1234F Name RAHUL SHARMA Father's Name MOHAN SHARMA",
    "aadhaar_front": "Government of India AADHAAR RAHUL SHARMA DOB: 15/08/1992 Gender: Male 2345 6789 0124 Your Aadhaar No.",
    "aadhaar_back": "Unique Identification Authority of India Address: S/O Mohan Sharma 12 MG Road Bengaluru PIN Code: 560001",
    "salary_slip": "ACME PVT LTD SALARY SLIP FOR THE MONTH OF AUGUST 2026 Employee Name: RAHUL EARNINGS DEDUCTIONS Net Pay: Rs. 72,500",
    "bank_statement": "HDFC BANK LTD STATEMENT OF ACCOUNT Account Number: 50100123 IFSC: HDFC0001234 Opening Balance Closing Balance",
    "form16": "FORM NO. 16 Certificate under section 203 of the Income-tax Act Name of the Employer TAN of the Employer",
    "itr": "ITR-1 INDIAN INCOME TAX RETURN ACKNOWLEDGEMENT Assessment Year 2026-27",
}


@pytest.mark.parametrize("expected,text", TEXTS.items())
def test_keyword_classification(expected, text):
    assert classify_text(text)[0] == expected


def test_unreadable_and_unknown_text():
    assert classify_text("")[0] == "unreadable" and classify_text("a b")[0] == "unreadable"
    assert classify_text("Today we are going to the market to buy some vegetables and fruit")[0] == "other"


def test_a_pan_number_alone_is_not_enough_to_call_it_a_pan():
    assert classify_text("Please remember my number ABCPE1234F for later use thanks")[0] == "other"


def test_form16_is_not_mistaken_for_a_pan_card():
    assert classify_text("FORM NO. 16 PAN of the Employee ABCPE1234F Income tax Section 203 TAN")[0] == "form16"


def test_bank_statement_is_not_mistaken_for_a_salary_slip():
    t = "STATEMENT OF ACCOUNT Opening Balance IFSC SALARY CREDIT ACME Net Closing Balance Branch"
    assert classify_text(t)[0] == "bank_statement"


# ---- the real demo files, through real local OCR -----------------------------------------------------------------------

DEMO_EXPECTED = [
    ("01_pan_card.jpg", "pan", "pan"), ("02_aadhaar_front.jpg", "aadhaar", "aadhaar_front"),
    ("03_aadhaar_back.jpg", "aadhaar", "aadhaar_back"), ("04_salary_slip_2026-08.jpg", "salary_slip", "salary_slip"),
    ("05_bank_statement_OK.pdf", "bank_statement", "bank_statement"), ("06_form16_optional.jpg", "form16_or_itr", "form16"),
    ("X4_bank_statement_WRONG_PERIOD.pdf", "bank_statement", "bank_statement"),
]


@pytest.mark.skipif(not DEMO.exists(), reason="demo_data not generated")
@pytest.mark.parametrize("fname,slot,expected", DEMO_EXPECTED)
def test_demo_documents_are_classified_by_local_ocr(fname, slot, expected):
    pytest.importorskip("rapidocr")
    from core.vlm.local_classify import classify_document_local
    _, pages = run_quality_checks(fname, (DEMO / fname).read_bytes(), SPECS[slot])
    out = classify_document_local(pages)
    assert out["detected_doc_type"] == expected, out
    assert out["source"] == "local_ocr"


@pytest.mark.skipif(not DEMO.exists(), reason="demo_data not generated")
def test_wrong_document_is_caught_locally():
    pytest.importorskip("rapidocr")
    from core.vlm.local_classify import classify_document_local
    _, pages = run_quality_checks("02_aadhaar_front.jpg", (DEMO / "02_aadhaar_front.jpg").read_bytes(), SPECS["pan"])
    assert classify_document_local(pages)["detected_doc_type"] == "aadhaar_front"      # not "pan": the PAN box rejects it


# ---- chat fallback order: Gemini first, Sarvam 105B when Gemini does not work ------------------------------------------------

def test_english_chat_tries_gemini_then_sarvam():
    llm = get_chat_llm("en")
    order = [k for k, _ in llm._attempts()]
    assert order[0].startswith("gemini:") and order[-1] == "sarvam:sarvam-105b"
    assert any(k.startswith("gemini:") for k in order[:-1])


def test_hindi_chat_prefers_sarvam_then_gemini():
    order = [k for k, _ in get_chat_llm("hi")._attempts()]
    assert order[0] == "sarvam:sarvam-105b" and any(k.startswith("gemini:") for k in order[1:])


def test_chat_falls_through_to_sarvam_when_gemini_fails(monkeypatch):
    import core.chat.llm as m

    class Boom:
        def __init__(self, key):
            self.key = key

        def invoke(self, msgs):
            if self.key.startswith("gemini"):
                raise RuntimeError("503 UNAVAILABLE")
            return type("R", (), {"content": "Sarvam answered."})()

    monkeypatch.setattr(m, "build_chat_model", lambda key, **kw: Boom(key))
    monkeypatch.setattr(m, "is_cooling", lambda *a: False)
    monkeypatch.setattr(m, "mark_bad", lambda *a: None)
    llm = LangChainChat("gemini:gemini-3-flash-preview", fallback_keys=["gemini:gemini-3.5-flash", "sarvam:sarvam-105b"])
    assert llm.complete("sys", [], "hi") == "Sarvam answered." and llm.last_model == "sarvam:sarvam-105b"
