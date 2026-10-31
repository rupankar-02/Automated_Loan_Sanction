"""Generate synthetic demo documents into demo_data/. Fictional person, fictional numbers: never real IDs.

  python scripts/make_demo_docs.py

Months follow the app's reference date (today in IST unless pinned in policy.yaml), so the files stay valid.
"""
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import numpy as np
import pymupdf
from PIL import Image, ImageDraw, ImageFilter, ImageFont

from core.config.loader import get_policy
from core.utils.dates import reference_date
from core.validation import verhoeff
from core.validation.months import add_months, month_name, required_window, window_bounds

OUT = Path(__file__).resolve().parents[1] / "demo_data"
NAME, FATHER = "RAHUL SHARMA", "MOHAN SHARMA"
PAN_NO = "ABCPE1234F"
DOB = "15/08/1992"
AADHAAR = "2345 6789 012" + verhoeff.check_digit("23456789012")
ACCOUNT = "50100123456789"
EMPLOYER = "ACME TECHNOLOGIES PVT LTD"


def font(size, bold=False):
    for name in (("arialbd.ttf" if bold else "arial.ttf"),):
        try:
            return ImageFont.truetype(name, size)
        except OSError:
            pass
    return ImageFont.load_default()


def save(img: Image.Image, name: str, quality=92) -> None:
    img.convert("RGB").save(OUT / name, "JPEG", quality=quality)


def table_background(w, h, seed=3) -> Image.Image:
    rng = np.random.default_rng(seed)
    return Image.fromarray(rng.integers(95, 135, (h, w, 3), dtype=np.uint8), "RGB")


def card(width=1100, height=700, fill=(232, 238, 247)) -> tuple[Image.Image, ImageDraw.ImageDraw, int, int]:
    """A card photographed on a textured table, with margins so nothing touches the frame."""
    bg = table_background(width + 160, height + 120)
    d = ImageDraw.Draw(bg)
    x0, y0 = 80, 60
    d.rectangle([x0, y0, x0 + width, y0 + height], fill=fill)
    return bg, d, x0, y0


# ---- identity ---------------------------------------------------------------------------------------------------------

def pan_card() -> Image.Image:
    img, d, x, y = card()
    d.rectangle([x, y, x + 1100, y + 90], fill=(40, 70, 140))
    d.text((x + 30, y + 22), "INCOME TAX DEPARTMENT        GOVT. OF INDIA", fill="white", font=font(36, True))
    d.text((x + 40, y + 130), "Permanent Account Number", fill="black", font=font(30))
    d.text((x + 40, y + 175), PAN_NO, fill="black", font=font(56, True))
    d.text((x + 40, y + 270), "Name", fill="black", font=font(28))
    d.text((x + 40, y + 310), NAME, fill="black", font=font(48, True))
    d.text((x + 40, y + 400), "Father's Name", fill="black", font=font(28))
    d.text((x + 40, y + 440), FATHER, fill="black", font=font(48, True))
    d.text((x + 40, y + 550), "Date of Birth", fill="black", font=font(28))
    d.text((x + 40, y + 590), DOB, fill="black", font=font(48, True))
    return img


def aadhaar_front() -> Image.Image:
    img, d, x, y = card(fill=(250, 244, 230))
    d.rectangle([x, y, x + 1100, y + 90], fill=(200, 80, 40))
    d.text((x + 30, y + 22), "Government of India      AADHAAR", fill="white", font=font(38, True))
    d.text((x + 40, y + 150), NAME, fill="black", font=font(54, True))
    d.text((x + 40, y + 240), f"DOB: {DOB}", fill="black", font=font(44))
    d.text((x + 40, y + 320), "Gender: Male", fill="black", font=font(44))
    d.text((x + 40, y + 480), AADHAAR, fill="black", font=font(72, True))
    d.text((x + 40, y + 600), "Your Aadhaar No.", fill="black", font=font(28))
    return img


