"""Deterministic eligibility engine. Rules decide; nothing here calls a model."""
import math

from core.offers import finance
from core.offers.catalog import Catalog, Offer, get_catalog, indicative_rate
from core.offers.criteria import PROFILE_IDS, EvalCtx, evaluate_criteria
from core.offers.models import Facts, LoanRequest, OfferEvaluation
from core.utils.money import inr


def make_ctx(offer: Offer, facts: Facts, req: LoanRequest, catalog: Catalog) -> EvalCtx:
    rate = indicative_rate(offer, facts.credit_score, facts.has_form16, catalog)
    tenure_eff = int(min(max(req.tenure_months, offer.tenure_months.min), offer.tenure_months.max))
    capacity = max(0.0, offer.foir_cap * facts.income - facts.existing_emi)
    return EvalCtx(offer=offer, facts=facts, req=req, rate=rate, tenure_eff=tenure_eff, capacity=capacity,
                   cap_principal=finance.max_principal(capacity, rate, tenure_eff),
                   emi_req=finance.emi(req.amount, rate, tenure_eff))


def _fill_money(ev: OfferEvaluation, amount: float, c: EvalCtx, for_what: str) -> None:
    o = c.offer
    e = finance.emi(amount, c.rate, c.tenure_eff)
    interest = e * c.tenure_eff - amount
    fee = finance.processing_fee(amount, o.processing_fee_pct)
    ev.evaluated_amount, ev.evaluated_for = int(round(amount)), for_what
    ev.emi, ev.total_interest = int(round(e)), int(round(interest))
    ev.processing_fee, ev.total_cost = int(round(fee)), int(round(interest + fee))


def evaluate_offer(offer: Offer, facts: Facts, req: LoanRequest, catalog: Catalog | None = None) -> OfferEvaluation:
    catalog = catalog or get_catalog()
    c = make_ctx(offer, facts, req, catalog)
    crit = evaluate_criteria(c)
    profile = [x for x in crit if x.id in PROFILE_IDS]
    ev = OfferEvaluation(offer_id=offer.id, status="not_eligible", criteria=crit)

    if any(x.status == "fail" for x in profile):
        return ev
    max_cap = min(offer.amount.max, c.cap_principal)
    ev.indicative_rate_pct = c.rate

    if any(x.status == "unknown" for x in profile):
        ev.status = "needs_info"
        if offer.amount.min <= req.amount <= offer.amount.max:
            _fill_money(ev, req.amount, c, "requested")
        if max_cap >= offer.amount.min:
            ev.max_eligible_amount = math.floor(max_cap)
        return ev

    if req.amount < offer.amount.min or c.cap_principal < offer.amount.min:
        ev.indicative_rate_pct = None          # no workable amount, so no rate is shown
        return ev

    ev.max_eligible_amount = math.floor(max_cap)
    if req.amount <= max_cap + 1e-6:
        ev.status = "eligible"
        _fill_money(ev, req.amount, c, "requested")
    else:
        ev.status = "eligible_reduced"
        _fill_money(ev, ev.max_eligible_amount, c, "max_eligible")
    return ev


def evaluate_all(facts: Facts, req: LoanRequest, catalog: Catalog | None = None) -> list[OfferEvaluation]:
    catalog = catalog or get_catalog()
    evs = [evaluate_offer(o, facts, req, catalog) for o in catalog.offers]
    rank_offers(evs, req)
    return evs


def rank_offers(evs: list[OfferEvaluation], req: LoanRequest) -> None:
    """Eligible first by lowest total cost (ties: larger eligible amount), then reduced offers by amount."""
    for e in evs:
        e.rank, e.rank_reason = None, None
    full = sorted([e for e in evs if e.status == "eligible"], key=lambda e: (e.total_cost, -(e.max_eligible_amount or 0)))
    part = sorted([e for e in evs if e.status == "eligible_reduced"], key=lambda e: -(e.max_eligible_amount or 0))
    for i, e in enumerate(full, 1):
        e.rank = i
        e.rank_reason = (f"lowest total cost for {inr(e.evaluated_amount)}" if i == 1
                         else f"total cost {inr(e.total_cost)} for {inr(e.evaluated_amount)}")
    for j, e in enumerate(part, len(full) + 1):
        e.rank = j
        e.rank_reason = f"closest to your request: up to {inr(e.max_eligible_amount)}"
