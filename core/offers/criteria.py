"""One function per criterion. Each returns a CriterionResult with the gap already computed."""
from dataclasses import dataclass

from core.offers.catalog import Offer
from core.offers.models import CriterionResult, Facts, LoanRequest

PROFILE_IDS = ["EMPLOYMENT", "MIN_INCOME", "AGE_MIN", "AGE_AT_MATURITY", "SCORE_MIN", "TENURE_RANGE", "DOCS"]


@dataclass
class EvalCtx:
    offer: Offer
    facts: Facts
    req: LoanRequest
    rate: float
    tenure_eff: int          # requested tenure clamped into the offer's range (for EMI maths only)
    capacity: float          # monthly EMI room: foir_cap * income - existing EMIs, floored at 0
    cap_principal: float     # largest principal that fits the capacity
    emi_req: float           # EMI for the requested amount


def _num(x: float) -> float:
    return round(x, 2) if x != int(x) else int(x)


def employment(c: EvalCtx) -> CriterionResult:
    ok = c.facts.employment in c.offer.employment
    return CriterionResult(id="EMPLOYMENT", label="Employment type", status="pass" if ok else "fail",
                           required=", ".join(c.offer.employment), actual=c.facts.employment)


def min_income(c: EvalCtx) -> CriterionResult:
    ok = c.facts.income >= c.offer.min_net_income
    return CriterionResult(id="MIN_INCOME", label="Minimum monthly income", status="pass" if ok else "fail",
                           required=_num(c.offer.min_net_income), actual=_num(c.facts.income),
                           gap=None if ok else _num(c.offer.min_net_income - c.facts.income),
                           fix_hint=None if ok else "add_coapplicant_income")


def age_min(c: EvalCtx) -> CriterionResult:
    ok = c.facts.age >= c.offer.min_age
    return CriterionResult(id="AGE_MIN", label="Minimum age", status="pass" if ok else "fail",
                           required=c.offer.min_age, actual=c.facts.age, gap=None if ok else c.offer.min_age - c.facts.age)


def age_at_maturity(c: EvalCtx) -> CriterionResult:
    aam = c.facts.age + c.req.tenure_months / 12
    ok = aam <= c.offer.max_age_at_maturity
    return CriterionResult(id="AGE_AT_MATURITY", label="Age at the end of the loan", status="pass" if ok else "fail",
                           required=c.offer.max_age_at_maturity, actual=round(aam, 1),
                           gap=None if ok else round(aam - c.offer.max_age_at_maturity, 1),
                           user_controllable=True, fix_hint=None if ok else "shorten_tenure")


def score_min(c: EvalCtx) -> CriterionResult:
    need = c.offer.min_credit_score
    if need is None:
        return CriterionResult(id="SCORE_MIN", label="Minimum credit score", status="pass", required="not needed")
    s = c.facts.credit_score
    if s is None:
        return CriterionResult(id="SCORE_MIN", label="Minimum credit score", status="unknown", required=need,
                               actual="not provided", user_controllable=True, fix_hint="provide_credit_score")
    ok = s >= need
    return CriterionResult(id="SCORE_MIN", label="Minimum credit score", status="pass" if ok else "fail",
                           required=need, actual=s, gap=None if ok else need - s, user_controllable=True,
                           fix_hint=None if ok else "improve_score")


def tenure_range(c: EvalCtx) -> CriterionResult:
    t, r = c.req.tenure_months, c.offer.tenure_months
    ok = r.min <= t <= r.max
    gap = None if ok else (_num(r.min - t) if t < r.min else _num(t - r.max))
    return CriterionResult(id="TENURE_RANGE", label="Loan tenure (months)", status="pass" if ok else "fail",
                           required=f"{_num(r.min)}-{_num(r.max)}", actual=t, gap=gap, user_controllable=True,
                           fix_hint=None if ok else ("extend_tenure" if t < r.min else "shorten_tenure"))


def docs(c: EvalCtx) -> CriterionResult:
    missing = [d for d in c.offer.required_docs if d not in c.facts.documents_verified]
    return CriterionResult(id="DOCS", label="Required documents", status="fail" if missing else "pass",
                           required=", ".join(c.offer.required_docs), actual=", ".join(c.facts.documents_verified),
                           gap=len(missing) or None, user_controllable=True,
                           fix_hint="upload_document" if missing else None,
                           detail=("missing: " + ", ".join(missing)) if missing else None)


def amount_range(c: EvalCtx) -> CriterionResult:
    a, r = c.req.amount, c.offer.amount
    ok = r.min <= a <= r.max
    gap = None if ok else (_num(r.min - a) if a < r.min else _num(a - r.max))
    return CriterionResult(id="AMOUNT_RANGE", label="Loan amount", status="pass" if ok else "fail",
                           required=f"{_num(r.min)}-{_num(r.max)}", actual=_num(a), gap=gap, user_controllable=True,
                           fix_hint=None if ok else ("increase_amount" if a < r.min else "reduce_amount"))


def foir(c: EvalCtx) -> CriterionResult:
    allowed = c.offer.foir_cap * c.facts.income
    total = c.facts.existing_emi + c.emi_req
    ok = total <= allowed + 1e-6
    return CriterionResult(id="FOIR", label="Monthly EMIs within the limit", status="pass" if ok else "fail",
                           required=round(allowed), actual=round(total), gap=None if ok else round(total - allowed),
                           user_controllable=True, fix_hint=None if ok else "reduce_amount")


ALL = [employment, min_income, age_min, age_at_maturity, score_min, tenure_range, docs, amount_range, foir]


def evaluate_criteria(c: EvalCtx) -> list[CriterionResult]:
    return [f(c) for f in ALL]