def aadhaar_back() -> Image.Image:
    img, d, x, y = card(fill=(250, 244, 230))
    d.rectangle([x, y, x + 1100, y + 90], fill=(200, 80, 40))
    d.text((x + 30, y + 22), "Unique Identification Authority of India", fill="white", font=font(36, True))
    d.text((x + 40, y + 150), "Address:", fill="black", font=font(40, True))
    for i, line in enumerate(["S/O Mohan Sharma", "12, MG Road, Indiranagar", "Bengaluru, Karnataka", "PIN Code: 560001"]):
        d.text((x + 40, y + 220 + i * 70), line, fill="black", font=font(46))
    return img


# ---- income -----------------------------------------------------------------------------------------------------------

def salary_slip(month: tuple[int, int], gross=85000, deductions=12500) -> Image.Image:
    img = Image.new("RGB", (1240, 1754), "white")
    d = ImageDraw.Draw(img)
    d.text((70, 70), EMPLOYER, fill="black", font=font(52, True))
    d.text((70, 150), "Bengaluru, Karnataka", fill=(80, 80, 80), font=font(30))
    d.text((70, 240), f"SALARY SLIP FOR THE MONTH OF {month_name(month).upper()}", fill="black", font=font(40, True))
    rows = [("Employee Name", NAME), ("Employee ID", "E1042"), ("Designation", "Software Engineer"), ("Department", "Engineering")]
    for i, (k, v) in enumerate(rows):
        d.text((70, 340 + i * 60), f"{k}: {v}", fill="black", font=font(36))
    d.line([70, 600, 1170, 600], fill="black", width=3)
    d.text((70, 620), "EARNINGS", fill="black", font=font(34, True))
    d.text((640, 620), "DEDUCTIONS", fill="black", font=font(34, True))
    earn = [("Basic", round(gross * 0.5)), ("HRA", round(gross * 0.25)), ("Special Allowance", gross - round(gross * 0.5) - round(gross * 0.25))]
    ded = [("Provident Fund", round(deductions * 0.4)), ("Professional Tax", 200), ("Income Tax (TDS)", deductions - round(deductions * 0.4) - 200)]
    for i, (k, v) in enumerate(earn):
        d.text((70, 690 + i * 60), f"{k}: {v:,.2f}", fill="black", font=font(34))
    for i, (k, v) in enumerate(ded):
        d.text((640, 690 + i * 60), f"{k}: {v:,.2f}", fill="black", font=font(34))
    d.line([70, 900, 1170, 900], fill="black", width=3)
    d.text((70, 930), f"Gross Earnings: Rs. {gross:,.2f}", fill="black", font=font(38, True))
    d.text((640, 930), f"Total Deductions: Rs. {deductions:,.2f}", fill="black", font=font(38, True))
    d.text((70, 1040), f"Net Pay: Rs. {gross - deductions:,.2f}", fill="black", font=font(46, True))
    d.text((70, 1650), "This is a computer generated payslip.", fill=(90, 90, 90), font=font(26))
    return img


def form16() -> Image.Image:
    img = Image.new("RGB", (1240, 1754), "white")
    d = ImageDraw.Draw(img)
    d.text((70, 70), "FORM NO. 16", fill="black", font=font(56, True))
    d.text((70, 150), "Certificate under section 203 of the Income-tax Act, 1961", fill="black", font=font(30))
    rows = [f"Financial Year: 2025-26", f"Name of the Employee: {NAME}", f"PAN of the Employee: {PAN_NO}",
            f"Name of the Employer: {EMPLOYER}", "TAN of the Employer: BLRA12345B",
            "Gross Salary: Rs. 10,20,000.00", "Total Taxable Income: Rs. 9,00,000.00", "Total Tax Deducted at Source: Rs. 60,000.00"]
    for i, r in enumerate(rows):
        d.text((70, 280 + i * 85), r, fill="black", font=font(38))
    return img


