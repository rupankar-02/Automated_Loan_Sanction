"""Every number in a reply must appear in the context. Rules decide; the model only rephrases."""
import re

_DEVANAGARI = str.maketrans("०१२३४५६७८९", "0123456789")
_NUM = re.compile(r"(?P<cur>₹|rs\.?|inr)?\s*(?P<num>\d[\d,]*(?:\.\d+)?)\s*(?P<unit>%|lakhs?|lacs?|crores?|cr\b|लाख|करोड़)?", re.I)

# Phrases that promise an outcome. Offers are indicative, so these are never acceptable.
PROMISES = [r"\bguarantee[sd]?\b", r"\byou (?:will|'ll) (?:definitely |surely )?(?:be )?(?:get|approved|receive)",
            r"\byou(?:'re| are) (?:already )?approved\b", r"\bdefinitely (?:get|qualify|approved)", r"\b100% (?:approval|sure)",
            r"\bno (?:chance|risk) of rejection", "गारंटी", "मंज़ूर हो जाएगा", "पक्का मिलेगा"]
SMALL_INTS = set(range(0, 11))          # "2 options", "step 3": harmless counting words
_MULT = {"lakh": 1e5, "lakhs": 1e5, "lac": 1e5, "lacs": 1e5, "लाख": 1e5, "crore": 1e7, "crores": 1e7, "cr": 1e7, "करोड़": 1e7}


def _norm(text: str) -> str:
    return text.translate(_DEVANAGARI)


def extract_numbers(text: str) -> list[tuple[float, str, bool]]:
    """(value in rupees/plain units, raw token, has_unit_or_currency). Lakh/crore are expanded exactly."""
    out = []
    for m in _NUM.finditer(_norm(text)):
        raw = m.group("num").rstrip(",")
        try:
            v = float(raw.replace(",", ""))
        except ValueError:
            continue
        unit = (m.group("unit") or "").lower()
        v *= _MULT.get(unit, 1)
        out.append((round(v, 4), m.group(0).strip(), bool(unit or m.group("cur"))))
    return out


def allowed_numbers(ctx_json: str) -> set[float]:
    """Every number in the context (including inside strings), plus harmless equivalents."""
    base = {v for v, _, _ in extract_numbers(re.sub(r'"run_id":"[^"]*"', '', ctx_json))}   # ids are not figures
    allowed = set(base)
    for v in base:
        if 0 < v < 1:                                   # 0.55 -> "55%"
            allowed.add(round(v * 100, 4))
        if v >= 12 and v == int(v) and v % 12 == 0 and v <= 120:   # 36 months -> "3 years"
            allowed.add(v / 12)
    return allowed


def unsupported_numbers(reply: str, ctx_json: str) -> list[str]:
    allowed = allowed_numbers(ctx_json)
    bad = []
    for v, raw, has_unit in extract_numbers(reply):
        if v in allowed:
            continue
        if v == int(v) and int(v) in SMALL_INTS and not has_unit:
            continue
        bad.append(raw)
    return bad


def promise_phrases(reply: str) -> list[str]:
    return [p for p in PROMISES if re.search(p, reply, re.I)]


def verify_reply(reply: str, ctx_json: str) -> tuple[bool, list[str]]:
    problems = [f"number not in context: {n}" for n in unsupported_numbers(reply, ctx_json)]
    problems += [f"promise phrase: {p}" for p in promise_phrases(reply)]
    return (not problems), problems
