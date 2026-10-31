"""Classify + extract + validate one document. The model extracts; the rules decide."""
from dataclasses import dataclass, field
from typing import Literal

import pymupdf
from PIL import Image

from core.config.loader import get_schema_fields
from core.errors import BudgetExceeded
from core.models import DocIssue, FieldResult
from core.validation.doc_rules import apply_document_rules
from core.validation.field_rules import RuleContext, make_context, validate_fields


@dataclass
class ExtractionOutcome:
    status: Literal["ok", "wrong_document", "unreadable", "failed"]
    classification: dict = field(default_factory=dict)
    fields: list[FieldResult] = field(default_factory=list)
    issues: list[DocIssue] = field(default_factory=list)
    doc_type: str | None = None
    error: str | None = None


def get_extractor():
    from core.config.settings import get_settings
    if get_settings().use_mock_vlm:
        from core.vlm.fake import FakeExtractor
        return FakeExtractor()
    from core.vlm.roles import LiveExtractor
    return LiveExtractor()


def prepare_pdf(doc_type: str, data: bytes, max_pages: int = 20) -> bytes:
    """Bank statements: send only the first and last page (header fields + closing balance)."""
    doc = pymupdf.open(stream=data, filetype="pdf")
    if doc_type == "bank_statement" and doc.page_count > 2:
        keep = [0, doc.page_count - 1]
    elif doc.page_count > max_pages:
        keep = list(range(max_pages))
    else:
        return data
    out = pymupdf.open()
    for i in keep:
        out.insert_pdf(doc, from_page=i, to_page=i)
    return out.tobytes()


def extract_document(doc_type: str, expected_types: list[str], pages: list[Image.Image],
                     extractor, *, pdf_bytes: bytes | None = None, ctx: RuleContext | None = None,
                     schema_map: dict[str, str] | None = None) -> ExtractionOutcome:
    """doc_type selects the schema; expected_types are the classifier labels that are acceptable."""
    ctx = ctx or make_context()
    try:
        cls = extractor.classify(pages)
    except BudgetExceeded:
        raise
    except Exception as e:
        # The type check is a safety extra. If every model is busy, read the document anyway: the field rules
        # still catch a wrong document (nothing extracts, or the values fail validation).
        cls = {"detected_doc_type": expected_types[0], "fully_visible": True, "legibility": "fair",
               "unchecked": f"{type(e).__name__}"}
    detected = cls["detected_doc_type"]
    if detected == "unreadable":
        return ExtractionOutcome(status="unreadable", classification=cls)
    if detected not in expected_types:
        return ExtractionOutcome(status="wrong_document", classification=cls)

    if schema_map:                                  # e.g. 'Form 16 or ITR': the detected type picks the schema
        doc_type = schema_map[detected]
    schema = get_schema_fields(doc_type)
    src_pdf = prepare_pdf(doc_type, pdf_bytes) if pdf_bytes else None
    raw, error = None, None
    for _attempt in range(2):                       # one automatic retry: reads fail now and then
        try:
            raw = extractor.extract(schema, pages=pages, pdf_bytes=src_pdf, doc_type=doc_type)
            break
        except BudgetExceeded:
            raise
        except Exception as e:
            error = f"{type(e).__name__}: {str(e)[:120]}"
    if raw is None:
        return ExtractionOutcome(status="failed", classification=cls, error=error)

    fields = validate_fields(doc_type, raw, ctx)
    return ExtractionOutcome(status="ok", classification=cls, fields=fields, doc_type=doc_type,
                             issues=apply_document_rules(doc_type, fields, ctx))
