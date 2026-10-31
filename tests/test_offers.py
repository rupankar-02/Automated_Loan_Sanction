import random

import pytest
import yaml
from pydantic import ValidationError

from core.demo import PROFILES, build_demo_state
from core.offers import finance
from core.offers.catalog import Catalog, get_catalog, indicative_rate, load_catalog
from core.offers.engine import evaluate_offer
from core.offers.facts import derive_facts, validate_inputs
from core.offers.models import Facts, LoanRequest
from core.offers.run import compute_run, run_id_for
from core.offers.simulate import simulate, simulate_offer

CAT = get_catalog()
DOCS = ["pan", "aadhaar", "salary_slip", "bank_statement"]


def facts(**kw):
    base = dict(first_name="Test", age=29, net_monthly_income=60000, existing_emi=0, credit_score=760, documents_verified=DOCS + ["form16"])
    return Facts(**{**base, **kw})


def ev(offer_id, f=None, amount=400000, tenure=36):
    return evaluate_offer(CAT.offer(offer_id), f or facts(), LoanRequest(amount=amount, tenure_months=tenure), CAT)


def failed_ids(e):
    return {c.id for c in e.failed()}


# ---- finance --------------------------------------------------------------------------------------

def test_golden_max_principal():
    capacity = 0.5 * 60000 - 10000                                   # 20,000
    assert round(finance.max_principal(capacity, 12, 36)) == 602150


def test_emi_known_values_and_inverse():
    assert round(finance.emi(100000, 12, 12), 2) == 8884.88
    e = finance.emi(500000, 13.5, 48)
    assert finance.max_principal(e, 13.5, 48) == pytest.approx(500000, rel=1e-9)
    assert finance.emi(120000, 0, 12) == 10000
    assert round(finance.total_cost(100000, 12, 12, 2.0)) == round(8884.88 * 12 - 100000 + 2000)


# ---- catalog ------------------------------------------------------------------------------------------

def test_catalog_loads_five_offers():
    assert CAT.catalog_version and len(CAT.offers) == 5


def _bad(mutate, tmp_path):
    data = yaml.safe_load(open("core/config/offers.yaml", encoding="utf-8"))
    mutate(data)
    p = tmp_path / "offers.yaml"
    p.write_text(yaml.safe_dump(data), encoding="utf-8")
    return load_catalog(p)


def test_bad_catalog_fails_fast(tmp_path):
    with pytest.raises(ValidationError):
        _bad(lambda d: d["offers"][0]["amount"].update(min=500000), tmp_path)           # min > max
    with pytest.raises(ValidationError):
        _bad(lambda d: d["offers"][0].pop("foir_cap"), tmp_path)                        # missing field
    with pytest.raises(ValidationError):
        _bad(lambda d: d["offers"][1].update(id=d["offers"][0]["id"]), tmp_path)        # duplicate id
    with pytest.raises(ValidationError):
        _bad(lambda d: d["offers"][0].update(foir_cap=1.5), tmp_path)


def test_rate_tiers_and_form16_discount():
    std = CAT.offer("standard")                                       # band 12.0 to 15.0
    assert indicative_rate(std, 820, False, CAT) == 12.0
    assert indicative_rate(std, 760, False, CAT) == 12.99
    assert indicative_rate(std, 720, False, CAT) == 13.98
    assert indicative_rate(std, 650, False, CAT) == 15.0
    assert indicative_rate(std, None, False, CAT) == 15.0             # unknown score -> top of band
    assert indicative_rate(std, 720, True, CAT) == 13.73
    assert indicative_rate(std, 820, True, CAT) == 12.0              # floored at the band minimum


# ---- criteria boundaries ---------------------------------------------------------------------------------

def test_income_boundary():
    assert "MIN_INCOME" not in failed_ids(ev("standard", facts(net_monthly_income=30000)))
    e = ev("standard", facts(net_monthly_income=29999))
    c = next(c for c in e.failed() if c.id == "MIN_INCOME")
    assert e.status == "not_eligible" and c.gap == 1 and c.required == 30000 and c.actual == 29999


