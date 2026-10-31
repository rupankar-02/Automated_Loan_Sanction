"""Typed objects for the offers engine."""
from typing import Any, Literal

from pydantic import BaseModel, Field

Status = Literal["eligible", "eligible_reduced", "not_eligible", "needs_info"]
STATUS_ORDER = {"not_eligible": 0, "needs_info": 1, "eligible_reduced": 2, "eligible": 3}


class Facts(BaseModel):
    """Derived, non-identifying facts about the applicant."""
    first_name: str | None = None
    age: int
    employment: str = "salaried"
    net_monthly_income: float
    income_variation_warning: bool = False
    existing_emi: float = 0.0
    credit_score: int | None = None
    documents_verified: list[str] = Field(default_factory=list)
    coapplicant_income: float = 0.0              # what-if only

    @property
    def income(self) -> float:
        return self.net_monthly_income + self.coapplicant_income

    @property
    def has_form16(self) -> bool:
        return "form16" in self.documents_verified


class LoanRequest(BaseModel):
    amount: float
    tenure_months: int
    purpose: str | None = None                   # personalisation only: never used in rules


class CriterionResult(BaseModel):
    id: str
    label: str
    status: Literal["pass", "fail", "unknown"]
    required: str | float | None = None
    actual: str | float | None = None
    gap: float | None = None                     # precomputed shortfall: the model never subtracts
    user_controllable: bool = False
    fix_hint: str | None = None                  # lever id
    detail: str | None = None


class OfferEvaluation(BaseModel):
    offer_id: str
    status: Status
    criteria: list[CriterionResult]
    max_eligible_amount: int | None = None
    indicative_rate_pct: float | None = None
    evaluated_amount: int | None = None          # the amount the figures below are for
    evaluated_for: Literal["requested", "max_eligible"] | None = None
    emi: int | None = None
    total_interest: int | None = None
    processing_fee: int | None = None
    total_cost: int | None = None
    rank: int | None = None
    rank_reason: str | None = None

    def failed(self) -> list[CriterionResult]:
        return [c for c in self.criteria if c.status == "fail"]


class Suggestion(BaseModel):
    lever: str
    change: str
    resulting_status: Status
    trade_off: str | None = None
    effort: int = 1
    params: dict[str, Any] = Field(default_factory=dict)


class OfferRun(BaseModel):
    run_id: str
    catalog_version: str
    facts: Facts
    request: LoanRequest
    evaluations: list[OfferEvaluation]
    suggestions: dict[str, list[Suggestion]] = Field(default_factory=dict)
    scenarios: dict[str, dict[str, list[dict]]] = Field(default_factory=dict)

    def evaluation(self, offer_id: str) -> OfferEvaluation:
        return next(e for e in self.evaluations if e.offer_id == offer_id)
