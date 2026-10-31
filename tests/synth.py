"""Synthetic test documents. Dummy data only - never real IDs."""
import io

import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageFont


def _font(size: int):
    try:
        return ImageFont.truetype("arial.ttf", size)
    except OSError:
        return ImageFont.load_default()


def _card(size=(1200, 780), pan="ABCDE1234F", name="RAHUL SHARMA", offset=(0, 0), canvas=None):
    """A PAN-like card photographed on a textured table. Content sits inside generous margins."""
    rng = np.random.default_rng(7)
    cw, ch = canvas or size
    table = rng.integers(90, 130, (ch, cw, 3), dtype=np.uint8)
    img = Image.fromarray(table, "RGB")
    d = ImageDraw.Draw(img)
    ox, oy = offset
    w, h = size
    d.rectangle([ox, oy, ox + w, oy + h], fill=(232, 238, 247))
    big, small = _font(54), _font(36)
    d.text((ox + 60, oy + 40), "INCOME TAX DEPARTMENT   GOVT. OF INDIA", fill="black", font=small)
    d.text((ox + 60, oy + 150), "Permanent Account Number", fill="black", font=small)
    d.text((ox + 60, oy + 210), pan, fill="black", font=big)
    d.text((ox + 60, oy + 330), "Name", fill="black", font=small)
    d.text((ox + 60, oy + 380), name, fill="black", font=big)
    d.text((ox + 60, oy + 500), "Father's Name", fill="black", font=small)
    d.text((ox + 60, oy + 550), "MOHAN SHARMA", fill="black", font=big)
    d.text((ox + 60, oy + 680), "Date of Birth  15/08/1990", fill="black", font=small)
    return img


def good_card() -> Image.Image:
    # Card inset on a bigger table so no content touches the frame.
    return _card(size=(1100, 740), offset=(80, 60), canvas=(1260, 860))


def blurry(img: Image.Image, radius: float = 7) -> Image.Image:
    return img.filter(ImageFilter.GaussianBlur(radius))


def dark(img: Image.Image) -> Image.Image:
    return Image.fromarray((np.array(img) * 0.12).astype(np.uint8))


def bright(img: Image.Image) -> Image.Image:
    return Image.fromarray(np.clip(np.array(img).astype(int) + 170, 0, 255).astype(np.uint8))


def low_res(img: Image.Image) -> Image.Image:
    return img.resize((520, 340))


def cropped() -> Image.Image:
    """Card larger than the frame: text runs off the right and bottom edges."""
    return _card(size=(1500, 1100), offset=(-300, -100), canvas=(1000, 600))


def to_jpeg(img: Image.Image, quality: int = 90) -> bytes:
    buf = io.BytesIO()
    img.convert("RGB").save(buf, "JPEG", quality=quality)
    return buf.getvalue()


def text_pdf(pages: int = 1, password: str | None = None) -> bytes:
    import pymupdf
    doc = pymupdf.open()
    for i in range(pages):
        p = doc.new_page()
        p.insert_text((72, 100), "STATEMENT OF ACCOUNT " + "lorem ipsum dolor sit amet " * 6, fontsize=11)
        p.insert_text((72, 140), f"Page {i + 1}", fontsize=11)
    if password:
        return doc.tobytes(encryption=pymupdf.PDF_ENCRYPT_AES_256, user_pw=password, owner_pw=password)
    return doc.tobytes()


def text_page(lines: list[str], size=(1240, 1754)) -> Image.Image:
    """A sharp scanned A4 page (white background, black text)."""
    img = Image.new("RGB", size, "white")
    d, f = ImageDraw.Draw(img), _font(38)
    for i, t in enumerate(lines):
        d.text((80, 100 + i * 80), t, fill="black", font=f)
    return img
