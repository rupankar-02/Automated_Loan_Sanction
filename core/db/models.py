"""SQLite schema (plan.md section 12). Sensitive values are protected before they reach these tables:
Aadhaar/account numbers masked in raw_value and normalized_value, PAN encrypted with a keyed hash."""
from datetime import datetime, timezone

from sqlalchemy import ForeignKey, Integer, String, Text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Base(DeclarativeBase):
    pass


class ApplicationRow(Base):
    __tablename__ = "applications"
    id: Mapped[str] = mapped_column(String, primary_key=True)
    loan_type: Mapped[str] = mapped_column(String)
    employment: Mapped[str] = mapped_column(String)
    status: Mapped[str] = mapped_column(String)          # draft|docs_pending|review|saved|kyc_started|kyc_done
    consent_at: Mapped[datetime | None] = mapped_column(nullable=True)
    created_at: Mapped[datetime] = mapped_column(default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(default=utcnow)


class DocumentRow(Base):
    __tablename__ = "documents"
    id: Mapped[str] = mapped_column(String, primary_key=True)
    application_id: Mapped[str] = mapped_column(ForeignKey("applications.id"))
    slot_id: Mapped[str] = mapped_column(String)
    part_index: Mapped[int] = mapped_column(Integer, default=0)
    doc_type: Mapped[str] = mapped_column(String)         # expected type (schema key)
    detected_type: Mapped[str | None] = mapped_column(String, nullable=True)
    file_name: Mapped[str | None] = mapped_column(String, nullable=True)
    file_hash: Mapped[str | None] = mapped_column(String, nullable=True)
    page_count: Mapped[int] = mapped_column(Integer, default=1)
    quality_status: Mapped[str] = mapped_column(String)   # passed|warning
    quality_report: Mapped[str | None] = mapped_column(Text, nullable=True)   # JSON, issue codes only
    status: Mapped[str] = mapped_column(String)           # extracted|extraction_failed|verified
    storage_path: Mapped[str | None] = mapped_column(String, nullable=True)   # null once originals are purged
    uploaded_at: Mapped[datetime] = mapped_column(default=utcnow)


class FieldRow(Base):
    __tablename__ = "extracted_fields"
    id: Mapped[str] = mapped_column(String, primary_key=True)
    application_id: Mapped[str] = mapped_column(ForeignKey("applications.id"))
    document_id: Mapped[str] = mapped_column(ForeignKey("documents.id"))
    field_key: Mapped[str] = mapped_column(String)
    raw_value: Mapped[str | None] = mapped_column(Text, nullable=True)           # protected (see core/utils/pii.py)
    normalized_value: Mapped[str | None] = mapped_column(Text, nullable=True)    # protected
    value_hmac: Mapped[str | None] = mapped_column(String, nullable=True)        # PAN match key
    source: Mapped[str] = mapped_column(String)           # vlm|user
    status: Mapped[str] = mapped_column(String)
    failed_rule_id: Mapped[str | None] = mapped_column(String, nullable=True)
    message: Mapped[str | None] = mapped_column(Text, nullable=True)
    user_corrected: Mapped[int] = mapped_column(Integer, default=0)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    updated_at: Mapped[datetime] = mapped_column(default=utcnow)


class ValidationRow(Base):
    __tablename__ = "validation_results"
    id: Mapped[str] = mapped_column(String, primary_key=True)
    application_id: Mapped[str] = mapped_column(ForeignKey("applications.id"))
    document_id: Mapped[str | None] = mapped_column(String, nullable=True)
    scope: Mapped[str] = mapped_column(String)            # field|document|set|cross_doc
    rule_id: Mapped[str] = mapped_column(String)
    severity: Mapped[str] = mapped_column(String)
    passed: Mapped[int] = mapped_column(Integer)
    details: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(default=utcnow)


class AuditRow(Base):
    """No foreign key on purpose: the deletion record must outlive the application's data."""
    __tablename__ = "audit_events"
    id: Mapped[str] = mapped_column(String, primary_key=True)
    application_id: Mapped[str] = mapped_column(String, index=True)
    event_type: Mapped[str] = mapped_column(String)
    payload: Mapped[str | None] = mapped_column(Text, nullable=True)   # JSON; ids and codes only, never PII values
    created_at: Mapped[datetime] = mapped_column(default=utcnow)


class KycRow(Base):
    __tablename__ = "kyc_sessions"
    id: Mapped[str] = mapped_column(String, primary_key=True)
    application_id: Mapped[str] = mapped_column(ForeignKey("applications.id"))
    method: Mapped[str] = mapped_column(String)
    status: Mapped[str] = mapped_column(String)
    details: Mapped[str | None] = mapped_column(Text, nullable=True)
    started_at: Mapped[datetime] = mapped_column(default=utcnow)
    completed_at: Mapped[datetime | None] = mapped_column(nullable=True)


class OfferRunRow(Base):
    __tablename__ = "offer_runs"
    id: Mapped[str] = mapped_column(String, primary_key=True)          # run_id
    application_id: Mapped[str] = mapped_column(ForeignKey("applications.id"))
    catalog_version: Mapped[str] = mapped_column(String)
    inputs_json: Mapped[str] = mapped_column(Text)                     # amount, tenure, EMIs, score + derived facts; source=user
    results_json: Mapped[str] = mapped_column(Text)                    # evaluations, suggestions, scenario grids
    created_at: Mapped[datetime] = mapped_column(default=utcnow)


class ChatSessionRow(Base):
    __tablename__ = "chat_sessions"
    id: Mapped[str] = mapped_column(String, primary_key=True)
    application_id: Mapped[str] = mapped_column(ForeignKey("applications.id"))
    lang: Mapped[str] = mapped_column(String, default="en")
    created_at: Mapped[datetime] = mapped_column(default=utcnow)


class ChatMessageRow(Base):
    __tablename__ = "chat_messages"
    id: Mapped[str] = mapped_column(String, primary_key=True)
    session_id: Mapped[str] = mapped_column(ForeignKey("chat_sessions.id"))
    role: Mapped[str] = mapped_column(String)                          # user | assistant | system_note
    content: Mapped[str] = mapped_column(Text)
    run_id: Mapped[str | None] = mapped_column(String, nullable=True)
    context_hash: Mapped[str | None] = mapped_column(String, nullable=True)   # hash only, never a copy of the context
    verification: Mapped[str | None] = mapped_column(String, nullable=True)   # passed|regenerated|fallback_template|blocked
    feedback: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(default=utcnow)


class SelectedOfferRow(Base):
    __tablename__ = "selected_offer"
    application_id: Mapped[str] = mapped_column(ForeignKey("applications.id"), primary_key=True)
    offer_id: Mapped[str] = mapped_column(String)
    run_id: Mapped[str] = mapped_column(String)
    selected_at: Mapped[datetime] = mapped_column(default=utcnow)
