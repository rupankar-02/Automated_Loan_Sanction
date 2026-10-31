"""build_context(run): the one JSON the model sees. A pure function of the run.

Only derived, non-identifying facts go in: a first name at most. No PAN, Aadhaar, account number,
surname, employer or document text. Every difference and total is precomputed.
"""
import hashlib
import json

from core.offers.catalog import Catalog, get_catalog, get_chat_static
from core.offers.models import OfferRun

_ALL_OPTIONAL_DOCS = ["form16"]


def _clean(x):
    """Drop None / empty containers; ints for whole floats; 2-decimal floats."""
    if isinstance(x, dict):
        out = {k: _clean(v) for k, v in x.items()}
        return {k: v for k, v in out.items() if v is not None and v != {} and v != []}
    if isinstance(x, list):
        return [_clean(v) for v in x]
    if isinstance(x, float):
        return int(x) if x == int(x) else round(x, 2)
    return x


def _terms(o) -> dict:
    return {"amount": o.amount.model_dump(), "tenure_months": o.tenure_months.model_dump(),
            "rate_band_pct": o.rate_band_pct.model_dump(), "processing_fee_pct": o.processing_fee_pct,
            "prepayment_charge_pct": o.prepayment_charge_pct, "foir_cap": o.foir_cap,
            "min_net_income": o.min_net_income, "min_age": o.min_age, "max_age_at_maturity": o.max_age_at_maturity,
            "min_credit_score": o.min_credit_score, "required_docs": o.required_docs}


def _criterion(c) -> dict:
    return {"id": c.id, "label": c.label, "status": c.status, "required": c.required, "actual": c.actual,
            "gap": c.gap, "user_controllable": c.user_controllable, "detail": c.detail}


def build_context(run: OfferRun, catalog: Catalog | None = None) -> dict:
    catalog = catalog or get_catalog()
    static = get_chat_static()
    f, r = run.facts, run.request
    user = {
        "first_name": f.first_name, "age": f.age, "employment": f.employment,
        "net_monthly_income": f.net_monthly_income,
        "income_variation_warning": True if f.income_variation_warning else None,
        "existing_monthly_emi": f.existing_emi,
        "credit_score": f.credit_score if f.credit_score is not None else "not provided",
        "documents_verified": f.documents_verified,
        "optional_documents_not_provided": [d for d in _ALL_OPTIONAL_DOCS if d not in f.documents_verified],
        "request": {"amount": r.amount, "tenure_months": r.tenure_months},
    }
    evs = sorted(run.evaluations, key=lambda e: (e.rank is None, e.rank or 0))
    offers = []
    for e in evs:
        o = catalog.offer(e.offer_id)
        entry = {"id": o.id, "name": o.name, "lender": o.lender, "status": e.status, "rank": e.rank,
                 "rank_reason": e.rank_reason, "terms": _terms(o),
                 "evaluation": {"max_eligible_amount": e.max_eligible_amount, "indicative_rate_pct": e.indicative_rate_pct,
                                "evaluated_amount": e.evaluated_amount, "evaluated_for": e.evaluated_for, "emi": e.emi,
                                "total_interest": e.total_interest, "processing_fee": e.processing_fee,
                                "total_cost": e.total_cost}}
        if e.status != "eligible":                      # full reasons only where something needs explaining
            entry["criteria"] = [_criterion(c) for c in e.criteria if c.status != "pass"]
            entry["criteria_passed"] = [c.id for c in e.criteria if c.status == "pass"]
        entry["suggestions"] = [{"lever": s.lever, "change": s.change, "resulting_status": s.resulting_status,
                                 "trade_off": s.trade_off} for s in run.suggestions.get(e.offer_id, [])]
        grid = run.scenarios.get(e.offer_id)
        if grid:
            entry["what_if"] = {"by_tenure": grid["by_tenure"], "by_amount": grid["by_amount"]}
        offers.append(entry)
    return _clean({
        "meta": {"run_id": run.run_id, "catalog_version": run.catalog_version, "currency": "INR",
                 "disclaimer": catalog.disclaimer},
        "user": user, "offers": offers,
        "glossary": static["glossary"], "how_we_decide": " ".join(static["how_we_decide"].split()),
    })


def context_json(ctx: dict) -> str:
    """Deterministic, compact serialisation: byte-identical for the same run."""
    return json.dumps(ctx, ensure_ascii=False, separators=(",", ":"))


def context_hash(ctx_json: str) -> str:
    return hashlib.sha256(ctx_json.encode()).hexdigest()[:16]


def estimate_tokens(ctx_json: str) -> int:
    return int(len(ctx_json) / 3.5)
