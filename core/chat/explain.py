"""Deterministic answers built from the same context JSON the model reads.

The app works with no LLM at all, and this is the fallback when the model fails verification.
"""
import re

from core.utils.money import inr

DISCLAIMER = "These offers are indicative and subject to lender verification and credit bureau checks. They are not a loan approval."
_OFFER_WORDS = {"quick_small": ["quick", "small"], "salary_linked": ["salary-linked", "salary linked", "advance"],
                "flexi_tenure": ["flexi"], "standard": ["standard"], "premium": ["premium"]}
_GLOSSARY_WORDS = {"foir": "FOIR", "emi": "EMI", "processing fee": "processing_fee", "prepayment": "prepayment_charge",
                   "total cost": "total_cost", "credit score": "credit_score", "indicative": "indicative"}
STATUS_TEXT = {"eligible": "You are eligible", "eligible_reduced": "You are eligible for a smaller amount",
               "not_eligible": "Not eligible right now", "needs_info": "We need a little more information"}


def find_offer(message: str, ctx: dict) -> dict | None:
    low = message.lower()
    for o in ctx["offers"]:
        words = _OFFER_WORDS.get(o["id"], []) + [o["name"].lower()]
        if any(w in low for w in words):
            return o
    return None


def find_offers(message: str, ctx: dict) -> list[dict]:
    low = message.lower()
    return [o for o in ctx["offers"] if any(w in low for w in _OFFER_WORDS.get(o["id"], []) + [o["name"].lower()])]


def _top(ctx: dict) -> dict | None:
    ranked = [o for o in ctx["offers"] if o.get("rank")]
    return ranked[0] if ranked else None


def _criterion_text(c: dict, ctx: dict) -> str:
    cid, req, act, gap = c["id"], c.get("required"), c.get("actual"), c.get("gap")
    if cid == "MIN_INCOME":
        return f"Minimum monthly income is {inr(req)}; yours is {inr(act)} ({inr(gap)} short)."
    if cid == "SCORE_MIN":
        if c["status"] == "unknown":
            return f"It needs a credit score of {req} or more, and we don't have yours yet."
        return f"Credit score needs {req} or more; you entered {act} ({gap} points short)."
    if cid == "AGE_MIN":
        return f"Minimum age is {req}; yours is {act}."
    if cid == "AGE_AT_MATURITY":
        return f"With this tenure your age at the end of the loan would be {act}, above the limit of {req}."
    if cid == "TENURE_RANGE":
        return f"Tenure must be {req} months; you asked for {act}."
    if cid == "AMOUNT_RANGE":
        lo, hi = str(req).split("-")
        return f"The loan amount must be between {inr(float(lo))} and {inr(float(hi))}; you asked for {inr(act)}."
    if cid == "FOIR":
        return f"With this loan your total monthly EMIs would be {inr(act)} against a limit of {inr(req)} ({inr(gap)} over)."
    if cid == "DOCS":
        return "Documents needed: " + (c.get("detail") or "").replace("missing: ", "") + "."
    return f"{c['label']}: required {req}, yours {act}."


def explain_why_not(o: dict, ctx: dict) -> str:
    if o["status"] == "eligible":
        return f"Good news: {o['name']} is available to you. {explain_offer(o, ctx)}"
    lines = [f"**{o['name']}**: {STATUS_TEXT[o['status']].lower()}."]
    lines += [_criterion_text(c, ctx) for c in o.get("criteria", [])]
    if o["status"] == "eligible_reduced" and o.get("evaluation", {}).get("max_eligible_amount"):
        lines.append(f"The most you can get on this offer is {inr(o['evaluation']['max_eligible_amount'])}.")
    sug = o.get("suggestions", [])
    if sug:
        lines.append("What could help: " + explain_suggestions(o, short=True))
    return " ".join(lines)


def explain_offer(o: dict, ctx: dict) -> str:
    t, ev = o["terms"], o.get("evaluation", {})
    base = (f"{o['name']} ({o['lender']}): amount {inr(t['amount']['min'])} to {inr(t['amount']['max'])}, "
            f"tenure {t['tenure_months']['min']} to {t['tenure_months']['max']} months, rate band "
            f"{t['rate_band_pct']['min']}% to {t['rate_band_pct']['max']}%, processing fee {t['processing_fee_pct']}%, "
            f"prepayment charge {t['prepayment_charge_pct']}%.")
    if ev.get("emi"):
        base += (f" For {inr(ev['evaluated_amount'])} your indicative EMI is {inr(ev['emi'])} at {ev['indicative_rate_pct']}%, "
                 f"with a total cost of {inr(ev['total_cost'])}.")
    return base


def explain_suggestions(o: dict, short: bool = False) -> str:
    sug = o.get("suggestions", [])
    if not sug:
        return "There is no simple change that opens this offer right now."
    parts = []
    for s in sug:
        p = s["change"][0].upper() + s["change"][1:] if not short else s["change"]
        p += f" (then: {STATUS_TEXT[s['resulting_status']].lower()})"
        if s.get("trade_off"):
            p += f"; trade-off: {s['trade_off']}"
        parts.append(p)
    return ("; ".join(parts) if short else " ".join(f"{i}. {p}." for i, p in enumerate(parts, 1)))


