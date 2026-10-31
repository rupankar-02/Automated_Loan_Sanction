"""Live pipeline check through the full process_upload path (synthetic docs, real Gemini + Sarvam)."""
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from core.pipeline import process_many
from core.state import new_application, progress, slot_status
from core.validation.field_rules import make_context
from core.vlm.roles import LiveExtractor
from tests import synth

app = new_application("personal", "salaried")
slip = synth.text_page(["ACME TECHNOLOGIES PVT LTD", "SALARY SLIP FOR THE MONTH OF SEP-26", "Employee Name: RAHUL SHARMA",
                        "Gross Earnings: Rs. 85,000.00", "Total Deductions: Rs. 12,500.00", "Net Pay: Rs. 72,500.00"])
jobs = [("pan", "pan.jpg", synth.to_jpeg(synth.good_card())),
        ("salary_slip", "slip.jpg", synth.to_jpeg(slip)),
        ("aadhaar_front", "wrong.jpg", synth.to_jpeg(synth.good_card(), 80))]   # a PAN image in the Aadhaar slot
outs = process_many(app, jobs, LiveExtractor(), on_progress=lambda s, m: print(f"  [{s}] {m}"), ctx=make_context(date(2026, 10, 31)))
for o in outs:
    print(o.slot_id, o.status, o.notice.message if o.notice else "")
for sid in ("pan", "salary_slip"):
    s = app.slots[sid]
    print(sid, slot_status(s), [(f.key, f.status.value) for p in s.parts for f in p.fields if f.status.value != "valid"], [i.message for i in s.set_issues])
print("api_calls", app.api_calls, "progress", progress(app))
