"""Quality gate: runs before any API call. Returns the verdict plus the loaded page images."""
import io
from pathlib import Path

from PIL import Image

from core.config.loader import get_policy
from core.models import DocSpec, QualityIssue, QualityResult
from core.quality.image_checks import check_image, load_oriented
from core.quality.pdf_checks import open_pdf

IMAGE_EXT = {"jpg", "jpeg", "png"}


def _fail(issue: QualityIssue) -> tuple[QualityResult, list[Image.Image]]:
    return QualityResult(passed=False, issues=[issue]), []


def run_quality_checks(filename: str, data: bytes, spec: DocSpec) -> tuple[QualityResult, list[Image.Image]]:
    policy = get_policy()
    name = spec.display_name
    ext = Path(filename).suffix.lower().lstrip(".")

    accepted = set()
    if "image" in spec.accepts:
        accepted |= IMAGE_EXT
    if "pdf" in spec.accepts:
        accepted.add("pdf")
    if ext not in policy.files.allowed_ext or ext not in accepted:
        return _fail(QualityIssue(
            code="BAD_FORMAT", severity="error",
            message=f"{name} - '.{ext or '?'}' files are not supported.",
            fix_hint="Please upload a JPG, PNG or PDF. For HEIC photos, convert them or retake the photo."))

    size_mb = len(data) / 1024 / 1024
    if size_mb > policy.files.max_mb:
        return _fail(QualityIssue(
            code="FILE_TOO_LARGE", severity="error",
            message=f"{name} - the file is {size_mb:.1f} MB, over the {policy.files.max_mb} MB limit.",
            fix_hint="Try a lower-quality scan, or upload a PDF.",
            metric={"size_mb": round(size_mb, 1), "max": policy.files.max_mb}))

    issues: list[QualityIssue] = []
    if ext == "pdf":
        cap = policy.files.max_pdf_pages_by_doc.get(spec.id, policy.files.max_pdf_pages)
        # Salary slips are processed page by page, so render every page; others only need a sample.
        render_limit = cap if spec.id == "salary_slip" else 3
        res = open_pdf(data, spec, cap, policy.pdf.render_dpi, render_limit)
        if res.issues:
            return QualityResult(passed=False, issues=res.issues), []
        pages, photo_checks = res.pages, not res.has_text_layer
    else:
        if len(data) < policy.files.min_image_kb * 1024:
            return _fail(QualityIssue(
                code="FILE_TOO_SMALL", severity="error",
                message=f"{name} - the file is very small and is likely a thumbnail.",
                fix_hint="Upload the original photo or scan, not a preview.",
                metric={"size_kb": round(len(data) / 1024), "min": policy.files.min_image_kb}))
        try:
            img = load_oriented(Image.open(io.BytesIO(data)))
            img.load()
        except Exception:
            return _fail(QualityIssue(
                code="UNREADABLE", severity="error",
                message=f"{name} - we couldn't open this image.",
                fix_hint="Please upload the file again, or retake the photo."))
        pages, photo_checks = [img], True

    for page in pages[:1] if spec.kind == "id" else (pages if spec.id == "salary_slip" else pages[:3]):
        issues += check_image(page, spec, policy.image, photo_checks=photo_checks)

    # One entry per issue code, even if several pages triggered it.
    seen, unique = set(), []
    for i in issues:
        if i.code not in seen:
            seen.add(i.code)
            unique.append(i)
    return QualityResult(passed=not any(i.severity == "error" for i in unique), issues=unique), pages
