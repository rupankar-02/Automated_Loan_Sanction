"""Smoke test: Sarvam Vision field extraction from a synthetic PAN-like image."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from PIL import Image, ImageDraw, ImageFont

from core.vlm.sarvam_doc import SarvamVisionExtractor

img = Image.new("RGB", (1000, 640), "#e8eef7")
d = ImageDraw.Draw(img)
big, small = ImageFont.truetype("arial.ttf", 44), ImageFont.truetype("arial.ttf", 32)
d.text((40, 30), "INCOME TAX DEPARTMENT   GOVT. OF INDIA", fill="black", font=small)
d.text((40, 130), "Permanent Account Number", fill="black", font=small)
d.text((40, 180), "ABCDE1234F", fill="black", font=big)
d.text((40, 270), "Name", fill="black", font=small)
d.text((40, 310), "RAHUL SHARMA", fill="black", font=big)
d.text((40, 400), "Father's Name", fill="black", font=small)
d.text((40, 440), "MOHAN SHARMA", fill="black", font=big)
d.text((40, 530), "Date of Birth  15/08/1990", fill="black", font=small)

fields = [
    {"key": "pan_number", "description": "10-character Permanent Account Number, exactly as printed"},
    {"key": "name", "description": "Cardholder's full name, exactly as printed"},
    {"key": "father_name", "description": "Father's name, exactly as printed"},
    {"key": "dob", "description": "Date of birth, exactly as printed"},
]
print(SarvamVisionExtractor().extract(fields, images=[img]))

from core.vlm.roles import classify_document
print(classify_document([img]))
