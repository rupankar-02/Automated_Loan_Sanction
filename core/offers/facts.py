"""Derive the applicant's facts from the saved application, and validate the 'a few more details' form."""
from decimal import Decimal

from core.config.loader import get_policy  # noqa: F401  (kept for symmetry with other modules)
from core.models import FieldStatus
from core.offers.catalog import Catalog, get_catalog
from core.offers.models import Facts, LoanRequest
from core.state import ApplicationState, slot_status
from core.utils.dates import reference_date
from core.validation.normalize import parse_date

_OK = {FieldStatus.VALID, FieldStatus.USER_ENTERED_VALID}
INCOME_VARIATION = 0.15            # warn if any month's net pay differs from the average by more than this


def _field(state: ApplicationState, slot_id: str, key: str):
    slot = state.slots.get(slot_id)
    for p in (slot.parts if slot else []):
        for f in p.fields:
            if f.key == key and f.status in _OK and f.normalized_value:
                return f
    return None


def _age(dob_iso: str, today) -> int | None:
    d = parse_date(dob_iso)
    return None if d is None else today.year - d.year - ((today.month, today.day) < (d.month, d.day))


def verified_documents(state: ApplicationState) -> list[str]:
    ok = lambda sid: sid in state.slots and state.slots[sid].parts and slot_status(state.slots[sid]) == "verified"  # noqa: E731
    docs = []
    if ok("pan"):
        docs.append("pan")
    if ok("aadhaar_front") and ok("aadhaar_back"):
        docs.append("aadhaar")
    if ok("salary_slip"):
        docs.append("salary_slip")
    if ok("bank_statement"):
        docs.append("bank_statement")
    if ok("form16_or_itr"):
        docs.append("form16")                        # a Form 16 or an ITR both count
    return docs


def derive_net_income(state: ApplicationState) -> tuple[float, bool]:
    """Average net salary over the validated slips; flag a month that deviates more than 15%."""
    slot = state.slots.get("salary_slip")
    nets = [Decimal(f.normalized_value) for p in (slot.parts if slot else []) for f in p.fields
            if f.key == "net_salary" and f.status in _OK and f.normalized_value]
    if not nets:
        return 0.0, False
    avg = sum(nets) / len(nets)
    warn = any(abs(n - avg) / avg > Decimal(str(INCOME_VARIATION)) for n in nets) if avg else False
    return float(avg), warn


def derive_facts(state: ApplicationState, *, existing_emi: float = 0.0, credit_score: int | None = None) -> Facts:
    name = _field(state, "pan", "name") or _field(state, "aadhaar_front", "name")
    dob = _field(state, "pan", "dob") or _field(state, "aadhaar_front", "dob")
    income, warn = derive_net_income(state)
    return Facts(
        first_name=name.normalized_value.split()[0].title() if name else None,
        age=(_age(dob.normalized_value, reference_date()) if dob else None) or 0,
        employment=state.employment or "salaried", net_monthly_income=round(income), income_variation_warning=warn,
        existing_emi=existing_emi, credit_score=credit_score, documents_verified=verified_documents(state))


def validate_inputs(amount, tenure, existing_emi, score, catalog: Catalog | None = None) -> tuple[dict, dict]:
    """Returns (clean values, errors by field). Nothing is accepted silently."""
    catalog = catalog or get_catalog()
    lo, hi = catalog.amount_bounds
    t = catalog.inputs["tenure_months"]
    s = catalog.inputs["score"]
    errors, clean = {}, {}

    def num(v):
        try:
            return float(str(v).replace(",", "").strip())
        except (TypeError, ValueError):
            return None

    a = num(amount)
    if a is None or a <= 0:
        errors["amount"] = "Enter the loan amount as a number greater than zero."
    elif not lo <= a <= hi:
        errors["amount"] = f"Loan amounts in this demo are between {int(lo):,} and {int(hi):,}."
    else:
        clean["amount"] = a
    n = num(tenure)
    if n is None or n != int(n) or not t["min"] <= n <= t["max"]:
        errors["tenure_months"] = f"Enter the tenure in whole months, between {t['min']} and {t['max']}."
    else:
        clean["tenure_months"] = int(n)
    e = num(existing_emi if str(existing_emi).strip() != "" else 0)
    if e is None or e < 0:
        errors["existing_emi"] = "Enter your total monthly EMIs (0 if none)."
    else:
        clean["existing_emi"] = e
    if score is None or str(score).strip().lower() in ("", "unknown", "none"):
        clean["credit_score"] = None
    else:
        sc = num(score)
        if sc is None or sc != int(sc) or not s["min"] <= sc <= s["max"]:
            errors["credit_score"] = f"A credit score is a whole number between {s['min']} and {s['max']}, or choose I don't know."
        else:
            clean["credit_score"] = int(sc)
    return clean, errors


def make_request(clean: dict, purpose: str | None = None) -> LoanRequest:
    return LoanRequest(amount=clean["amount"], tenure_months=clean["tenure_months"], purpose=(purpose or None))
