"""PDF handling: open, encryption check, page cap, render pages to images."""
import pymupdf
from PIL import Image

from core.models import DocSpec, QualityIssue


class PdfOpenResult:
    def __init__(self):
        self.pages: list[Image.Image] = []
        self.page_count = 0
        self.has_text_layer = False
        self.issues: list[QualityIssue] = []


def open_pdf(data: bytes, spec: DocSpec, max_pages: int, dpi: int, render_limit: int = 3) -> PdfOpenResult:
    out = PdfOpenResult()
    name = spec.display_name
    try:
        doc = pymupdf.open(stream=data, filetype="pdf")
    except Exception:
        out.issues.append(QualityIssue(
            code="UNREADABLE", severity="error",
            message=f"{name} - we couldn't open this PDF.",
            fix_hint="Download a fresh copy of the document and upload it again."))
        return out

    if doc.needs_pass:
        out.issues.append(QualityIssue(
            code="PDF_ENCRYPTED", severity="error",
            message=f"{name} - this PDF is password protected.",
            fix_hint="Remove the password, or download a fresh copy, then upload it again."))
        return out

    out.page_count = doc.page_count
    if doc.page_count == 0:
        out.issues.append(QualityIssue(
            code="UNREADABLE", severity="error", message=f"{name} - this PDF has no pages.",
            fix_hint="Download a fresh copy of the document and upload it again."))
        return out
    if doc.page_count > max_pages:
        out.issues.append(QualityIssue(
            code="PDF_TOO_MANY_PAGES", severity="error",
            message=f"{name} - this PDF has {doc.page_count} pages.",
            fix_hint=f"Upload only the relevant document (at most {max_pages} pages).",
            metric={"pages": doc.page_count, "max": max_pages}))
        return out

    out.has_text_layer = any(len(doc[i].get_text().strip()) > 40 for i in range(min(doc.page_count, render_limit)))
    for i in range(min(doc.page_count, render_limit)):
        pix = doc[i].get_pixmap(dpi=dpi)
        out.pages.append(Image.frombytes("RGB", (pix.width, pix.height), pix.samples))
    return out
