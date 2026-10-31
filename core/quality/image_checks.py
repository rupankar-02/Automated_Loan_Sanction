"""Local image-level quality checks. No network, no API cost."""
import cv2
import numpy as np
from PIL import Image, ImageOps

from core.config.loader import ImagePolicy
from core.models import DocSpec, QualityIssue


def to_gray(img: Image.Image) -> np.ndarray:
    return cv2.cvtColor(np.array(img.convert("RGB")), cv2.COLOR_RGB2GRAY)


def blur_score(img: Image.Image, width: int = 1000, top_n: int = 500) -> float:
    """Sharpness = mean of the strongest Laplacian responses on a width-normalised grayscale image.

    Unlike the variance of the Laplacian, this does not drop on pages with little ink: a sparse
    but sharp page still has strong stroke edges, a blurred one does not.
    """
    g = to_gray(img)
    h, w = g.shape
    g = cv2.resize(g, (width, max(1, int(h * width / w))), interpolation=cv2.INTER_AREA)
    lap = np.abs(cv2.Laplacian(g, cv2.CV_64F)).ravel()
    n = min(top_n, lap.size)
    return float(np.partition(lap, -n)[-n:].mean())


def mean_brightness(img: Image.Image) -> float:
    return float(to_gray(img).mean())


def darkest_pct(img: Image.Image, pct: float = 0.05) -> float:
    """Gray level of the darkest `pct`% of pixels. Real documents have ink, so this stays low."""
    return float(np.percentile(to_gray(img), pct))


def glare_pct(img: Image.Image) -> float:
    """% of pixels that are blown out. Only meaningful for photos of non-white documents."""
    g = to_gray(img)
    return float((g >= 250).mean() * 100)


def edge_touch_sides(img: Image.Image, margin_px: int) -> int:
    """How many of the 4 image borders have content (edges) running into them."""
    g = cv2.GaussianBlur(to_gray(img), (5, 5), 0)
    edges = cv2.Canny(g, 60, 150)
    h, w = edges.shape
    m = max(margin_px, int(min(h, w) * 0.012))
    strips = [edges[:m, :], edges[h - m:, :], edges[:, :m], edges[:, w - m:]]
    return sum(1 for s in strips if s.size and (s > 0).mean() > 0.005)


def load_oriented(img: Image.Image) -> Image.Image:
    return ImageOps.exif_transpose(img)


def check_image(img: Image.Image, spec: DocSpec, policy: ImagePolicy,
                *, photo_checks: bool = True) -> list[QualityIssue]:
    """photo_checks=False for digital PDF pages (sharp by construction)."""
    issues: list[QualityIssue] = []
    name = spec.display_name
    w, h = img.size

    if spec.kind == "id":
        need, have = policy.min_long_side_id, max(w, h)
    else:
        need, have = policy.min_short_side_a4, min(w, h)
    if have < need:
        issues.append(QualityIssue(
            code="LOW_RES", severity="error",
            message=f"{name} - image resolution is too low.",
            fix_hint="Move closer so the document fills the frame, or use your camera's full resolution.",
            metric={"pixels": have, "required": need}))

    if not photo_checks:
        return issues

    blur_min = policy.blur_min_id if spec.kind == "id" else policy.blur_min_a4
    score = blur_score(img)
    if score < blur_min:
        issues.append(QualityIssue(
            code="BLURRY", severity="error",
            message=f"{name} - the photo is blurry.",
            fix_hint="Place the document on a flat surface in daylight, hold your phone steady, tap to focus and retake.",
            metric={"blur_score": round(score), "required": round(blur_min)}))

    mean = mean_brightness(img)
    if mean < policy.dark_mean_below:
        issues.append(QualityIssue(
            code="TOO_DARK", severity="error",
            message=f"{name} - the photo is too dark.",
            fix_hint="Use even lighting, such as daylight or a bright room, and avoid shadows.",
            metric={"brightness": round(mean), "min": policy.dark_mean_below}))
    elif mean > policy.bright_mean_above and darkest_pct(img) > 150:   # white pages are bright by design; washed-out photos have no ink
        issues.append(QualityIssue(
            code="TOO_BRIGHT", severity="error",
            message=f"{name} - the photo is washed out.",
            fix_hint="Avoid flash and direct light on the document.",
            metric={"brightness": round(mean), "max": policy.bright_mean_above}))
    elif mean < 200:  # white pages have a bright background by design; skip glare for them
        pct = glare_pct(img)
        if pct > policy.glare_pixel_pct:
            issues.append(QualityIssue(
                code="GLARE", severity="warning",
                message=f"{name} - there is glare on the document.",
                fix_hint="Tilt the document slightly to avoid reflections.",
                metric={"glare_pct": round(pct, 1), "max": policy.glare_pixel_pct}))

    sides = edge_touch_sides(img, policy.border_margin_px)
    if sides >= 2:
        issues.append(QualityIssue(
            code="CROPPED", severity="warning",
            message=f"{name} - part of the document may be cut off.",
            fix_hint="Make sure all four corners of the document are visible in the photo.",
            metric={"sides_touching_border": sides}))
    return issues