def test_age_and_age_at_maturity():
    assert "AGE_MIN" in failed_ids(ev("standard", facts(age=20)))
    assert "AGE_AT_MATURITY" not in failed_ids(ev("standard", facts(age=57), tenure=36))      # 57 + 3 = 60
    e = ev("standard", facts(age=58), tenure=36)                                              # 61 > 60
    c = next(c for c in e.failed() if c.id == "AGE_AT_MATURITY")
    assert c.gap == 1.0 and c.user_controllable


def test_score_pass_fail_unknown():
    assert "SCORE_MIN" not in failed_ids(ev("standard", facts(credit_score=700)))
    e = ev("standard", facts(credit_score=699))
    assert next(c for c in e.failed() if c.id == "SCORE_MIN").gap == 1
    u = ev("standard", facts(credit_score=None))
    assert u.status == "needs_info" and next(c for c in u.criteria if c.id == "SCORE_MIN").status == "unknown"
    assert ev("quick_small", facts(credit_score=None), amount=50000, tenure=12).status == "eligible"   # no score needed


def test_tenure_and_amount_ranges():
    assert "TENURE_RANGE" in failed_ids(ev("quick_small", amount=50000, tenure=24))
    assert "TENURE_RANGE" in failed_ids(ev("standard", tenure=6))
    assert ev("standard", amount=40000).status == "not_eligible"                     # below the offer minimum
    assert "AMOUNT_RANGE" in failed_ids(ev("standard", amount=40000))


def test_docs_criterion_names_missing_documents():
    e = ev("premium", facts(documents_verified=DOCS))
    c = next(c for c in e.failed() if c.id == "DOCS")
    assert e.status == "not_eligible" and "form16" in c.detail and c.fix_hint == "upload_document"


def test_foir_boundary_and_status():
    f = facts(net_monthly_income=50000, existing_emi=0, credit_score=760)
    cap = finance.max_principal(0.5 * 50000, indicative_rate(CAT.offer("standard"), 760, True, CAT), 36)
    inside = ev("standard", f, amount=int(cap) - 1)
    outside = ev("standard", f, amount=int(cap) + 1000)
    assert inside.status == "eligible" and "FOIR" not in failed_ids(inside)
    assert outside.status == "eligible_reduced" and "FOIR" in failed_ids(outside)
    assert outside.evaluated_for == "max_eligible" and outside.evaluated_amount == outside.max_eligible_amount


def test_status_values():
    assert ev("standard").status == "eligible"
    assert ev("standard", facts(net_monthly_income=10000)).status == "not_eligible"
    assert ev("standard", facts(credit_score=None)).status == "needs_info"
    assert ev("standard", facts(net_monthly_income=35000, existing_emi=10000), amount=900000).status == "eligible_reduced"
    assert ev("standard", facts(net_monthly_income=35000, existing_emi=17000)).status == "not_eligible"   # no room even for the minimum


def test_requested_amount_money_fields_are_consistent():
    e = ev("standard")
    assert e.emi == round(finance.emi(400000, e.indicative_rate_pct, 36))
    assert e.total_cost == e.total_interest + e.processing_fee
    assert e.processing_fee == 6000 and e.evaluated_amount == 400000


# ---- ranking, runs, simulate --------------------------------------------------------------------------------

def test_ranking_is_by_total_cost_then_reduced_offers():
    run = compute_run(facts(), LoanRequest(amount=400000, tenure_months=36))
    ranked = sorted((e for e in run.evaluations if e.rank), key=lambda e: e.rank)
    eligible = [e for e in ranked if e.status == "eligible"]
    assert [e.total_cost for e in eligible] == sorted(e.total_cost for e in eligible)
    assert ranked[0].rank_reason.startswith("lowest total cost for ₹4,00,000")
    assert all(e.rank is None for e in run.evaluations if e.status in ("not_eligible", "needs_info"))


