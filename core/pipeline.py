"""Orchestrates one upload end to end: duplicate check -> quality gate -> classify -> extract -> validate.

Order matters for cost: everything before `classify` is local and free; only what reaches the
API counts against the per-slot re-upload cap and the per-application call budget.
"""
from concurrent.futures import ThreadPoolExecutor
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from PIL import Image

from core.config.loader import get_policy
from core.errors import BudgetExceeded
from core.extraction import extract_document
from core.models import DocIssue, FieldResult, FieldStatus
from core.quality.gate import run_quality_checks
from core.state import (DOC_TYPE_LABELS, ApplicationState, Notice, Part, SlotState,
                        all_fields)
from core.utils.hashing import sha256_bytes
from core.validation.doc_rules import apply_document_rules, apply_salary_set_rules
from core.validation.field_rules import RuleContext, make_context, revalidate_user_value, validate_fields

Progress = Callable[[str, str], None]   # (slot_id, message)
_OK = {FieldStatus.VALID, FieldStatus.USER_ENTERED_VALID}


@dataclass
class UploadOutcome:
    slot_id: str
    status: str          # accepted | cached | rejected | blocked
    notice: Notice | None = None


class MeteredExtractor:
    """Wraps an extractor: charges the call budget, reports progress, forwards rate-limit waits."""

    def __init__(self, inner, state: ApplicationState, slot_id: str, on_progress: Progress | None):
        self.inner, self.state, self.slot_id, self.on_progress = inner, state, slot_id, on_progress

    def _say(self, msg: str) -> None:
        if self.on_progress:
            self.on_progress(self.slot_id, msg)

    def _charge(self) -> None:
        with self.state._lock:
            if self.state.api_calls >= get_policy().limits.max_api_calls_per_application:
                raise BudgetExceeded()
            self.state.api_calls += 1

    def classify(self, pages):
        self._charge()
        self._say("Checking what kind of document this is...")
        return self.inner.classify(pages)

    def extract(self, fields, pages=None, pdf_bytes=None, doc_type=None, **kw):
        self._charge()
        self._say("Reading the details...")
        return self.inner.extract(
            fields, pages=pages, pdf_bytes=pdf_bytes, doc_type=doc_type,
            on_wait=lambda s: self._say(f"Waiting for the reading service (about {int(s) + 1}s)..."))


def _notice_from_quality(result) -> Notice:
    first = result.errors[0]
    extra = " ".join(i.message for i in result.errors[1:])
    return Notice(code=first.code, message=(first.message + (" " + extra if extra else "")).strip(),
                  fix_hint=first.fix_hint)


def _max_api_uploads(slot: SlotState) -> int:
    return get_policy().limits.max_reuploads_per_slot + slot.required_parts


def _wrong_doc_notice(slot: SlotState, detected: str) -> Notice:
    want = DOC_TYPE_LABELS.get(slot.expected_types[0], slot.label) if len(slot.expected_types) == 1 else slot.spec.display_name
    if detected == "other":
        msg = f"This doesn't look like a {want}."
    else:
        seen = DOC_TYPE_LABELS.get(detected, detected)
        article = "an" if seen[:1].lower() in "aeiou" else "a"
        msg = f"This looks like {article} {seen}, but we asked for your {want}."
    return Notice(code="WRONG_DOCUMENT", message=msg, fix_hint=f"Please upload your {want} here.")


def _manual_review_notice(code: str, message: str) -> Notice:
    return Notice(code=code, message=message,
                  fix_hint="You can continue and send this document for manual review.", offer_manual_review=True)


# ---- recompute --------------------------------------------------------------------------------

