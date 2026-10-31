"""Field-level rules. Pure functions: (normalised value, context) -> RuleResult.

The same rules run on extracted values and on values the user types in.
"""
import re
import unicodedata
from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from core.config.loader import Policy, get_policy, get_schema_fields
from core.models import FieldResult, FieldStatus, RuleResult
from core.utils.dates import reference_date
from core.validation import verhoeff
from core.validation.normalize import normalize_value, parse_date, parse_pay_month


@dataclass
class RuleContext:
    today: date
    policy: Policy


def make_context(today: date | None = None) -> RuleContext:
    return RuleContext(today=today or reference_date(), policy=get_policy())


def _ok(rule_id: str) -> RuleResult:
    return RuleResult(ok=True, rule_id=rule_id)


def _fail(rule_id: str, msg: str, severity="error") -> RuleResult:
    return RuleResult(ok=False, rule_id=rule_id, severity=severity, message=msg)


def pan_format(v, ctx):
    if re.fullmatch(r"[A-Z]{5}[0-9]{4}[A-Z]", v):
        return _ok("PAN_FORMAT")
    return _fail("PAN_FORMAT", "A PAN has 5 letters, then 4 digits, then 1 letter (for example ABCDE1234F).")


def pan_individual(v, ctx):
    if len(v) == 10 and v[3] != "P":
        return _fail("PAN_INDIVIDUAL", "The 4th character of an individual's PAN is usually 'P'. Please check it.", "warning")
    return _ok("PAN_INDIVIDUAL")


def aadhaar_format(v, ctx):
    if re.fullmatch(r"[2-9][0-9]{11}", v):
        return _ok("AADHAAR_FORMAT")
    return _fail("AADHAAR_FORMAT", "An Aadhaar number has 12 digits and does not start with 0 or 1.")


def aadhaar_checksum(v, ctx):
    if v.isdigit() and verhoeff.is_valid(v):
        return _ok("AADHAAR_CHECKSUM")
    return _fail("AADHAAR_CHECKSUM", "This Aadhaar number does not pass the check-digit test. One digit is probably wrong.")


def ifsc_format(v, ctx):
    if re.fullmatch(r"[A-Z]{4}0[A-Z0-9]{6}", v):
        return _ok("IFSC_FORMAT")
    return _fail("IFSC_FORMAT", "An IFSC has 4 letters, the digit 0, then 6 letters or digits (for example HDFC0001234).")


def account_no(v, ctx):
    if re.fullmatch(r"[0-9]{9,18}", v):
        return _ok("ACCOUNT_NO")
    return _fail("ACCOUNT_NO", "An account number has 9 to 18 digits. If your statement masks it, type the full number.")


def pincode(v, ctx):
    if re.fullmatch(r"[1-9][0-9]{5}", v):
        return _ok("PINCODE")
    return _fail("PINCODE", "A pincode has 6 digits and does not start with 0.")


def date_valid(v, ctx):
    if parse_date(v):
        return _ok("DATE_VALID")
    return _fail("DATE_VALID", "This is not a valid date. Use DD/MM/YYYY.")


def dob_valid(v, ctx):
    d = parse_date(v)
    if not d:
        return _fail("DOB_VALID", "This is not a valid date. Use DD/MM/YYYY.")
    if d > ctx.today:
        return _fail("DOB_VALID", "Date of birth cannot be in the future.")
    return _ok("DOB_VALID")


def _age(d: date, today: date) -> int:
    return today.year - d.year - ((today.month, today.day) < (d.month, d.day))


def age_range(v, ctx):
    d = parse_date(v)
    if not d or d > ctx.today:
        return _ok("AGE_RANGE")  # DOB_VALID reports it
    a, p = _age(d, ctx.today), ctx.policy.applicant
    if a < p.min_age:
        return _fail("AGE_RANGE", f"You must be at least {p.min_age} years old to apply.")
    if not p.preferred_age_min <= a <= p.preferred_age_max:
        return _fail("AGE_RANGE", f"Applicants are usually between {p.preferred_age_min} and "
                                  f"{p.preferred_age_max} years old, so this application may need extra review.", "warning")
    return _ok("AGE_RANGE")


