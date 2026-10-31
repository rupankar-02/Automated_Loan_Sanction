"""Pre-model checks: language, length, injection, identifier requests, per-session limits."""
import re
from dataclasses import dataclass

MAX_CHARS = 500
MAX_USER_MESSAGES = 30

_INJECTION = [r"ignore (?:all |your |the |previous |these )*(?:rules|instructions|prompt)", r"disregard (?:all |your |the )*(?:rules|instructions)",
              r"(?:reveal|show|print|repeat) (?:your |the )*(?:system )?(?:prompt|instructions|rules)", r"you are now\b",
              r"pretend (?:to be|you)", r"act as (?:a |an )?(?:different|unrestricted)", r"jailbreak", r"developer mode",
              r"tell me (?:that )?i(?:'m| am) approved", r"say (?:that )?i(?:'m| am) approved", r"मंज़ूर बता", r"नियम भूल"]
_IDENTIFIERS = [r"\bpan\b.*\b(?:number|no)\b", r"\baadhaa?r\b.*\b(?:number|no)\b", r"\baccount (?:number|no)\b",
                r"(?:someone|somebody|another person|my (?:friend|neighbour|neighbor|colleague|boss)).*(?:loan|offer|salary|score)",
                r"\bother (?:customers?|applicants?|users?)\b"]

REFUSALS = {
    "injection": "I can only explain the offers shown for your application, and I can't change how they are decided or promise an approval. "
                 "These offers are indicative and subject to lender verification. Would you like to know why an offer is or isn't available to you?",
    "identifier": "I can't share or look up personal identifiers or anyone else's details. I can only explain the offers for your own application.",
    "too_long": "That message is a bit long for me. Could you ask it in a shorter way?",
    "session_limit": "We've reached the message limit for this session. You can still use the sliders and the offer details on this page.",
}


@dataclass
class GuardResult:
    ok: bool
    reason: str | None = None        # injection | identifier | too_long | session_limit | empty
    lang: str = "en"

    @property
    def refusal(self) -> str | None:
        return REFUSALS.get(self.reason or "")


def detect_language(text: str) -> str:
    letters = [c for c in text if c.isalpha()]
    if not letters:
        return "en"
    deva = sum(1 for c in letters if "ऀ" <= c <= "ॿ")
    return "hi" if deva / len(letters) > 0.3 else "en"


def check_message(text: str, user_message_count: int = 0) -> GuardResult:
    t = (text or "").strip()
    lang = detect_language(t)
    if not t:
        return GuardResult(False, "empty", lang)
    if len(t) > MAX_CHARS:
        return GuardResult(False, "too_long", lang)
    if user_message_count >= MAX_USER_MESSAGES:
        return GuardResult(False, "session_limit", lang)
    low = t.lower()
    if any(re.search(p, low) for p in _INJECTION):
        return GuardResult(False, "injection", lang)
    if any(re.search(p, low) for p in _IDENTIFIERS):
        return GuardResult(False, "identifier", lang)
    return GuardResult(True, None, lang)
