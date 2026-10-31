"""LangChain-based VLM client: image(s) + prompts -> raw text, with retry and fallback."""
import base64
import io
import time

from langchain_core.messages import HumanMessage, SystemMessage
from PIL import Image

from core.config.settings import get_settings
from core.vlm.registry import build_chat_model, get_option, is_cooling, mark_bad


class VLMError(Exception):
    pass


def encode_image(img: Image.Image, max_side: int = 1600, quality: int = 85) -> str:
    img = img.convert("RGB")
    img.thumbnail((max_side, max_side))
    buf = io.BytesIO()
    img.save(buf, "JPEG", quality=quality)
    return "data:image/jpeg;base64," + base64.b64encode(buf.getvalue()).decode()


def message_text(content) -> str:
    """Providers return a str or a list of blocks (text/thinking); keep only the text."""
    if isinstance(content, str):
        return content
    return "".join(b.get("text", "") for b in content
                   if isinstance(b, dict) and b.get("type") == "text")


class LangChainVLM:
    def __init__(self, model_key: str | None = None, fallback_key: str | None = None):
        s = get_settings()
        self.model_key = model_key or s.default_model
        self.fallback_key = fallback_key if fallback_key is not None else s.fallback_model
        for k in filter(None, (self.model_key, self.fallback_key)):
            if not get_option(k).vision:
                raise VLMError(f"{k} cannot read images; pick a vision model.")

    def _call(self, key: str, system: str, user: str, images: list[Image.Image], alt_key: bool = False) -> str:
        content = [{"type": "image_url", "image_url": {"url": encode_image(i)}} for i in images]
        content.append({"type": "text", "text": user})
        llm = build_chat_model(key, alt_key=alt_key, timeout=20)
        resp = llm.invoke([SystemMessage(content=system), HumanMessage(content=content)])
        return message_text(resp.content)

    def complete(self, system: str, user: str, images: list[Image.Image]) -> str:
        """Primary model, then the fallback (an overloaded model is usually still overloaded), then the primary once more."""
        errors = []
        models = [m for m in (self.model_key, self.fallback_key) if m]
        has_key2 = bool(get_settings().gemini_api_key2)
        order = [(m, False) for m in models] + ([(m, True) for m in models] if has_key2 else [(self.model_key, False)])
        usable = [o for o in order if not is_cooling(*o)] or order       # never end up with nothing to try
        for key, alt in usable:
            try:
                return self._call(key, system, user, images, alt)
            except Exception as e:  # network, quota or model errors
                mark_bad(key, alt)
                errors.append(f"{key}{' (key 2)' if alt else ''}: {str(e)[:80]}")
        raise VLMError("; ".join(errors))
