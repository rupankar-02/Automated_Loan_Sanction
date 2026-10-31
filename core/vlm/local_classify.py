"""Document-type check with no API call: local OCR (RapidOCR) + keyword scoring.

Replaces the Gemini classification step, which was slow and often unavailable. Fields are still read by
Sarvam Vision and judged by the rules, so a mistake here can only produce a clear message, never a wrong value.
"""
import re
import threading

import numpy as np
from PIL import Image

_engine = None
_lock = threading.Lock()                      # one OCR engine, used one page at a time


def _get_engine():
    global _engine
    if _engine is None:
        from rapidocr import RapidOCR
        _engine = RapidOCR()
    return _engine


def ocr_text(img: Image.Image, max_side: int = 1800) -> str:
    img = img.convert("RGB")
    img.thumbnail((max_side, max_side))
    with _lock:
        result = _get_engine()(np.array(img))
    return " ".join(result.txts) if result.txts else ""


# (regex, weight). Matched against upper-cased text with whitespace collapsed.
KEYWORDS: dict[str, list[tuple[str, int]]] = {
    "pan": [(r"INCOME\s*TAX\s*DEPARTMENT", 3), (r"PERMANENT\s*ACCOUNT\s*NUMBER", 4), (r"\b[A-Z]{5}\d{4}[A-Z]\b", 2),
            (r"GOVT\.?\s*OF\s*INDIA", 1), (r"FATHER'?S?\s*NAME", 1)],
    "aadhaar_front": [(r"AADHAA?R", 3), (r"GOVERNMENT\s*OF\s*INDIA", 2), (r"\b\d{4}\s?\d{4}\s?\d{4}\b", 2),
                      (r"\bDOB\b|DATE\s*OF\s*BIRTH|YEAR\s*OF\s*BIRTH", 1), (r"\bMALE\b|\bFEMALE\b|TRANSGENDER", 1)],
    "aadhaar_back": [(r"UNIQUE\s*IDENTIFICATION", 3), (r"\bADDRESS\b", 3), (r"PIN\s*CODE|PINCODE", 2),
                     (r"\b[SCDW]/O\b", 1), (r"AADHAA?R", 1)],
    "salary_slip": [(r"SALARY\s*SLIP|PAY\s*SLIP|PAYSLIP|SALARY\s*STATEMENT|MONTH\s*OF", 3), (r"NET\s*PAY|NET\s*SALARY|TAKE\s*HOME", 2),
                    (r"EARNINGS", 1), (r"DEDUCTIONS", 1), (r"\bGROSS\b", 1), (r"EMPLOYEE\s*(NAME|ID|CODE)", 1)],
    "bank_statement": [(r"STATEMENT\s*OF\s*ACCOUNT|ACCOUNT\s*STATEMENT|BANK\s*STATEMENT", 4), (r"OPENING\s*BALANCE", 2),
                       (r"CLOSING\s*BALANCE", 2), (r"\bIFSC\b", 2), (r"ACCOUNT\s*(NUMBER|NO)|A/C\s*NO", 1),
                       (r"NARRATION|WITHDRAWAL|DEPOSIT|\bDEBIT\b|\bCREDIT\b", 1), (r"\bBRANCH\b", 1)],
    "form16": [(r"FORM\s*NO\.?\s*16|\bFORM\s*16\b", 5), (r"SECTION\s*203", 2), (r"\bTAN\b", 1),
               (r"TAX\s*DEDUCTED\s*AT\s*SOURCE", 1), (r"NAME\s*OF\s*THE\s*EMPLOYER", 1)],
    "itr": [(r"ITR[-\s]?[1-7]\b|INCOME\s*TAX\s*RETURN", 3), (r"ACKNOWLEDGEMENT", 3), (r"ASSESSMENT\s*YEAR", 2)],
    "utility_bill": [(r"ELECTRICITY|WATER\s*BILL|GAS\s*BILL|BROADBAND|CONSUMER\s*(NO|NUMBER)", 3), (r"BILL\s*DATE|DUE\s*DATE", 1)],
}
MIN_SCORE = 4          # weakest evidence we will call a match
MIN_TEXT_CHARS = 15    # below this the page is effectively unreadable


def classify_text(text: str) -> tuple[str, dict[str, int]]:
    up = re.sub(r"\s+", " ", text.upper())
    scores = {t: sum(w for rx, w in rules if re.search(rx, up)) for t, rules in KEYWORDS.items()}
    if len(up.strip()) < MIN_TEXT_CHARS:
        return "unreadable", scores
    best = max(scores, key=scores.get)
    ranked = sorted(scores.values(), reverse=True)
    if scores[best] < MIN_SCORE or (len(ranked) > 1 and ranked[0] == ranked[1]):
        return "other", scores
    return best, scores


def classify_document_local(images: list[Image.Image]) -> dict:
    text = ocr_text(images[0])
    doc_type, scores = classify_text(text)
    return {"detected_doc_type": doc_type, "fully_visible": True,        # cropping is judged by the local image checks
            "legibility": "good" if len(text) > 80 else ("fair" if len(text) >= MIN_TEXT_CHARS else "poor"),
            "source": "local_ocr", "scores": scores}
