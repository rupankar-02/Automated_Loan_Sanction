"""Catalog of selectable models and a LangChain chat-model factory.

Availability was probed with real image calls (scripts/probe_calls.py).
"""
from dataclasses import dataclass

from langchain_core.language_models.chat_models import BaseChatModel

from core.config.settings import get_settings


@dataclass(frozen=True)
class ModelOption:
    key: str            # "<provider>:<model>", what the UI / env stores
    provider: str       # gemini | hf | sarvam
    model: str
    label: str
    vision: bool        # accepts images -> usable for document extraction
    note: str


def _catalog() -> list[ModelOption]:
    s = get_settings()
    opts = [
        ModelOption("gemini:gemini-3-flash-preview", "gemini", "gemini-3-flash-preview",
                    "Gemini 3 Flash (preview)", True, "Fast (about 4s); recommended default"),
        ModelOption("gemini:gemini-3.1-flash-lite", "gemini", "gemini-3.1-flash-lite",
                    "Gemini 3.1 Flash-Lite", True, "Often overloaded (503) at busy times"),
        ModelOption("gemini:gemini-3.5-flash", "gemini", "gemini-3.5-flash",
                    "Gemini 3.5 Flash", True, "Accurate; run with minimal thinking for speed"),
        ModelOption("gemini:gemma-4-31b-it", "gemini", "gemma-4-31b-it",
                    "Gemma 4 31B (via Gemini API)", True, "Open model, slow (~30s)"),
        ModelOption("sarvam:sarvam-105b", "sarvam", "sarvam-105b",
                    "Sarvam 105B", False, "Text only: cannot read images"),
    ]
    if s.hf_model_id:
        opts.append(ModelOption(f"hf:{s.hf_model_id}", "hf", s.hf_model_id,
                                f"{s.hf_model_id} (Hugging Face)", True,
                                "Needs HF credits (account currently out of credits)"))
    return opts


def list_models(vision_only: bool = False) -> list[ModelOption]:
    return [m for m in _catalog() if m.vision or not vision_only]


def get_option(key: str) -> ModelOption:
    for m in _catalog():
        if m.key == key:
            return m
    raise ValueError(f"Unknown model '{key}'. Available: {[m.key for m in _catalog()]}")


def build_chat_model(key: str, *, max_tokens: int = 1500, timeout: int = 90, alt_key: bool = False) -> BaseChatModel:
    opt, s = get_option(key), get_settings()
    if opt.provider == "gemini":
        from langchain_google_genai import ChatGoogleGenerativeAI
        extra = {"thinking_level": "minimal"} if opt.model == "gemini-3.5-flash" else {}   # 5s instead of 50s
        return ChatGoogleGenerativeAI(**extra, model=opt.model, google_api_key=(s.gemini_api_key2 if alt_key and s.gemini_api_key2 else s.gemini_api_key),
                                      temperature=0, max_tokens=max_tokens, timeout=timeout, max_retries=1)
    from langchain_openai import ChatOpenAI
    if opt.provider == "hf":
        return ChatOpenAI(model=opt.model, api_key=s.hf_token,
                          base_url="https://router.huggingface.co/v1",
                          temperature=0, max_tokens=max_tokens, timeout=timeout, max_retries=1)
    if opt.provider == "sarvam":
        return ChatOpenAI(model=opt.model, api_key=s.sarvam_api_key,
                          base_url="https://api.sarvam.ai/v1", temperature=0,
                          max_tokens=max_tokens, timeout=timeout, max_retries=1,
                          # sarvam-105b reasons by default and can take a minute; null switches that off (about 1s)
                          extra_body={"reasoning_effort": None},
                          default_headers={"api-subscription-key": s.sarvam_api_key})
    raise ValueError(f"Unsupported provider {opt.provider}")


# ---- cooldown: skip a model/key that just failed (429 quota, 503 overload, timeout) so users do not wait on it again
import time as _time

_COOLDOWN: dict[tuple[str, bool], float] = {}
COOLDOWN_SECONDS = 90


def mark_bad(key: str, alt: bool) -> None:
    _COOLDOWN[(key, alt)] = _time.monotonic() + COOLDOWN_SECONDS


def is_cooling(key: str, alt: bool) -> bool:
    return _COOLDOWN.get((key, alt), 0) > _time.monotonic()
