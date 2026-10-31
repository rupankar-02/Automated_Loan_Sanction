"""Run every file in demo_data/ through the live pipeline and print what the demo will show."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.stdout.reconfigure(encoding="utf-8")

from core.pipeline import process_many, process_upload
from core.state import new_application, readiness, slot_status
from core.vlm.roles import LiveExtractor

D = Path(__file__).resolve().parents[1] / "demo_data"
ext = LiveExtractor()


def up(app, slot, fname):
    return process_upload(app, slot, fname, (D / fname).read_bytes(), ext)


def show(app, slot):
    s = app.slots[slot]
    bad = [(f.key, f.status.value, f.raw_value) for p in s.parts for f in p.fields if f.status.value != "valid" and f.required]
    print(f"   {slot:15} {slot_status(s):16} bad={bad} issues={[i.message for p in s.parts for i in p.issues] + [i.message for i in s.set_issues]}")


print("== happy path, all five slots in parallel")
app = new_application("personal", "salaried")
jobs = [("pan", "01_pan_card.jpg"), ("aadhaar_front", "02_aadhaar_front.jpg"), ("aadhaar_back", "03_aadhaar_back.jpg"),
        ("salary_slip", "04_salary_slip_2026-07.jpg"), ("salary_slip", "04_salary_slip_2026-08.jpg"),
        ("salary_slip", "04_salary_slip_2026-09.jpg"), ("bank_statement", "05_bank_statement_OK.pdf"),
        ("form16_or_itr", "06_form16_optional.jpg")]
outs = process_many(app, [(s, f, (D / f).read_bytes()) for s, f in jobs], ext)
for (s, f), o in zip(jobs, outs):
    print(f" {f:34} -> {s:15} {o.status} {o.notice.message if o.notice else ''}")
for slot in app.slots:
    show(app, slot)
print("   READY:", readiness(app), "api_calls", app.api_calls)

print("\n== local rejections (free)")
a2 = new_application("personal", "salaried")
for f in ("X1_pan_card_BLURRY.jpg", "X2_pan_card_TOO_DARK.jpg", "X3_pan_card_LOW_RESOLUTION.jpg"):
    o = up(a2, "pan", f)
    print(f" {f:34} {o.status} {o.notice.code}: {o.notice.message} | {o.notice.fix_hint}")
print("   api_calls", a2.api_calls)

print("\n== wrong document: Aadhaar front into the PAN box")
o = up(a2, "pan", "02_aadhaar_front.jpg")
print(f"   {o.status} {o.notice.message}")

print("\n== wrong bank period")
a3 = new_application("personal", "salaried")
up(a3, "bank_statement", "X4_bank_statement_WRONG_PERIOD.pdf")
show(a3, "bank_statement")

print("\n== IFSC typo")
a4 = new_application("personal", "salaried")
up(a4, "bank_statement", "X5_bank_statement_IFSC_TYPO.pdf")
show(a4, "bank_statement")

print("\n== missing month: Jul + Sep + Oct")
a5 = new_application("personal", "salaried")
for f in ("04_salary_slip_2026-07.jpg", "04_salary_slip_2026-09.jpg", "X6_salary_slip_2026-10_current_month.jpg"):
    up(a5, "salary_slip", f)
show(a5, "salary_slip")
