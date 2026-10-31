"""Typed result objects shared across the pipeline (plan.md §6.3, §9.4)."""
from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, Field


class QualityIssue(BaseModel):
    code: str                       # BLURRY, CROPPED, LOW_RES, TOO_DARK, FILE_TOO_LARGE, ...
    message: str                    # user-facing: what is wrong
    fix_hint: str                   # user-facing: what to do
    severity: Literal["error", "warning"]
    metric: dict[str, Any] | None = None


class QualityResult(BaseModel):
    passed: bool
    issues: list[QualityIssue] = Field(default_factory=list)

    @property
    def errors(self) -> list[QualityIssue]:
        return [i for i in self.issues if i.severity == "error"]

    @property
    def warnings(self) -> list[QualityIssue]:
        return [i for i in self.issues if i.severity == "warning"]

    def has(self, code: str) -> bool:
        return any(i.code == code for i in self.issues)


class FieldStatus(str, Enum):
    VALID = "valid"
    NOT_EXTRACTED = "not_extracted"
    INVALID = "invalid"
    USER_ENTERED_VALID = "user_entered_valid"
    NEEDS_MANUAL_REVIEW = "needs_manual_review"


class RuleResult(BaseModel):
    ok: bool
    rule_id: str
    severity: Literal["error", "warning"] = "error"
    message: str = ""


class FieldResult(BaseModel):
    key: str
    label: str
    raw_value: str | None = None
    normalized_value: str | None = None
    status: FieldStatus = FieldStatus.NOT_EXTRACTED
    failed_rule_id: str | None = None
    message: str | None = None
    required: bool = True
    warning: str | None = None      # non-blocking rule failure; status stays VALID
    source: Literal["vlm", "user"] = "vlm"
    user_corrected: bool = False
    attempts: int = 0


class DocIssue(BaseModel):
    """Document-level or set-level rule failure."""
    rule_id: str
    severity: Literal["error", "warning"] = "error"
    message: str
    action: Literal["reupload", "edit"] = "reupload"
    metric: dict[str, Any] | None = None


class DocSpec(BaseModel):
    """One checklist entry, built from doc_requirements.yaml."""
    id: str
    display_name: str
    description: str
    kind: Literal["id", "a4"]
    accepts: list[str]
    expected_types: list[str]
    sides: list[str] = Field(default_factory=list)
    count: int = 1
    recency_months: int | None = None
    alternatives: list[str] = Field(default_factory=list)
    optional: bool = False


class DocumentResult(BaseModel):
    status: Literal["rejected", "wrong_document", "extraction_failed", "extracted"]
    quality: QualityResult | None = None
    detected_type: str | None = None
    fields: list[FieldResult] = Field(default_factory=list)
    issues: list[DocIssue] = Field(default_factory=list)
