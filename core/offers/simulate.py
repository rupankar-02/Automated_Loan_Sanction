"""What-if: apply changes to the facts/request and re-run the engine. Used by sliders, gaps and grids."""
from core.offers.catalog import Catalog, get_catalog
from core.offers.engine import evaluate_all, evaluate_offer
from core.offers.models import Facts, LoanRequest, OfferEvaluation


def apply_changes(facts: Facts, req: LoanRequest, **changes) -> tuple[Facts, LoanRequest]:
    f, r = facts.model_copy(deep=True), req.model_copy(deep=True)
    if "amount" in changes:
        r.amount = changes["amount"]
    if "tenure_months" in changes:
        r.tenure_months = int(changes["tenure_months"])
    for key in ("existing_emi", "credit_score", "coapplicant_income"):
        if key in changes:
            setattr(f, key, changes[key])
    if "add_docs" in changes:
        f.documents_verified = sorted(set(f.documents_verified) | set(changes["add_docs"]))
    return f, r


def simulate(facts: Facts, req: LoanRequest, catalog: Catalog | None = None, **changes) -> list[OfferEvaluation]:
    f, r = apply_changes(facts, req, **changes)
    return evaluate_all(f, r, catalog or get_catalog())


def simulate_offer(offer_id: str, facts: Facts, req: LoanRequest, catalog: Catalog | None = None, **changes) -> OfferEvaluation:
    catalog = catalog or get_catalog()
    f, r = apply_changes(facts, req, **changes)
    return evaluate_offer(catalog.offer(offer_id), f, r, catalog)
