"""Persistence. Every write goes through core.utils.pii.protect_value, so nothing sensitive is stored in full
except the encrypted PAN."""
import json
import uuid
from datetime import datetime, timezone

from sqlalchemy import create_engine, delete, select, text
from sqlalchemy.orm import Session, sessionmaker

from core.config.loader import get_schema_fields
from core.config.settings import get_settings
from core.db.models import (ApplicationRow, AuditRow, Base, ChatMessageRow, ChatSessionRow, DocumentRow,
                            FieldRow, KycRow, OfferRunRow, SelectedOfferRow, ValidationRow)
from core.models import FieldStatus
from core.offers.models import OfferRun
from core.state import ApplicationState, Part, slot_status
from core.storage import FileStore
from core.utils.crypto import FieldCipher
from core.utils.pii import ENCRYPTED_KEYS, mask_pan, protect_value

_OK = {FieldStatus.VALID.value, FieldStatus.USER_ENTERED_VALID.value}


def _id() -> str:
    return uuid.uuid4().hex


class Repo:
    def __init__(self, url: str | None = None, cipher: FieldCipher | None = None, store: FileStore | None = None):
        if url is None:
            path = get_settings().data_dir / "app.sqlite"
            path.parent.mkdir(parents=True, exist_ok=True)
            url = f"sqlite:///{path.as_posix()}"
        self.engine = create_engine(url, connect_args={"check_same_thread": False})
        Base.metadata.create_all(self.engine)
        self.Session = sessionmaker(self.engine, expire_on_commit=False)
        self.cipher = cipher or FieldCipher()
        self.store = store or FileStore()

    # ---- writes -------------------------------------------------------------------------------

    def sync(self, state: ApplicationState, status: str | None = None) -> None:
        """Make the database match the state. After a save (`scrubbed`) fields are never rewritten."""
        if status:
            state.status = status
        now = datetime.now(timezone.utc)
        with self.Session.begin() as s:
            app = s.get(ApplicationRow, state.app_id)
            if app is None:
                app = ApplicationRow(id=state.app_id, loan_type=state.loan_type or "", employment=state.employment or "",
                                     status=state.status, consent_at=state.consent_at, created_at=now, updated_at=now)
                s.add(app)
                s.flush()
            app.status, app.updated_at = state.status, now
            if not state.scrubbed:
                self._write_children(s, state)
            self._write_events(s, state)

    def _write_children(self, s: Session, state: ApplicationState) -> None:
        for model in (FieldRow, ValidationRow, DocumentRow):
            s.execute(delete(model).where(model.application_id == state.app_id))
        for slot in state.slots.values():
            for pi, part in enumerate(slot.parts):
                if part.pages == 0:                          # continuation page, merged into the previous slip
                    continue
                doc = self._document_row(state, slot, pi, part)
                s.add(doc)
                s.flush()
                for f in part.fields:
                    raw, h = protect_value(f.key, f.raw_value, self.cipher)
                    norm, h2 = protect_value(f.key, f.normalized_value, self.cipher)
                    s.add(FieldRow(id=_id(), application_id=state.app_id, document_id=doc.id, field_key=f.key,
                                   raw_value=raw, normalized_value=norm, value_hmac=h2 or h, source=f.source,
                                   status=f.status.value, failed_rule_id=f.failed_rule_id, message=f.message,
                                   user_corrected=int(f.user_corrected), attempts=f.attempts))
                for i in part.issues:
                    s.add(self._validation_row(state, doc.id, "document", i))
            for i in slot.set_issues:
                s.add(self._validation_row(state, None, "set", i))

    def _document_row(self, state, slot, pi, part: Part) -> DocumentRow:
        path = self.store.path_for(state.app_id, part.file_hash)
        warns = [w.code for w in part.quality_warnings]
        return DocumentRow(
            id=_id(), application_id=state.app_id, slot_id=slot.slot_id, part_index=pi, doc_type=slot.schema_for(part) or slot.slot_id,
            detected_type=part.detected_type, file_name=part.file_name, file_hash=part.file_hash, page_count=part.pages,
            quality_status="warning" if warns else "passed", quality_report=json.dumps({"warnings": warns}),
            status="extraction_failed" if part.extraction_failed else slot_status(slot),
            storage_path=str(path) if path else None)

    @staticmethod
    def _validation_row(state, doc_id, scope, issue) -> ValidationRow:
        return ValidationRow(id=_id(), application_id=state.app_id, document_id=doc_id, scope=scope,
                             rule_id=issue.rule_id, severity=issue.severity, passed=0, details=issue.message)

    @staticmethod
    def _write_events(s: Session, state: ApplicationState) -> None:
        for ev in state.events[state.persisted_events:]:
            payload = {k: v for k, v in ev.items() if k not in ("event", "at")}
            s.add(AuditRow(id=_id(), application_id=state.app_id, event_type=ev["event"], payload=json.dumps(payload),
                           created_at=datetime.fromisoformat(ev["at"])))
        state.persisted_events = len(state.events)

    def clear_storage_paths(self, app_id: str) -> None:
        with self.Session.begin() as s:
            for d in s.scalars(select(DocumentRow).where(DocumentRow.application_id == app_id)):
                d.storage_path = None

    def log(self, app_id: str, event: str, **payload) -> None:
        with self.Session.begin() as s:
            s.add(AuditRow(id=_id(), application_id=app_id, event_type=event, payload=json.dumps(payload)))

    # ---- reads / exports ------------------------------------------------------------------------

    def _decode(self, key: str, value: str | None, reveal: bool) -> str | None:
        if value is None or key not in ENCRYPTED_KEYS:
            return value
        plain = self.cipher.decrypt(value)
        return plain if reveal else mask_pan(plain)

    def export_package(self, app_id: str, mode: str = "user") -> dict:
        """mode='user': PAN masked (default download). mode='lender': full PAN, a separate explicit action."""
        if mode not in ("user", "lender"):
            raise ValueError("mode must be 'user' or 'lender'")
        reveal = mode == "lender"
        with self.Session() as s:
            app = s.get(ApplicationRow, app_id)
            if app is None:
                raise KeyError("Unknown application.")
            docs = list(s.scalars(select(DocumentRow).where(DocumentRow.application_id == app_id)
                                  .order_by(DocumentRow.slot_id, DocumentRow.part_index)))
            fields = list(s.scalars(select(FieldRow).where(FieldRow.application_id == app_id)))
            issues = list(s.scalars(select(ValidationRow).where(ValidationRow.application_id == app_id)))
            sel = s.get(SelectedOfferRow, app_id)
            run_row = s.get(OfferRunRow, sel.run_id) if sel else None
        by_doc: dict[str, list[FieldRow]] = {}
        for f in fields:
            by_doc.setdefault(f.document_id, []).append(f)

        def label(doc_type, key):
            try:
                return next(x["label"] for x in get_schema_fields(doc_type) if x["key"] == key)
            except (KeyError, StopIteration):
                return key

        documents, flat = [], {}
        for d in docs:
            out_fields = []
            for f in by_doc.get(d.id, []):
                val = self._decode(f.field_key, f.normalized_value, reveal)
                out_fields.append({"key": f.field_key, "label": label(d.doc_type, f.field_key), "value": val,
                                   "status": f.status, "source": f.source, "user_corrected": bool(f.user_corrected)})
                if f.status in _OK:
                    flat.setdefault(f.field_key, val)
            documents.append({"slot": d.slot_id, "doc_type": d.doc_type, "file_name": d.file_name, "status": d.status,
                              "quality_status": d.quality_status, "fields": out_fields})
        return {
            "export_mode": mode,
            "application": {"id": app.id, "loan_type": app.loan_type, "employment": app.employment, "status": app.status,
                            "consent_at": app.consent_at.isoformat() if app.consent_at else None},
            "applicant": {"name": flat.get("name") or flat.get("employee_name"), "dob": flat.get("dob"),
                          "pan": flat.get("pan_number"), "aadhaar": flat.get("aadhaar_number")},
            "documents": documents,
            "validation": [{"rule_id": i.rule_id, "severity": i.severity, "scope": i.scope, "message": i.details}
                           for i in issues],
            "manual_review": [f"{d['slot']}:{f['key']}" for d in documents for f in d["fields"]
                              if f["status"] == FieldStatus.NEEDS_MANUAL_REVIEW.value],
            "offer": self._offer_section(sel, run_row),
        }

    @staticmethod
    def _offer_section(sel, run_row) -> dict | None:
        """The selected offer plus the eligibility run behind it (inputs, criteria, catalog version)."""
        if sel is None or run_row is None:
            return None
        run = OfferRun.model_validate_json(run_row.results_json)
        ev = run.evaluation(sel.offer_id)
        return {"selected_offer_id": sel.offer_id, "run_id": run_row.id, "catalog_version": run_row.catalog_version,
                "inputs": json.loads(run_row.inputs_json), "evaluation": ev.model_dump(),
                "selected_at": sel.selected_at.isoformat()}

    def audit_trail(self, app_id: str) -> list[dict]:
        with self.Session() as s:
            rows = s.scalars(select(AuditRow).where(AuditRow.application_id == app_id).order_by(AuditRow.created_at))
            return [{"event": r.event_type, "payload": json.loads(r.payload or "{}"), "at": r.created_at.isoformat()} for r in rows]

    # ---- KYC ----------------------------------------------------------------------------------------

    def save_kyc(self, app_id: str, session_id: str, method: str, status: str, details: dict, completed: bool) -> None:
        with self.Session.begin() as s:
            row = s.get(KycRow, session_id) or KycRow(id=session_id, application_id=app_id, method=method, status=status)
            row.status, row.details = status, json.dumps(details)
            row.completed_at = datetime.now(timezone.utc) if completed else None
            s.merge(row)

    # ---- deletion --------------------------------------------------------------------------------------

    def delete_application(self, app_id: str) -> dict:
        """Delete files, fields (incl. encrypted PAN), validation results, documents and KYC data.
        Leaves one audit row - 'application deleted at T' - with no personal values."""
        files = self.store.purge(app_id)
        with self.Session.begin() as s:
            counts = {}
            sessions = [r for r in s.scalars(select(ChatSessionRow.id).where(ChatSessionRow.application_id == app_id))]
            if sessions:
                counts["chat_messages"] = s.execute(delete(ChatMessageRow).where(ChatMessageRow.session_id.in_(sessions))).rowcount
            for model in (ChatSessionRow, SelectedOfferRow, OfferRunRow, FieldRow, ValidationRow, DocumentRow, KycRow):
                counts[model.__tablename__] = s.execute(delete(model).where(model.application_id == app_id)).rowcount
            s.execute(delete(AuditRow).where(AuditRow.application_id == app_id))
            s.execute(delete(ApplicationRow).where(ApplicationRow.id == app_id))
            s.add(AuditRow(id=_id(), application_id=app_id, event_type="application_deleted", payload="{}"))
        counts["files"] = files
        return counts

    def dump_text(self) -> str:
        """Every stored string, for tests asserting that no PII leaked."""
        with self.engine.connect() as c:
            tables = [r[0] for r in c.execute(text("select name from sqlite_master where type='table'"))]
            out = []
            for t in tables:
                for row in c.execute(text(f'select * from "{t}"')):
                    out.append(" ".join(str(v) for v in row))
            return "\n".join(out)

    # ---- offers and chat ---------------------------------------------------------------------------------

    def save_run(self, app_id: str, run: OfferRun, inputs_extra: dict | None = None) -> None:
        """Persist a run. Inputs are self-declared, so they are recorded with source='user'."""
        inputs = {"source": "user", "request": run.request.model_dump(), "facts": run.facts.model_dump(), **(inputs_extra or {})}
        with self.Session.begin() as s:
            s.merge(OfferRunRow(id=run.run_id, application_id=app_id, catalog_version=run.catalog_version,
                                inputs_json=json.dumps(inputs), results_json=run.model_dump_json()))
        self.log(app_id, "offers_computed", run_id=run.run_id)

    def latest_run(self, app_id: str) -> OfferRun | None:
        with self.Session() as s:
            row = s.scalars(select(OfferRunRow).where(OfferRunRow.application_id == app_id)
                            .order_by(OfferRunRow.created_at.desc())).first()
            return OfferRun.model_validate_json(row.results_json) if row else None

    def select_offer(self, app_id: str, offer_id: str, run_id: str) -> None:
        with self.Session.begin() as s:
            s.merge(SelectedOfferRow(application_id=app_id, offer_id=offer_id, run_id=run_id))
        self.log(app_id, "offer_selected", offer_id=offer_id, run_id=run_id)

    def selected_offer(self, app_id: str) -> str | None:
        with self.Session() as s:
            row = s.get(SelectedOfferRow, app_id)
            return row.offer_id if row else None

    def create_chat_session(self, app_id: str, lang: str = "en") -> str:
        sid = _id()
        with self.Session.begin() as s:
            s.add(ChatSessionRow(id=sid, application_id=app_id, lang=lang))
        return sid

    def add_message(self, session_id: str, role: str, content: str, run_id: str | None = None,
                    context_hash: str | None = None, verification: str | None = None) -> str:
        mid = _id()
        with self.Session.begin() as s:
            s.add(ChatMessageRow(id=mid, session_id=session_id, role=role, content=content, run_id=run_id,
                                 context_hash=context_hash, verification=verification))
        return mid

    def messages(self, session_id: str) -> list[dict]:
        with self.Session() as s:
            rows = s.scalars(select(ChatMessageRow).where(ChatMessageRow.session_id == session_id)
                             .order_by(ChatMessageRow.created_at))
            return [{"id": r.id, "role": r.role, "content": r.content, "run_id": r.run_id,
                     "verification": r.verification, "feedback": r.feedback} for r in rows]

    def set_feedback(self, message_id: str, value: int) -> None:
        with self.Session.begin() as s:
            row = s.get(ChatMessageRow, message_id)
            if row:
                row.feedback = value
