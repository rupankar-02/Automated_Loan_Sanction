"""Precomputed what-if grids, so the chatbot answers by reading a row instead of calculating."""
from core.offers.catalog import Catalog, Offer
from core.offers.models import Facts, LoanRequest
from core.offers.simulate import simulate_offer

# Failures a user cannot fix by changing the amount or tenure: a grid would only repeat "not eligible".
_HARD = {"EMPLOYMENT", "AGE_MIN", "MIN_INCOME"}


def _row(ev, **extra) -> dict:
    return {**extra, "status": ev.status, "max_amount": ev.max_eligible_amount, "emi": ev.emi,
            "interest": ev.total_interest}


def grid_for_offer(offer: Offer, facts: Facts, req: LoanRequest, catalog: Catalog, base_failed: set[str]) -> dict[str, list[dict]]:
    if base_failed & _HARD:
        return {}
    tenures = sorted({t for t in catalog.grids["tenure_months"] if offer.tenure_months.min <= t <= offer.tenure_months.max}
                     | {req.tenure_months} & set(range(int(offer.tenure_months.min), int(offer.tenure_months.max) + 1)))
    amounts = sorted({a for a in catalog.grids["amount_ladder"] if offer.amount.min <= a <= offer.amount.max}
                     | {int(offer.amount.min), int(offer.amount.max)} | ({int(req.amount)} if offer.amount.min <= req.amount <= offer.amount.max else set()))
    # keep the amount ladder compact
    if len(amounts) > 9:
        keep = {int(req.amount), int(offer.amount.min), int(offer.amount.max)}
        step = max(1, len(amounts) // 6)
        amounts = sorted(keep | set(amounts[::step]))
    by_t = [_row(simulate_offer(offer.id, facts, req, catalog, tenure_months=t), tenure_months=t) for t in tenures]
    by_a = [_row(simulate_offer(offer.id, facts, req, catalog, amount=a), amount=a) for a in amounts]
    return {"by_tenure": by_t, "by_amount": by_a}