def bank_statement_pdf(start: date, end: date, ifsc="HDFC0001234", months: list[tuple[int, int]] | None = None) -> bytes:
    doc = pymupdf.open()
    p = doc.new_page()
    y = 72
    for text, size in [("HDFC BANK LTD", 18), ("STATEMENT OF ACCOUNT", 13), ("", 8),
                       (f"Account Holder: {NAME}", 12), (f"Account Number: {ACCOUNT}", 12), (f"IFSC: {ifsc}", 12),
                       ("Branch: Indiranagar, Bengaluru", 12),
                       (f"Statement Period: {start:%d/%m/%Y} to {end:%d/%m/%Y}", 12), ("Opening Balance: Rs. 54,300.00", 12), ("", 8),
                       ("Date        Narration                          Debit        Credit        Balance", 10)]:
        p.insert_text((60, y), text, fontsize=size, fontname="helv")
        y += size + 8
    bal = 54300
    for m in months or []:
        for day, narr, debit, credit in [(1, "SALARY ACME TECHNOLOGIES", 0, 72500), (5, "RENT PAYMENT", 22000, 0), (12, "UPI GROCERIES", 3400, 0), (20, "ELECTRICITY BILL", 2100, 0)]:
            bal += credit - debit
            p.insert_text((60, y), f"{day:02d}/{m[1]:02d}/{m[0]}  {narr:<30} {debit:>9,.2f}  {credit:>10,.2f}  {bal:>11,.2f}", fontsize=9, fontname="courier")
            y += 14
    last = doc.new_page()
    last.insert_text((60, 90), "Closing Balance: Rs. %s" % f"{bal:,.2f}", fontsize=12, fontname="helv")
    last.insert_text((60, 120), "This is a computer generated statement and does not require a signature.", fontsize=10, fontname="helv")
    return doc.tobytes()


def main() -> None:
    OUT.mkdir(exist_ok=True)
    today = reference_date()
    window = required_window(today, get_policy())                  # e.g. Jul-Sep 2026
    w0, w1 = window_bounds(window)
    older = [add_months(m, -3) for m in window]                    # the wrong period: three months earlier
    older0, older1 = window_bounds(older)

    save(pan_card(), "01_pan_card.jpg")
    save(aadhaar_front(), "02_aadhaar_front.jpg")
    save(aadhaar_back(), "03_aadhaar_back.jpg")
    for i, m in enumerate(window, 1):
        save(salary_slip(m, 85000 + i * 500, 12500), f"04_salary_slip_{m[0]}-{m[1]:02d}.jpg")
    (OUT / "05_bank_statement_OK.pdf").write_bytes(bank_statement_pdf(w0, w1, months=window))
    save(form16(), "06_form16_optional.jpg")

    # --- failure scenarios, each one demonstrates a specific catch ---
    save(pan_card().filter(ImageFilter.GaussianBlur(7)), "X1_pan_card_BLURRY.jpg")
    dark = (np.array(pan_card()) * 0.12).astype(np.uint8)
    save(Image.fromarray(dark), "X2_pan_card_TOO_DARK.jpg")
    save(pan_card().resize((520, 340)), "X3_pan_card_LOW_RESOLUTION.jpg")
    # "wrong document": upload 02_aadhaar_front.jpg into the PAN box
    (OUT / "X4_bank_statement_WRONG_PERIOD.pdf").write_bytes(bank_statement_pdf(older0, older1, months=older))
    (OUT / "X5_bank_statement_IFSC_TYPO.pdf").write_bytes(bank_statement_pdf(w0, w1, ifsc="HDFC1001234", months=window))
    extra = add_months(window[-1], 1)                              # the current month: accepted, never required
    save(salary_slip(extra, 86000, 12500), f"X6_salary_slip_{extra[0]}-{extra[1]:02d}_current_month.jpg")
    skip = window[1]
    print(f"reference date {today}; required months {month_name(window[0])} to {month_name(window[-1])}")
    print(f"missing-month demo: upload slips for {month_name(window[0])}, {month_name(window[2])} and {month_name(extra)} -> '{month_name(skip)} is missing'")
    print(f"aadhaar {AADHAAR}  pan {PAN_NO}  files: {len(list(OUT.glob('*')))}")


if __name__ == "__main__":
    main()