def test_run_id_is_stable_and_input_sensitive():
    f, r = facts(), LoanRequest(amount=400000, tenure_months=36)
    assert run_id_for(f, r, "v1") == run_id_for(f.model_copy(), r.model_copy(), "v1")
    assert run_id_for(f, r, "v1") != run_id_for(f, LoanRequest(amount=410000, tenure_months=36), "v1")
    assert run_id_for(f, r, "v1") != run_id_for(f, r, "v2")
    assert run_id_for(f, r, "v1") == run_id_for(f, LoanRequest(amount=400000, tenure_months=36, purpose="wedding"), "v1")


def test_simulate_does_not_mutate_inputs():
    f, r = facts(), LoanRequest(amount=400000, tenure_months=36)
    snapshot = (f.model_dump(), r.model_dump())
    simulate(f, r, amount=900000, tenure_months=60, existing_emi=20000, coapplicant_income=10000)
    assert (f.model_dump(), r.model_dump()) == snapshot


# ---- gap solver: the promised status is the engine's status ------------------------------------------------

def _random_profile(rng):
    f = Facts(first_name="T", age=rng.randint(19, 60), net_monthly_income=rng.choice([12000, 18000, 25000, 40000, 52400, 75000, 120000]),
              existing_emi=rng.choice([0, 3000, 8000, 20000]), credit_score=rng.choice([None, 620, 690, 720, 760, 810]),
              documents_verified=rng.choice([DOCS, DOCS + ["form16"], ["pan"]]))
    r = LoanRequest(amount=rng.choice([20000, 60000, 150000, 400000, 900000, 1800000]), tenure_months=rng.choice([6, 12, 24, 36, 60, 84]))
    return f, r


def test_every_suggestion_delivers_its_promised_status():
    rng, checked = random.Random(11), 0
    for _ in range(120):
        f, r = _random_profile(rng)
        run = compute_run(f, r)
        for oid, sugs in run.suggestions.items():
            current = run.evaluation(oid)
            for s in sugs:
                if s.lever == "choose_other_offer":
                    assert run.evaluation(s.params["offer_id"]).status == s.resulting_status
                else:
                    changes = {k: v for k, v in s.params.items()}
                    if "docs" in changes:
                        changes["add_docs"] = changes.pop("docs")
                    if "clear" in changes:
                        changes = {"existing_emi": f.existing_emi - changes["clear"]}
                    assert simulate_offer(oid, f, r, CAT, **changes).status == s.resulting_status, (oid, s)
                if s.lever in ("reduce_amount", "increase_amount", "shorten_tenure", "reduce_existing_emi"):
                    from core.offers.models import STATUS_ORDER
                    assert STATUS_ORDER[s.resulting_status] > STATUS_ORDER[current.status]
                checked += 1
    assert checked > 100


def test_suggestions_state_the_trade_off_for_longer_tenure():
    f = facts(net_monthly_income=60000, existing_emi=10000, credit_score=760)
    r = LoanRequest(amount=600000, tenure_months=24)
    run = compute_run(f, r)
    sugs = [s for s in run.suggestions["standard"] if s.lever == "extend_tenure"]
    assert sugs and sugs[0].resulting_status == "eligible"
    assert "total interest rises by" in sugs[0].trade_off
    new_t = sugs[0].params["tenure_months"]
    assert new_t > 24 and simulate_offer("standard", f, r, CAT, tenure_months=new_t - 1).status != "eligible"   # the smallest fix


# ---- scenario grids equal fresh runs -----------------------------------------------------------------------

