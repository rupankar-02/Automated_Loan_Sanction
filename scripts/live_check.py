"""Live end-to-end check: Gemini classifies, Sarvam extracts, rules validate (synthetic docs only)."""
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from PIL import Image, ImageDraw, ImageFont

from core.extraction import extract_document
from core.validation.field_rules import make_context
from core.vlm.roles import LiveExtractor
from tests import synth

ctx = make_context(date(2026, 10, 31))
f = ImageFont.truetype("arial.ttf", 34)
slip = Image.new("RGB", (1240, 1000), "white")
d = ImageDraw.Draw(slip)
rows = ["ACME TECHNOLOGIES PVT LTD", "SALARY SLIP FOR THE MONTH OF SEP-26", "Employee Name: RAHUL SHARMA",
        "Employee ID: E1042    Designation: Software Engineer", "Gross Earnings: Rs. 85,000.00",
        "Total Deductions: Rs. 12,500.00", "Net Pay: Rs. 72,500.00"]
for i, t in enumerate(rows):
    d.text((60, 60 + i * 90), t, fill="black", font=f)

cases = [("pan", ["pan"], synth.good_card()), ("salary_slip", ["salary_slip"], slip)]
for doc_type, expected, img in cases:
    out = extract_document(doc_type, expected, [img], LiveExtractor(), ctx=ctx)
    print(f"\n== {doc_type}: {out.status} {out.classification}")
    for fr in out.fields:
        print(f"  {fr.key:18} {fr.status.value:14} raw={fr.raw_value!r} norm={fr.normalized_value!r} {fr.message or ''}")
    for i in out.issues:
        print("  ISSUE", i.rule_id, i.message)