def list_offers(ctx: dict) -> str:
    lines = []
    for o in ctx["offers"]:
        ev = o.get("evaluation", {})
        if o["status"] == "eligible":
            lines.append(f"{o.get('rank')}. {o['name']}: eligible, EMI {inr(ev['emi'])}, total cost {inr(ev['total_cost'])}.")
        elif o["status"] == "eligible_reduced":
            lines.append(f"{o.get('rank')}. {o['name']}: eligible up to {inr(ev['max_eligible_amount'])}.")
        else:
            lines.append(f"- {o['name']}: {STATUS_TEXT[o['status']].lower()}.")
    return "Here is where you stand. " + " ".join(lines) + " " + DISCLAIMER


def compare(a: dict, b: dict) -> str:
    def line(o):
        ev = o.get("evaluation", {})
        return (f"{o['name']}: {STATUS_TEXT[o['status']].lower()}" +
                (f", total cost {inr(ev['total_cost'])} for {inr(ev['evaluated_amount'])}" if ev.get("total_cost") else "") + ".")
    return line(a) + " " + line(b)


def _parse_tenure(msg: str) -> int | None:
    m = re.search(r"(\d+)\s*(months?|mos?\b|years?|yrs?)", msg.lower())
    if not m:
        return None
    n = int(m.group(1))
    return n * 12 if m.group(2).startswith(("y",)) else n


def _parse_amount(msg: str) -> int | None:
    low = msg.lower().replace(",", "")
    m = re.search(r"(\d+(?:\.\d+)?)\s*(lakhs?|lacs?|crores?)", low)
    if m:
        return int(float(m.group(1)) * (1e5 if m.group(2).startswith(("lakh", "lac")) else 1e7))
    m = re.search(r"(?:₹|rs\.?\s*)\s*(\d{4,})|\b(\d{5,})\b", low)
    return int(next(g for g in m.groups() if g)) if m else None


def whatif_answer(msg: str, ctx: dict) -> str:
    o = find_offer(msg, ctx) or _top(ctx) or ctx["offers"][0]
    grid = o.get("what_if")
    t, a = _parse_tenure(msg), _parse_amount(msg)
    if grid and t is not None:
        row = next((r for r in grid["by_tenure"] if r["tenure_months"] == t), None)
        if row:
            return (f"{o['name']} at {t} months: {STATUS_TEXT[row['status']].lower()}"
                    + (f", EMI {inr(row['emi'])}, total interest {inr(row['interest'])}" if row.get("emi") else "")
                    + (f", up to {inr(row['max_amount'])}" if row.get("max_amount") else "") + ".")
    if grid and a is not None:
        row = next((r for r in grid["by_amount"] if r["amount"] == a), None)
        if row:
            return (f"{o['name']} for {inr(a)}: {STATUS_TEXT[row['status']].lower()}"
                    + (f", EMI {inr(row['emi'])}" if row.get("emi") else "") + ".")
    return "I don't have that exact figure. Try the sliders on the offers page to see it instantly."


def template_answer(message: str, ctx: dict, lang: str = "en") -> str:
    low = message.lower()
    if re.search(r"approv|guarantee|definitely|sure (?:to )?get|पक्का|गारंटी", low):
        return "I can't promise an approval. " + DISCLAIMER
    for word, key in _GLOSSARY_WORDS.items():
        if word in low and re.search(r"what is|what's|meaning|explain|mean|क्या है", low):
            return ctx["glossary"].get(key, "I don't have that information.")
    o = find_offer(message, ctx)
    named = find_offers(message, ctx)
    if re.search(r"why|not offered|not eligible|reject|क्यों", low):
        if o:
            return explain_why_not(o, ctx)
        bad = [x for x in ctx["offers"] if x["status"] in ("not_eligible", "needs_info", "eligible_reduced")]
        return " ".join(explain_why_not(x, ctx) for x in bad[:3]) or "All offers are available to you."
    asks_number = bool(_parse_tenure(message) or _parse_amount(message))
    if asks_number and re.search(r"what if|how about|what about|what would|instead|\bif i\b|extend|borrow|\bemi\b|month|tenure|lakh", low):
        return whatif_answer(message, ctx)
    if re.search(r"credit score|\bscore\b|\braise\b", low) and re.search(r"help|improve|raise|increase|better|lower|change", low):
        sug = [(x, s) for x in ctx["offers"] for s in x.get("suggestions", []) if s["lever"] == "improve_score"]
        if sug:
            x, s = sug[0]
            return (f"For {x['name']}: {s['change']} (then: {STATUS_TEXT[s['resulting_status']].lower()}); trade-off: {s['trade_off']}. "
                    + ctx["glossary"].get("credit_score", ""))
        return ctx["glossary"].get("credit_score", "") + " A higher score places you lower in an offer's rate band."
    if re.search(r"lower (?:the )?(?:rate|emi)|better rate|cheaper rate|reduce (?:the )?rate", low):
        top = o or _top(ctx) or ctx["offers"][0]
        return f"For {top['name']}: " + explain_suggestions(top)
    if re.search(r"improve|better|what can i do|how can i|how do i|increase my chance|qualify", low):
        target = o or next((x for x in ctx["offers"] if x["status"] != "eligible" and x.get("suggestions")), None) or _top(ctx) or ctx["offers"][0]
        return f"For {target['name']}: " + explain_suggestions(target)
    if len(named) >= 2 or re.search(r"cheap|compare|better deal|lowest|which (?:one )?is", low):
        pair = named[:2] if len(named) >= 2 else [x for x in ctx["offers"] if x.get("rank")][:2]
        if len(pair) == 2:
            return compare(pair[0], pair[1])
    if o:
        return explain_offer(o, ctx) + (" " + explain_why_not(o, ctx) if o["status"] != "eligible" else "")
    return list_offers(ctx)
