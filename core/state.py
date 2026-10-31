"""Application state: plain, serialisable models that the pipeline mutates and the UI renders.

No Streamlit imports. Phase 4 persists this to SQLite.
"""
import threading
import uuid
from datetime import datetime, timezone
from typing import Any, Literal

from pydantic import BaseModel, Field, PrivateAttr

from core.config.loader import get_policy, get_schemas
from core.models import DocIssue, DocSpec, FieldResult, FieldStatus, QualityIssue
from core.requirements import build_checklist

SlotStatus = Literal["pending", "rejected", "needs_attention", "verified", "manual_review"]

DOC_TYPE_LABELS = {
    "pan": "PAN card", "aadhaar_front": "Aadhaar card (front)", "aadhaar_back": "Aadhaar card (back)",
    "salary_slip": "salary slip", "bank_statement": "bank statement", "form16": "Form 16", "itr": "ITR",
    "gst_certificate": "GST certificate", "utility_bill": "utility bill", "other": "a different kind of document",
}

_OK_FIELD = {FieldStatus.VALID, FieldStatus.USER_ENTERED_VALID}


class Notice(BaseModel):
    """Why the last upload for a slot was not accepted (shown as a banner)."""
    code: str
    message: str
    fix_hint: str = ""
    severity: Literal["error", "warning"] = "error"
    offer_manual_review: bool = False


class Part(BaseModel):
    """One logical document: a single ID/statement, or one salary slip (a month)."""
    file_name: str
    file_hash: str
    pages: int = 1
    detected_type: str | None = None
    fully_visible: bool = True
    fields: list[FieldResult] = Field(default_factory=list)
    issues: list[DocIssue] = Field(default_factory=list)
    quality_warnings: list[QualityIssue] = Field(default_factory=list)
    extraction_failed: bool = False
    schema_type: str | None = None      # which schema this part was read with (Form 16 vs ITR)
    error: str | None = None            # why automatic reading failed (error type and short message, never document content)


class SlotState(BaseModel):
    slot_id: str
    spec: DocSpec
    label: str
    schema_type: str | None            # key in doc_schemas.yaml; None = not extractable yet
    schema_types: dict[str, str] = Field(default_factory=dict)   # detected type -> schema, for 'Form 16 or ITR'
    expected_types: list[str]
    required_parts: int = 1
    max_pages: int = 1
    parts: list[Part] = Field(default_factory=list)
    set_issues: list[DocIssue] = Field(default_factory=list)
    notice: Notice | None = None
    api_uploads: int = 0
    file_hashes: list[str] = Field(default_factory=list)
    pages_used: int = 0
    manual_review: bool = False

    @property
    def optional(self) -> bool:
        return self.spec.optional

    @property
    def extractable(self) -> bool:
        return self.schema_type is not None or bool(self.schema_types)

    def schema_for(self, part: "Part") -> str | None:
        return part.schema_type or self.schema_type or next(iter(self.schema_types.values()), None)


class ApplicationState(BaseModel):
    app_id: str = Field(default_factory=lambda: uuid.uuid4().hex)
    loan_type: str | None = None
    employment: str | None = None
    consent_at: datetime | None = None
    slots: dict[str, SlotState] = Field(default_factory=dict)
    api_calls: int = 0
    manual_review_ack: bool = False
    status: str = "draft"
    scrubbed: bool = False                 # True after save: sensitive values in memory are masked, never re-written
    persisted_events: int = 0
    events: list[dict[str, Any]] = Field(default_factory=list)   # audit trail: ids and codes only, never PII
    _lock: threading.RLock = PrivateAttr(default_factory=threading.RLock)

    def log(self, event: str, slot_id: str | None = None, **data) -> None:
        with self._lock:
            self.events.append({"event": event, "slot": slot_id, "at": datetime.now(timezone.utc).isoformat(), **data})


def build_slots(loan_type: str, employment: str) -> dict[str, SlotState]:
    """Checklist -> upload slots. Aadhaar splits into front/back; salary slips take several parts."""
    schemas = get_schemas()["schemas"]
    policy = get_policy()
    slots: dict[str, SlotState] = {}
    for spec in build_checklist(loan_type, employment):
        if spec.sides:
            variants = [(f"{spec.id}_{side}", f"{spec.display_name} ({side})", f"{spec.id}_{side}",
                         [f"{spec.id}_{side}"]) for side in spec.sides]
        else:
            first = spec.expected_types[0]
            schema_type = spec.id if spec.id in schemas else (first if first in schemas else None)
            variants = [(spec.id, spec.display_name, schema_type, spec.expected_types)]
        for slot_id, label, schema_type, expected in variants:
            if schema_type not in schemas:
                schema_type = None
            schema_types = {t: t for t in expected if t in schemas} if len(expected) > 1 else {}
            is_slip = spec.id == "salary_slip"
            slots[slot_id] = SlotState(
                slot_id=slot_id, spec=spec, label=label, schema_type=schema_type, schema_types=schema_types,
                expected_types=expected,
                required_parts=spec.count,
                max_pages=policy.limits.max_salary_slip_pages if is_slip else
                policy.files.max_pdf_pages_by_doc.get(spec.id, policy.files.max_pdf_pages))
    return slots


def new_application(loan_type: str, employment: str) -> ApplicationState:
    return ApplicationState(loan_type=loan_type, employment=employment,
                            slots=build_slots(loan_type, employment))


# ---- status helpers -------------------------------------------------------------------------

def all_fields(slot: SlotState) -> list[FieldResult]:
    return [f for p in slot.parts for f in p.fields]


def blocking_issues(slot: SlotState) -> list[DocIssue]:
    return [i for p in slot.parts for i in p.issues if i.severity == "error"] + \
           [i for i in slot.set_issues if i.severity == "error"]


def slot_status(slot: SlotState) -> SlotStatus:
    if slot.manual_review:
        return "manual_review"
    if not slot.parts:
        return "rejected" if slot.notice and slot.notice.severity == "error" else "pending"
    if len(slot.parts) < slot.required_parts:
        return "pending"
    if blocking_issues(slot):
        return "needs_attention"
    bad = [f for f in all_fields(slot) if f.required and f.status not in _OK_FIELD | {FieldStatus.NEEDS_MANUAL_REVIEW}]
    if bad:
        return "needs_attention"
    if any(f.status == FieldStatus.NEEDS_MANUAL_REVIEW for f in all_fields(slot)):
        return "manual_review"
    return "verified"


def progress(state: ApplicationState) -> tuple[int, int]:
    """(ready, total) over required slots."""
    req = [s for s in state.slots.values() if not s.optional]
    ready = sum(1 for s in req if slot_status(s) in ("verified", "manual_review"))
    return ready, len(req)


def readiness(state: ApplicationState) -> tuple[bool, list[str]]:
    """Gate to the review step (plan.md section 10.3)."""
    problems = []
    for s in state.slots.values():
        if s.optional and not s.parts:
            continue
        st = slot_status(s)
        if st in ("pending", "rejected"):
            problems.append(f"{s.label}: not uploaded yet" if not s.parts else f"{s.label}: needs {s.required_parts - len(s.parts)} more")
        elif st == "needs_attention":
            problems.append(f"{s.label}: needs your attention")
    needs_ack = any(slot_status(s) == "manual_review" for s in state.slots.values())
    if needs_ack and not state.manual_review_ack:
        problems.append("Please acknowledge that some details will be sent for manual review.")
    return (not problems), problems