def test_every_grid_cell_equals_a_fresh_engine_run():
    f, r = facts(net_monthly_income=52400, existing_emi=8000, credit_score=720, documents_verified=DOCS), LoanRequest(amount=400000, tenure_months=36)
    run = compute_run(f, r)
    assert run.scenarios
    cells = 0
    for oid, grid in run.scenarios.items():
        for row in grid["by_tenure"]:
            e = simulate_offer(oid, f, r, CAT, tenure_months=row["tenure_months"])
            assert (row["status"], row["max_amount"], row["emi"], row["interest"]) == (e.status, e.max_eligible_amount, e.emi, e.total_interest)
            cells += 1
        for row in grid["by_amount"]:
            e = simulate_offer(oid, f, r, CAT, amount=row["amount"])
            assert (row["status"], row["emi"]) == (e.status, e.emi)
            cells += 1
    assert cells > 30


def test_grids_skip_offers_the_user_cannot_fix():
    run = compute_run(facts(net_monthly_income=18000, credit_score=620, documents_verified=DOCS), LoanRequest(amount=50000, tenure_months=12))
    assert "premium" not in run.scenarios and "standard" not in run.scenarios      # income below minimum


# ---- demo profiles and facts ----------------------------------------------------------------------------------

def test_borderline_profile_matches_the_demo_story():
    p = PROFILES["borderline"]
    state = build_demo_state(p)
    f = derive_facts(state, existing_emi=p.existing_emi, credit_score=p.credit_score)
    assert f.net_monthly_income == 52400 and f.age in (30, 31) and f.first_name == "Priya"
    assert f.documents_verified == ["pan", "aadhaar", "salary_slip", "bank_statement"]
    run = compute_run(f, LoanRequest(amount=p.amount, tenure_months=p.tenure))
    prem = run.evaluation("premium")
    inc = next(c for c in prem.failed() if c.id == "MIN_INCOME")
    sc = next(c for c in prem.failed() if c.id == "SCORE_MIN")
    assert prem.status == "not_eligible" and inc.gap == 7600 and sc.gap == 30
    assert run.evaluation("standard").rank == 1 and run.evaluation("standard").status == "eligible"


def test_strong_profile_opens_premium_and_low_income_only_small_offers():
    s, l = PROFILES["strong"], PROFILES["low_income"]
    fs = derive_facts(build_demo_state(s), existing_emi=s.existing_emi, credit_score=s.credit_score)
    strong = compute_run(fs, LoanRequest(amount=s.amount, tenure_months=s.tenure))
    assert strong.evaluation("premium").status == "eligible" and "form16" in fs.documents_verified
    fl = derive_facts(build_demo_state(l), existing_emi=l.existing_emi, credit_score=l.credit_score)
    low = compute_run(fl, LoanRequest(amount=l.amount, tenure_months=l.tenure))
    assert {e.offer_id for e in low.evaluations if e.status == "eligible"} == {"quick_small"}


def test_income_variation_warning():
    from core.offers.facts import derive_net_income
    state = build_demo_state(PROFILES["borderline"])
    assert derive_net_income(state)[1] is False
    nets = [f for p in state.slots["salary_slip"].parts for f in p.fields if f.key == "net_salary"]
    nets[0].normalized_value = "30000"
    assert derive_net_income(state)[1] is True


# ---- input validation ----------------------------------------------------------------------------------------------

def test_validate_inputs():
    ok, err = validate_inputs("4,00,000", "36", "8000", "720")
    assert not err and ok == {"amount": 400000.0, "tenure_months": 36, "existing_emi": 8000.0, "credit_score": 720}
    assert validate_inputs(400000, 36, "", "unknown")[0]["credit_score"] is None
    for args, field in [((0, 36, 0, 700), "amount"), ((5_000_000, 36, 0, 700), "amount"), (("abc", 36, 0, 700), "amount"),
                        ((400000, 3, 0, 700), "tenure_months"), ((400000, 36.5, 0, 700), "tenure_months"),
                        ((400000, 36, -1, 700), "existing_emi"), ((400000, 36, 0, 950), "credit_score"), ((400000, 36, 0, 70.5), "credit_score")]:
        assert field in validate_inputs(*args)[1], args