def recompute(slot: SlotState, ctx: RuleContext) -> None:
    """Re-run document- and set-level rules after any change to the slot's fields."""
    for p in slot.parts:
        schema = slot.schema_for(p)
        if schema:
            p.issues = apply_document_rules(schema, p.fields, ctx)
    slot.set_issues = []
    if slot.schema_type == "salary_slip" and len(slot.parts) >= slot.required_parts:
        months = []
        for p in slot.parts:
            pm = next((f for f in p.fields if f.key == "pay_month"), None)
            if pm and pm.status in _OK and pm.normalized_value:
                months.append(pm.normalized_value)
        slot.set_issues = apply_salary_set_rules(months, ctx)


def _merge_continuation(prev: Part, cont: list[FieldResult]) -> None:
    """A page with no pay month continues the previous slip: fill only what that slip is missing."""
    by_key = {f.key: f for f in cont}
    for i, f in enumerate(prev.fields):
        c = by_key.get(f.key)
        if c and f.status not in _OK and c.status in _OK:
            prev.fields[i] = c
    prev.pages += 1


# ---- main entry --------------------------------------------------------------------------------

def process_upload(state: ApplicationState, slot_id: str, filename: str, data: bytes, extractor,
                   on_progress: Progress | None = None, ctx: RuleContext | None = None,
                   store=None) -> UploadOutcome:
    ctx = ctx or make_context()
    slot = state.slots[slot_id]
    say = (lambda m: on_progress(slot_id, m)) if on_progress else (lambda m: None)
    h = sha256_bytes(data)

    if not slot.extractable:
        n = Notice(code="NOT_SUPPORTED_YET", severity="warning",
                   message=f"{slot.label} can't be read automatically yet.", fix_hint="You can skip this optional document.")
        slot.notice = n
        return UploadOutcome(slot_id, "blocked", n)

    if h in slot.file_hashes:                               # Streamlit reruns: never pay twice
        return UploadOutcome(slot_id, "cached")
    for other in state.slots.values():
        if other.slot_id != slot_id and h in other.file_hashes:
            n = Notice(code="DUPLICATE_FILE", message=f"You already uploaded this file for {other.label}.",
                       fix_hint=f"Please choose your {slot.label} file.")
            slot.notice = n
            return UploadOutcome(slot_id, "rejected", n)

    # 1. local, free
    say("Checking the file quality...")
    quality, pages = run_quality_checks(filename, data, slot.spec.model_copy(update={"display_name": slot.label}))
    if not quality.passed:
        n = _notice_from_quality(quality)
        slot.notice = n
        state.log("quality_rejected", slot_id, code=quality.errors[0].code)
        return UploadOutcome(slot_id, "rejected", n)
    if store is not None:                                   # originals live only until the user confirms
        store.save(state.app_id, h, data, Path(filename).suffix.lower())
    if slot.schema_type == "salary_slip" and slot.pages_used + len(pages) > slot.max_pages:
        n = Notice(code="SLIP_PAGE_LIMIT", message=f"You can upload at most {slot.max_pages} salary-slip pages "
                   f"(3 months plus one continuation page); {slot.pages_used} are already used.",
                   fix_hint="Remove a slip you don't need, then upload again.")
        slot.notice = n
        return UploadOutcome(slot_id, "rejected", n)

    # 2. caps before spending anything
    if slot.api_uploads >= _max_api_uploads(slot):
        n = _manual_review_notice("REUPLOAD_LIMIT", f"{slot.label} has been uploaded too many times.")
        slot.notice = n
        return UploadOutcome(slot_id, "blocked", n)

    metered = MeteredExtractor(extractor, state, slot_id, on_progress)
    with state._lock:
        slot.api_uploads += 1
    is_pdf = filename.lower().endswith(".pdf")
    try:
        if slot.schema_type == "salary_slip":
            parts, notice = _process_slips(slot, pages, metered, ctx, filename, h)
        else:
            parts, notice = _process_single(slot, pages, data if is_pdf else None, metered, ctx, filename, h, quality)
    except BudgetExceeded:
        n = _manual_review_notice("API_BUDGET", "We've reached the checking limit for this application.")
        slot.notice = n
        state.log("budget_exceeded", slot_id)
        return UploadOutcome(slot_id, "blocked", n)

    if notice:
        slot.notice = notice
        slot.file_hashes.append(h)       # the API already ran: same file again would not change the answer
        state.log("rejected_after_api", slot_id, code=notice.code)
        return UploadOutcome(slot_id, "rejected", notice)

    with state._lock:
        if slot.schema_type == "salary_slip":
            for p in parts:
                if p.pages == 0:         # continuation page: already merged into an earlier slip
                    continue
                slot.parts.append(p)
        else:
            slot.parts = parts
            slot.manual_review = False
        slot.pages_used += len(pages) if slot.schema_type == "salary_slip" else 0
        slot.file_hashes.append(h)
        slot.notice = Notice(code="QUALITY_WARNING", severity="warning", message=quality.warnings[0].message,
                             fix_hint=quality.warnings[0].fix_hint) if quality.warnings else None
        recompute(slot, ctx)
    state.log("extracted", slot_id, parts=len(parts))
    say("Done")
    return UploadOutcome(slot_id, "accepted", slot.notice)


