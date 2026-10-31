"""Field extraction with Sarvam Vision (Document AI `extract`).

Role split: Sarvam extracts the values; Gemini (core/vlm/client.py) does classification
and other reasoning tasks; rule validators decide what is acceptable.
"""
import io
import json
import time

from PIL import Image
from sarvamai import SarvamAI

from core.config.loader import get_policy
from core.config.settings import get_settings
from core.utils.ratelimit import SlidingWindowLimiter, call_with_backoff

TERMINAL = {"completed", "partially_completed", "failed", "rejected"}
OK = {"completed", "partially_completed"}


class SarvamExtractError(Exception):
    pass


_limiter: SlidingWindowLimiter | None = None


def get_limiter() -> SlidingWindowLimiter:
    """One limiter shared by all threads: Sarvam allows N requests per minute per key."""
    global _limiter
    if _limiter is None:
        _limiter = SlidingWindowLimiter(get_policy().limits.sarvam_requests_per_minute, 60.0)
    return _limiter


def build_schema(fields: list[dict]) -> dict:
    """fields: [{"key", "description", "type"?}] -> Sarvam JSON schema (every field needs a description)."""
    return {
        "type": "object",
        "properties": {
            f["key"]: {"type": f.get("type", "string"), "description": f["description"]}
            for f in fields
        },
    }


def _to_jpeg_bytes(img: Image.Image, max_side: int = 2000) -> bytes:
    img = img.convert("RGB")
    img.thumbnail((max_side, max_side))
    buf = io.BytesIO()
    img.save(buf, "JPEG", quality=90)
    return buf.getvalue()


class SarvamVisionExtractor:
    def __init__(self, poll_seconds: float = 3.0, timeout_seconds: int = 120):
        key = get_settings().sarvam_api_key
        if not key:
            raise SarvamExtractError("SARVAM_API_KEY is not set.")
        self.client = SarvamAI(api_subscription_key=key)
        self.poll_seconds = poll_seconds
        self.timeout_seconds = timeout_seconds

    def extract(self, fields: list[dict], *, pdf_bytes: bytes | None = None,
                images: list[Image.Image] | None = None, on_wait=None) -> dict:
        """Return {key: value-or-None} for the requested fields.

        on_wait(seconds) is called while waiting on the rate limit or backing off.
        """
        if pdf_bytes is not None:
            payload, name, mime = pdf_bytes, "document.pdf", "application/pdf"
        elif images:
            if len(images) > 1:
                raise SarvamExtractError("Pass one image, or a PDF for multiple pages.")
            payload, name, mime = _to_jpeg_bytes(images[0]), "document.jpg", "image/jpeg"
        else:
            raise SarvamExtractError("No document supplied.")

        schema = json.dumps(build_schema(fields))
        retries = get_policy().limits.sarvam_retries
        get_limiter().acquire(on_wait)
        job = call_with_backoff(
            lambda: self.client.doc_ai.extract(file=[(name, io.BytesIO(payload), mime)],
                                               schema=schema, output_format="json"),
            retries=retries, on_wait=on_wait)

        deadline = time.time() + self.timeout_seconds
        while True:
            st = call_with_backoff(lambda: self.client.doc_ai.get_status(job_id=job.job_id),
                                   retries=retries, on_wait=on_wait)
            status = str(st.status).lower()
            if status in TERMINAL:
                break
            if time.time() > deadline:
                raise SarvamExtractError("Sarvam extraction timed out.")
            time.sleep(self.poll_seconds)
        if status not in OK:
            raise SarvamExtractError(f"Sarvam job {status}.")

        result = call_with_backoff(lambda: self.client.doc_ai.get_results(job_id=job.job_id).result,
                                   retries=retries, on_wait=on_wait)
        if isinstance(result, str):
            result = json.loads(result)
        return {f["key"]: _clean(result.get(f["key"])) for f in fields}


def _clean(v):
    if v is None:
        return None
    if isinstance(v, str) and v.strip().lower() in {"", "n/a", "na", "-", "null", "none"}:
        return None
    return v
