"""'What would it take' solver. Every suggestion is verified by re-running the engine, so the status we
promise is the status the engine gives."""
import math

from core.offers import finance
from core.offers.catalog import Catalog, Offer, indicative_rate
from core.offers.models import STATUS_ORDER, Facts, LoanRequest, OfferEvaluation, Suggestion
from core.offers.simulate import simulate_offer
from core.utils.money import inr

MAX_PER_OFFER = 4
LEVER_ORDER = ["reduce_amount", "increase_amount", "shorten_tenure", "extend_tenure", "upload_document",
               "reduce_existing_emi", "choose_other_offer", "add_coapplicant_income", "improve_score"]


def _better(new: str, old: str) -> bool:
    return STATUS_ORDER[new] > STATUS_ORDER[old]


def _interest_at(offer: Offer, facts: Facts, amount: float, months: int, catalog: Catalog) -> float:
    return finance.total_interest(amount, indicative_rate(offer, facts.credit_score, facts.has_form16, catalog), months)


def _max_tenure(offer: Offer, facts: Facts) -> int:
    """Longest tenure the offer allows for this applicant's age."""
    by_age = math.floor((offer.max_age_at_maturity - facts.age) * 12)
    return int(min(offer.tenure_months.max, by_age))


def suggest_for_offer(offer: Offer, ev: OfferEvaluation, facts: Facts, req: LoanRequest, catalog: Catalog,
                      all_evals: list[OfferEvaluation]) -> list[Suggestion]:
    out: list[Suggestion] = []
    failed = {c.id: c for c in ev.failed()}

    def verify(**ch) -> OfferEvaluation:
        return simulate_offer(offer.id, facts, req, catalog, **ch)

    def add(lever, change, res, trade_off=None, effort=1, **params):
        out.append(Suggestion(lever=lever, change=change, resulting_status=res.status, trade_off=trade_off,
                              effort=effort, params=params))

    # amount: too high for the EMI limit or the offer's maximum
    if ("FOIR" in failed or ("AMOUNT_RANGE" in failed and req.amount > offer.amount.max)) and ev.status != "needs_info":
        target = min(ev.max_eligible_amount or 0, offer.amount.max)
        target = max(math.floor(target / 1000) * 1000, 0) if target >= 1000 else target
        if target >= offer.amount.min:
            res = verify(amount=target)
            if _better(res.status, ev.status):
                add("reduce_amount", f"borrow {inr(target)} instead of {inr(req.amount)}", res,
                    "a smaller loan than requested", 1, amount=target)
    if "AMOUNT_RANGE" in failed and req.amount < offer.amount.min:
        res = verify(amount=offer.amount.min)
        if _better(res.status, ev.status):
            add("increase_amount", f"borrow at least {inr(offer.amount.min)}", res, "a larger loan than requested", 1,
                amount=offer.amount.min)

    # tenure: outside the offer's range or past the age limit
    if "TENURE_RANGE" in failed or "AGE_AT_MATURITY" in failed:
        t = req.tenure_months
        if t > offer.tenure_months.max or "AGE_AT_MATURITY" in failed:
            new_t = _max_tenure(offer, facts)
            lever = "shorten_tenure"
        else:
            new_t, lever = int(offer.tenure_months.min), "extend_tenure"
        if offer.tenure_months.min <= new_t <= offer.tenure_months.max and new_t != t:
            res = verify(tenure_months=new_t)
            if _better(res.status, ev.status):
                add(lever, f"choose {new_t} months instead of {t}", res, None, 1, tenure_months=new_t)

    # EMI too high: a longer tenure lowers it but costs more interest
    if "FOIR" in failed and ev.status != "needs_info":
        hi = _max_tenure(offer, facts)
        for t in range(req.tenure_months + 1, hi + 1):
            res = verify(tenure_months=t)
            if res.status == "eligible":
                extra = _interest_at(offer, facts, req.amount, t, catalog) - _interest_at(offer, facts, req.amount, req.tenure_months, catalog)
                add("extend_tenure", f"choose {t} months instead of {req.tenure_months}", res,
                    f"total interest rises by about {inr(extra)}", 1, tenure_months=t)
                break
        need = failed["FOIR"].gap or 0
        cut = math.ceil(need / 100) * 100
        if 0 < cut <= facts.existing_emi:
            res = verify(existing_emi=facts.existing_emi - cut)
            if res.status == "eligible":
                add("reduce_existing_emi", f"clear at least {inr(cut)} of your monthly EMIs", res, None, 2, clear=cut)

    # documents
    if "DOCS" in failed:
        missing = [d for d in offer.required_docs if d not in facts.documents_verified]
        res = verify(add_docs=missing)
        if _better(res.status, ev.status):
            add("upload_document", "upload " + " and ".join(m.replace("form16", "Form 16 or ITR") for m in missing), res,
                None, 1, docs=missing)

    # income: a co-applicant (what-if number only)
    if "MIN_INCOME" in failed:
        extra = failed["MIN_INCOME"].gap or 0
        extra = math.ceil(extra / 100) * 100
        for _ in range(60):                     # widen until the engine agrees (FOIR may need more)
            res = verify(coapplicant_income=extra)
            if "MIN_INCOME" not in {c.id for c in res.failed()} and "FOIR" not in {c.id for c in res.failed()}:
                break
            extra += 500
        if _better(res.status, ev.status):
            add("add_coapplicant_income", f"co-applicant income of at least {inr(extra)} per month", res,
                "a co-applicant would share responsibility for the loan", 3, coapplicant_income=extra)

    # credit score
    if "SCORE_MIN" in failed:
        need = offer.min_credit_score
        res = verify(credit_score=need)
        if _better(res.status, ev.status):
            add("improve_score", f"raise your credit score to at least {need} (it is {facts.credit_score})", res,
                "this takes time, and no outcome is guaranteed", 3, credit_score=need)

    # cheaper rate through optional documents, for offers the user can already get
    if ev.status in ("eligible", "eligible_reduced") and not facts.has_form16 and catalog.adjustments.get("form16_provided"):
        res = verify(add_docs=["form16"])
        if res.indicative_rate_pct is not None and ev.indicative_rate_pct is not None and res.indicative_rate_pct < ev.indicative_rate_pct:
            add("upload_document", f"upload Form 16 or ITR to lower the indicative rate from {ev.indicative_rate_pct}% to {res.indicative_rate_pct}%",
                res, None, 1, docs=["form16"])

    # switch to the best other option
    others = sorted((e for e in all_evals if e.offer_id != offer.id and e.status in ("eligible", "eligible_reduced")),
                    key=lambda e: e.rank or 99)
    if others and ev.status not in ("eligible",):
        best = others[0]
        o2 = catalog.offer(best.offer_id)
        band = o2.rate_band_pct
        add("choose_other_offer", f"{o2.name}", best, f"rate band {band.min}% to {band.max}%", 2, offer_id=best.offer_id)

    out.sort(key=lambda s: (s.effort, LEVER_ORDER.index(s.lever) if s.lever in LEVER_ORDER else 99))
    seen, final = set(), []
    for s in out:
        k = (s.lever, s.change)
        if k not in seen:
            seen.add(k)
            final.append(s)
    return final[:MAX_PER_OFFER]


def suggest_all(evals: list[OfferEvaluation], facts: Facts, req: LoanRequest, catalog: Catalog) -> dict[str, list[Suggestion]]:
    return {e.offer_id: suggest_for_offer(catalog.offer(e.offer_id), e, facts, req, catalog, evals) for e in evals}