def _failed_part(slot: SlotState, name: str, h: str, ctx: RuleContext, error: str | None = None) -> Part:
    print(f"[read-failed] slot={slot.slot_id} error={error}", file=sys.stderr, flush=True)   # visible in the host's logs
    schema = slot.schema_type or next(iter(slot.schema_types.values()))
    fields = validate_fields(schema, {}, ctx)
    for f in fields:
        f.message = f"We couldn't read your {slot.label}. Please enter this."
    return Part(file_name=name, file_hash=h, extraction_failed=True, fields=fields, schema_type=schema, error=error)


def _process_single(slot, pages, pdf_bytes, metered, ctx, name, h, quality):
    out = extract_document(slot.schema_type or next(iter(slot.schema_types.values())), slot.expected_types, pages, metered,
                           pdf_bytes=pdf_bytes, ctx=ctx, schema_map=slot.schema_types or None)
    if out.status == "wrong_document":
        return [], _wrong_doc_notice(slot, out.classification["detected_doc_type"])
    if out.status == "unreadable":
        return [], Notice(code="UNREADABLE_DOC", message=f"We couldn't read this {slot.label}.",
                          fix_hint="Retake the photo in good light with the whole document in view.")
    if out.status == "failed":
        return [_failed_part(slot, name, h, ctx, out.error)], None
    if not out.classification.get("fully_visible", True) and quality.has("CROPPED"):   # both signals agree
        return [], Notice(code="CROPPED", message=f"{slot.label} - part of the document is cut off.",
                          fix_hint="Make sure all four corners are visible in the photo.")
    part = Part(file_name=name, file_hash=h, pages=len(pages), detected_type=out.classification["detected_doc_type"],
                fully_visible=out.classification.get("fully_visible", True), schema_type=out.doc_type,
                fields=out.fields, issues=out.issues, quality_warnings=quality.warnings)
    return [part], None


def _process_slips(slot, pages, metered, ctx, name, h):
    """Each page is read separately. A page with no pay month continues the previous slip."""
    parts: list[Part] = []
    for i, page in enumerate(pages):
        label = f"{name} p{i + 1}"
        out = extract_document("salary_slip", slot.expected_types, [page], metered, ctx=ctx)
        if out.status == "wrong_document":
            return [], _wrong_doc_notice(slot, out.classification["detected_doc_type"])
        if out.status == "unreadable":
            return [], Notice(code="UNREADABLE_DOC", message=f"We couldn't read page {i + 1} of this salary slip.",
                              fix_hint="Retake it in good light with the whole page in view.")
        if out.status == "failed":
            parts.append(_failed_part(slot, label, h, ctx, out.error))
            continue
        pay = next(f for f in out.fields if f.key == "pay_month")
        prev = parts[-1] if parts else (slot.parts[-1] if slot.parts else None)
        if pay.raw_value is None and prev is not None:        # continuation: no month printed on this page
            _merge_continuation(prev, out.fields)
            parts.append(Part(file_name=label, file_hash=h, pages=0))
            continue
        parts.append(Part(file_name=label, file_hash=h, pages=1, detected_type="salary_slip", schema_type="salary_slip",
                          fields=out.fields, issues=out.issues))
    return parts, None