def name_valid(v, ctx):
    # Letters (any script, including combining vowel marks), spaces and . ' - only.
    letters = sum(1 for c in v if c.isalpha())
    clean = all(c.isalpha() or unicodedata.category(c).startswith("M") or c in " .'-" for c in v)
    if letters >= 2 and clean:
        return _ok("NAME_VALID")
    return _fail("NAME_VALID", "A name can only contain letters, spaces and . ' - (at least 2 letters).")


def amount_positive(v, ctx):
    try:
        if Decimal(v) > 0:
            return _ok("AMOUNT_POSITIVE")
    except Exception:
        pass
    return _fail("AMOUNT_POSITIVE", "Enter the amount as a number greater than zero, for example 45000.")


def doc_date_not_future(v, ctx):
    d = parse_date(v)
    if d and d > ctx.today:
        return _fail("DOC_DATE_NOT_FUTURE", "This date is in the future. Please check it.")
    return _ok("DOC_DATE_NOT_FUTURE")


def pay_month_valid(v, ctx):
    ym = parse_pay_month(v) if not re.fullmatch(r"\d{4}-\d{2}", v) else (int(v[:4]), int(v[5:]))
    if not ym or not 1 <= ym[1] <= 12:
        return _fail("PAY_MONTH_VALID", "Enter the salary month like 'September 2026'.")
    return _ok("PAY_MONTH_VALID")


RULES = {f.__name__.upper(): f for f in (
    pan_format, pan_individual, aadhaar_format, aadhaar_checksum, ifsc_format, account_no, pincode,
    date_valid, dob_valid, age_range, name_valid, amount_positive, doc_date_not_future, pay_month_valid)}


def validate_value(key: str, ftype: str, validators: list[str], raw, ctx: RuleContext) -> tuple[str | None, RuleResult | None, list[RuleResult]]:
    """Normalise then run rules. Returns (normalised, first blocking failure, warnings)."""
    norm = normalize_value(key, ftype, raw)
    if norm is None:
        return None, None, []
    warnings = []
    for rid in validators:
        res = RULES[rid](norm, ctx)
        if not res.ok:
            if res.severity == "error":
                return norm, res, warnings
            warnings.append(res)
    return norm, None, warnings


def validate_fields(doc_type: str, raw: dict, ctx: RuleContext | None = None) -> list[FieldResult]:
    ctx = ctx or make_context()
    out = []
    for f in get_schema_fields(doc_type):
        raw_v = raw.get(f["key"])
        raw_s = None if raw_v is None else str(raw_v)
        fr = FieldResult(key=f["key"], label=f["label"], raw_value=raw_s, required=f.get("required", True))
        norm, failure, warnings = validate_value(f["key"], f["type"], f.get("validators", []), raw_v, ctx)
        if norm is None:
            fr.message = f"We couldn't read the {f['label'].lower()}. Please enter it."
            fr.status = FieldStatus.NOT_EXTRACTED
        else:
            fr.normalized_value = norm
            if failure:
                fr.status, fr.failed_rule_id, fr.message = FieldStatus.INVALID, failure.rule_id, failure.message
            else:
                fr.status = FieldStatus.VALID
                if warnings:
                    fr.warning = warnings[0].message
        out.append(fr)
    return out


def revalidate_user_value(doc_type: str, key: str, value: str, ctx: RuleContext | None = None) -> FieldResult:
    """The same rules, applied to a user-typed value."""
    ctx = ctx or make_context()
    f = next(x for x in get_schema_fields(doc_type) if x["key"] == key)
    norm, failure, warnings = validate_value(key, f["type"], f.get("validators", []), value, ctx)
    fr = FieldResult(key=key, label=f["label"], raw_value=value, normalized_value=norm,
                     required=f.get("required", True), source="user")
    if norm is None:
        fr.status, fr.message = FieldStatus.NOT_EXTRACTED, "Please enter a value."
    elif failure:
        fr.status, fr.failed_rule_id, fr.message = FieldStatus.INVALID, failure.rule_id, failure.message
    else:
        fr.status = FieldStatus.USER_ENTERED_VALID
        fr.warning = warnings[0].message if warnings else None
    return fr
