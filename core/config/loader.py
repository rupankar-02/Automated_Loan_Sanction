"""Load and validate the YAML config files."""
from datetime import date
from functools import lru_cache
from pathlib import Path

import yaml
from pydantic import BaseModel

CONFIG_DIR = Path(__file__).parent


def _load(name: str) -> dict:
    with open(CONFIG_DIR / name, encoding="utf-8") as f:
        return yaml.safe_load(f)


class FilePolicy(BaseModel):
    allowed_ext: list[str]
    min_image_kb: int
    max_mb: int
    max_pdf_pages: int
    max_pdf_pages_by_doc: dict[str, int] = {}


class ImagePolicy(BaseModel):
    min_long_side_id: int
    min_short_side_a4: int
    blur_min_id: float
    blur_min_a4: float
    dark_mean_below: float
    bright_mean_above: float
    glare_pixel_pct: float
    border_margin_px: int


class PdfPolicy(BaseModel):
    render_dpi: int


class ApplicantPolicy(BaseModel):
    min_age: int
    preferred_age_min: int
    preferred_age_max: int


class RetryPolicy(BaseModel):
    max_field_attempts: int


class MonthsPolicy(BaseModel):
    reference_date: date | None = None
    required_months: int
    slip_grace_days: int
    allow_current_month: bool
    bank_start_tolerance_days: int
    bank_recency_days: int


class LimitsPolicy(BaseModel):
    max_reuploads_per_slot: int
    max_api_calls_per_application: int
    max_salary_slip_pages: int
    sarvam_requests_per_minute: int
    sarvam_retries: int
    parallel_workers: int


class Policy(BaseModel):
    files: FilePolicy
    image: ImagePolicy
    pdf: PdfPolicy
    applicant: ApplicantPolicy
    retries: RetryPolicy
    months: MonthsPolicy
    limits: LimitsPolicy


@lru_cache
def get_policy() -> Policy:
    return Policy(**_load("policy.yaml"))


@lru_cache
def get_requirements() -> dict:
    return _load("doc_requirements.yaml")


@lru_cache
def get_schemas() -> dict:
    return _load("doc_schemas.yaml")


def get_schema_fields(doc_type: str) -> list[dict]:
    schemas = get_schemas()["schemas"]
    if doc_type not in schemas:
        raise KeyError(f"No extraction schema for '{doc_type}'.")
    return schemas[doc_type]["fields"]
