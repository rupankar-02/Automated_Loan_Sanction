"""Load and validate offers.yaml. Bad config fails fast at load time."""
from functools import lru_cache
from pathlib import Path

import yaml
from pydantic import BaseModel, model_validator

CONFIG = Path(__file__).resolve().parents[1] / "config"


class Range(BaseModel):
    min: float
    max: float

    @model_validator(mode="after")
    def _ordered(self):
        if self.min > self.max:
            raise ValueError(f"range min {self.min} is above max {self.max}")
        return self


class Offer(BaseModel):
    id: str
    name: str
    lender: str
    employment: list[str]
    min_net_income: float
    min_age: int
    max_age_at_maturity: int
    min_credit_score: int | None = None
    amount: Range
    tenure_months: Range
    rate_band_pct: Range
    processing_fee_pct: float
    foir_cap: float
    prepayment_charge_pct: float = 0.0
    required_docs: list[str]

    @model_validator(mode="after")
    def _sane(self):
        if not 0 < self.foir_cap <= 1:
            raise ValueError(f"{self.id}: foir_cap must be in (0, 1]")
        if self.min_age >= self.max_age_at_maturity:
            raise ValueError(f"{self.id}: min_age must be below max_age_at_maturity")
        return self


class RateTier(BaseModel):
    min_score: int | None = None
    default: bool = False
    position: float


class Catalog(BaseModel):
    catalog_version: str
    disclaimer: str
    inputs: dict
    grids: dict
    rate_tiers: list[RateTier]
    adjustments: dict[str, float]
    offers: list[Offer]

    @model_validator(mode="after")
    def _unique(self):
        ids = [o.id for o in self.offers]
        if len(ids) != len(set(ids)):
            raise ValueError("duplicate offer ids")
        if not any(t.default for t in self.rate_tiers):
            raise ValueError("rate_tiers needs a default tier")
        return self

    def offer(self, offer_id: str) -> Offer:
        return next(o for o in self.offers if o.id == offer_id)

    @property
    def amount_bounds(self) -> tuple[float, float]:
        return min(o.amount.min for o in self.offers), max(o.amount.max for o in self.offers)


def load_catalog(path: Path | None = None) -> Catalog:
    with open(path or CONFIG / "offers.yaml", encoding="utf-8") as f:
        return Catalog(**yaml.safe_load(f))


@lru_cache
def get_catalog() -> Catalog:
    return load_catalog()


@lru_cache
def get_chat_static() -> dict:
    with open(CONFIG / "chat_static.yaml", encoding="utf-8") as f:
        return yaml.safe_load(f)


def indicative_rate(offer: Offer, score: int | None, has_form16: bool, catalog: Catalog) -> float:
    """Rate inside the offer's band: tier by credit score (unknown score -> top of band), then the Form 16 discount."""
    pos = next((t.position for t in catalog.rate_tiers if t.min_score is not None and score is not None
                and score >= t.min_score), None)
    if pos is None:
        pos = next(t.position for t in catalog.rate_tiers if t.default)
    band = offer.rate_band_pct
    rate = band.min + pos * (band.max - band.min)
    if has_form16:
        rate += catalog.adjustments.get("form16_provided", 0.0)
    return round(max(rate, band.min), 2)