def process_many(state: ApplicationState, jobs: list[tuple[str, str, bytes]], extractor,
                 on_progress: Progress | None = None, ctx: RuleContext | None = None,
                 store=None) -> list[UploadOutcome]:
    """Process several (slot_id, filename, bytes) uploads in parallel; the Sarvam limiter paces them."""
    ctx = ctx or make_context()
    workers = get_policy().limits.parallel_workers
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futs = [pool.submit(process_upload, state, sid, fn, data, extractor, on_progress, ctx, store) for sid, fn, data in jobs]
        return [f.result() for f in futs]


# ---- corrections & slot management --------------------------------------------------------------

def submit_correction(state: ApplicationState, slot_id: str, part_index: int, key: str, value: str,
                      ctx: RuleContext | None = None) -> FieldResult:
    """Validate a typed value with the same rules. 3 failed attempts -> NEEDS_MANUAL_REVIEW."""
    ctx = ctx or make_context()
    slot = state.slots[slot_id]
    part = slot.parts[part_index]
    idx = next(i for i, f in enumerate(part.fields) if f.key == key)
    old = part.fields[idx]
    if old.status == FieldStatus.NEEDS_MANUAL_REVIEW:
        return old
    new = revalidate_user_value(slot.schema_for(part), key, value, ctx)
    new.attempts = old.attempts + (0 if new.status == FieldStatus.USER_ENTERED_VALID else 1)
    new.user_corrected = old.status in _OK or old.user_corrected
    if new.status != FieldStatus.USER_ENTERED_VALID and new.attempts >= get_policy().retries.max_field_attempts:
        new.status = FieldStatus.NEEDS_MANUAL_REVIEW
        new.message = "We couldn't verify this value. It will be checked by a person, so you can continue."
    part.fields[idx] = new
    part.extraction_failed = False if new.status == FieldStatus.USER_ENTERED_VALID else part.extraction_failed
    recompute(slot, ctx)
    state.log("user_edit", slot_id, field=key, result=new.status.value)
    return new


def request_manual_review(state: ApplicationState, slot_id: str) -> None:
    """The user can't provide a value (or the circuit breaker tripped): flag the slot for a person."""
    slot = state.slots[slot_id]
    for p in slot.parts:
        for i, f in enumerate(p.fields):
            if f.status not in _OK:
                p.fields[i] = f.model_copy(update={"status": FieldStatus.NEEDS_MANUAL_REVIEW})
    slot.manual_review = True
    slot.notice = None
    state.log("manual_review_requested", slot_id)


def clear_slot(state: ApplicationState, slot_id: str) -> None:
    """Re-upload: wipe this document's results only. The API-upload counter is kept on purpose."""
    slot = state.slots[slot_id]
    slot.parts, slot.set_issues, slot.notice = [], [], None
    slot.file_hashes, slot.pages_used, slot.manual_review = [], 0, False
    state.log("slot_cleared", slot_id)


def remove_part(state: ApplicationState, slot_id: str, part_index: int, ctx: RuleContext | None = None) -> None:
    """Remove one salary slip so a replacement can be uploaded."""
    slot = state.slots[slot_id]
    part = slot.parts.pop(part_index)
    slot.pages_used = max(0, slot.pages_used - max(part.pages, 1))
    if not any(p.file_hash == part.file_hash for p in slot.parts) and part.file_hash in slot.file_hashes:
        slot.file_hashes.remove(part.file_hash)
    slot.notice = None
    recompute(slot, ctx or make_context())
