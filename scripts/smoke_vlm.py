"""Smoke test: read a dummy image through every vision model (or one via --model KEY)."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from PIL import Image, ImageDraw, ImageFont

from core.vlm.client import LangChainVLM
from core.vlm.registry import list_models

img = Image.new("RGB", (900, 400), "white")
d = ImageDraw.Draw(img)
f = ImageFont.truetype("arial.ttf", 44)
for y, t in ((60, "PERMANENT ACCOUNT NUMBER"), (160, "ABCDE1234F"), (260, "RAHUL SHARMA")):
    d.text((40, y), t, fill="black", font=f)

if len(sys.argv) > 2 and sys.argv[1] == "--model":
    keys = [sys.argv[2]]
else:
    keys = [m.key for m in list_models(vision_only=True)]

for k in keys:
    try:
        out = LangChainVLM(k, "").complete("You are an OCR engine.", "Return only the text in the image.", [img])
        print(f"OK   {k}: {out.strip()!r}")
    except Exception as e:
        print(f"FAIL {k}: {e}")
