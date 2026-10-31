"""Synthetic demo applicants, so the offers and chatbot demo does not depend on live document extraction.

Each profile builds a fully verified, saved application (no API calls) with fictional data only.
"""
from dataclasses import dataclass
from datetime import date, datetime, timezone

from core.db.repo import Repo
from core.models import FieldResult, FieldStatus
from core.pipeline import recompute
from core.save import confirm_and_save
from core.state import ApplicationState, Part, new_application
from core.utils.dates import reference_date
from core.validation import verhoeff
from core.validation.field_rules import make_context
from core.validation.months import range_label, required_window, window_bounds


@dataclass(frozen=True)
class DemoProfile:
    key: str
    title: str
    blurb: str
    name: str
    birth_year: int
    net_pay: tuple[int, int, int]        # three monthly net salaries
    form16: bool
    existing_emi: int
    credit_score: int | None
    amount: int
    tenure: int


PROFILES = {
    "strong": DemoProfile("strong", "Strong profile", "High income, good score, Form 16 provided: most offers open.",
                          "Rahul Sharma", 1992, (96000, 95000, 97000), True, 5000, 780, 400000, 36),
    "borderline": DemoProfile("borderline", "Borderline profile", "Premium is just out of reach: ask the assistant why.",
                              "Priya Nair", 1995, (52000, 53000, 52200), False, 8000, 720, 400000, 36),
    "low_income": DemoProfile("low_income", "Low-income profile", "Only small-ticket options open up.",
                              "Amit Verma", 1998, (18000, 18500, 17800), False, 0, None, 50000, 12),
}


def _f(key, label, value, req=True) -> FieldResult:
    return FieldResult(key=key, label=label, raw_value=str(value), normalized_value=str(value),
                       status=FieldStatus.VALID, required=req)


def _set(state: ApplicationState, slot_id: str, fields_per_part: list[list[FieldResult]], schema: str, name: str) -> None:
    slot = state.slots[slot_id]
    slot.parts = [Part(file_name=f"{name}-{i + 1}.demo", file_hash=f"demo-{slot_id}-{i}", fields=fields, schema_type=schema,
                       detected_type=schema) for i, fields in enumerate(fields_per_part)]
    slot.pages_used = len(slot.parts) if slot_id == "salary_slip" else 0


def build_demo_state(profile: DemoProfile, today: date | None = None) -> ApplicationState:
    today = today or reference_date()
    ctx = make_context(today)
    state = new_application("personal", "salaried")
    state.consent_at = datetime.now(timezone.utc)
    pan_no = "ABCPE1234F" if profile.key == "strong" else ("PQRPS5678K" if profile.key == "borderline" else "LMNPV9012T")
    first, last = profile.name.upper().split()[0], profile.name.upper()
    dob = f"{profile.birth_year}-06-15"
    aadhaar = "23456789012" + verhoeff.check_digit("23456789012")
    window = required_window(today, ctx.policy)
    w_start, w_end = window_bounds(window)

    _set(state, "pan", [[_f("pan_number", "PAN number", pan_no), _f("name", "Name", last), _f("dob", "Date of birth", dob),
                         _f("father_name", "Father's name", "DEMO FATHER", False)]], "pan", "pan")
    _set(state, "aadhaar_front", [[_f("name", "Name", last), _f("dob", "Date of birth", dob),
                                   _f("aadhaar_number", "Aadhaar number", aadhaar)]], "aadhaar_front", "aadhaar-front")
    _set(state, "aadhaar_back", [[_f("address", "Address", "12 Demo Street, Bengaluru"), _f("pincode", "Pincode", "560001")]],
         "aadhaar_back", "aadhaar-back")
    slips = []
    for (y, m), net in zip(window, profile.net_pay):
        slips.append([_f("employee_name", "Employee name", last), _f("employer_name", "Employer name", "DEMO TECHNOLOGIES"),
                      _f("pay_month", "Pay month", f"{y:04d}-{m:02d}"), _f("gross_salary", "Gross salary", round(net * 1.18)),
                      _f("net_salary", "Net salary", net), _f("total_deductions", "Total deductions", round(net * 0.18), False)])
    _set(state, "salary_slip", slips, "salary_slip", "slip")
    _set(state, "bank_statement", [[_f("account_holder_name", "Account holder", last), _f("bank_name", "Bank name", "Demo Bank"),
                                    _f("account_number", "Account number", "123456789012"), _f("ifsc", "IFSC", "DEMO0001234"),
                                    _f("statement_from", "Statement from", w_start.isoformat()),
                                    _f("statement_to", "Statement to", w_end.isoformat())]], "bank_statement", "statement")
    if profile.form16:
        _set(state, "form16_or_itr", [[_f("employee_name", "Employee name", last), _f("employee_pan", "Employee PAN", pan_no),
                                       _f("employer_name", "Employer name", "DEMO TECHNOLOGIES"), _f("financial_year", "Financial year", "2025-26"),
                                       _f("gross_salary", "Gross salary", sum(profile.net_pay) * 4)]], "form16", "form16")
    for slot in state.slots.values():
        recompute(slot, ctx)
    state.log("demo_profile_loaded", profile=profile.key)
    return state


def load_demo_application(profile_key: str, repo: Repo) -> tuple[ApplicationState, DemoProfile]:
    profile = PROFILES[profile_key]
    state = build_demo_state(profile)
    confirm_and_save(state, repo)
    return state, profile


def describe_window(today: date | None = None) -> str:
    return range_label(required_window(today or reference_date(), make_context(today).policy))
