"""Chat model interface, through LangChain.

English: Gemini (both keys, then the fallback Gemini model), and if Gemini does not work at all, Sarvam 105B.
Hindi:   Sarvam 105B first, then Gemini.
"""
from typing import Protocol

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage

from core.config.settings import get_settings
from core.vlm.client import message_text
from core.vlm.registry import build_chat_model, get_option, is_cooling, mark_bad

HINDI_MODEL = "sarvam:sarvam-105b"
SARVAM_BACKUP = "sarvam:sarvam-105b"


class ChatLLM(Protocol):
    def complete(self, system: str, history: list[tuple[str, str]], user: str) -> str: ...


class LangChainChat:
    def __init__(self, model_key: str, max_tokens: int = 600, timeout: int = 25, fallback_keys: list[str] | None = None):
        self.model_key, self.max_tokens, self.timeout = model_key, max_tokens, timeout
        self.fallback_keys = [k for k in (fallback_keys or []) if k and k != model_key]
        self.last_model: str | None = None            # which model actually answered (shown for transparency)

    def _attempts(self) -> list[tuple[str, bool]]:
        out: list[tuple[str, bool]] = []
        has_key2 = bool(get_settings().gemini_api_key2)
        for m in [self.model_key] + self.fallback_keys:
            out.append((m, False))
            if has_key2 and get_option(m).provider == "gemini":
                out.append((m, True))
        return out

    def complete(self, system: str, history: list[tuple[str, str]], user: str) -> str:
        msgs = [SystemMessage(content=system)]
        for role, text in history:
            msgs.append(HumanMessage(content=text) if role == "user" else AIMessage(content=text))
        msgs.append(HumanMessage(content=user))
        attempts = self._attempts()
        last: Exception | None = None
        for key, alt in ([a for a in attempts if not is_cooling(*a)] or attempts):
            try:
                out = build_chat_model(key, max_tokens=self.max_tokens, timeout=self.timeout, alt_key=alt).invoke(msgs)
                text = message_text(out.content).strip()
                if not text:
                    raise ValueError("empty reply")
                self.last_model = key
                return text
            except Exception as e:                  # overloaded, out of quota or timed out: try the next one
                mark_bad(key, alt)
                last = e
        raise last  # type: ignore[misc]


class FakeLLM:
    """Scripted replies for tests: a list is consumed in order (the last one repeats); a callable gets (system, history, user)."""

    def __init__(self, replies):
        self.replies, self.calls = replies, []

    def complete(self, system, history, user):
        self.calls.append({"system": system, "history": list(history), "user": user})
        if callable(self.replies):
            return self.replies(system, history, user)
        r = self.replies if isinstance(self.replies, list) else [self.replies]
        return r[min(len(self.calls) - 1, len(r) - 1)]


def get_chat_llm(lang: str = "en", english_model: str | None = None) -> ChatLLM:
    s = get_settings()
    primary = english_model or s.default_model
    if lang == "hi":
        return LangChainChat(HINDI_MODEL, fallback_keys=[primary, s.fallback_model])
    return LangChainChat(primary, fallback_keys=[s.fallback_model, SARVAM_BACKUP])
