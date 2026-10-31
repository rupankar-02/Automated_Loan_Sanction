"""Compute one complete offers run: evaluations + suggestions + what-if grids."""
import hashlib
import json

from core.offers.catalog import Catalog, get_catalog
from core.offers.engine import evaluate_all
from core.offers.gaps import suggest_all
from core.offers.models import Facts, LoanRequest, OfferRun
from core.offers.scenarios import grid_for_offer


def run_id_for(facts: Facts, req: LoanRequest, catalog_version: str) -> str:
    payload = json.dumps([facts.model_dump(), req.model_dump(exclude={"purpose"}), catalog_version], sort_keys=True)
    return "r_" + hashlib.sha1(payload.encode()).hexdigest()[:8]


def compute_run(facts: Facts, req: LoanRequest, catalog: Catalog | None = None) -> OfferRun:
    catalog = catalog or get_catalog()
    evals = evaluate_all(facts, req, catalog)
    suggestions = suggest_all(evals, facts, req, catalog)
    scenarios = {}
    for e in evals:
        failed = {c.id for c in e.failed()}
        grid = grid_for_offer(catalog.offer(e.offer_id), facts, req, catalog, failed)
        if grid:
            scenarios[e.offer_id] = grid
    return OfferRun(run_id=run_id_for(facts, req, catalog.catalog_version), catalog_version=catalog.catalog_version,
                    facts=facts, request=req, evaluations=evals, suggestions=suggestions, scenarios=scenarios)
