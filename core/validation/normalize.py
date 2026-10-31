"""Normalise raw extracted text: IDs upper-cased, dates -> ISO, amounts -> plain numbers."""
import re
from datetime import date, datetime
from decimal import Decimal, InvalidOperation

MONTHS = {m: i for i, m in enumerate(
    ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"], 1)}

_DATE_FORMATS = ["%d/%m/%Y", "%d-%m-%Y", "%d.%m.%Y", "%Y-%m-%d", "%Y/%m/%d",
                 "%d %b %Y", "%d %B %Y", "%d-%b-%Y", "%d-%B-%Y", "%d %b, %Y", "%b %d, %Y", "%B %d, %Y"]

ID_KEYS = {"pan_number", "employee_pan", "pan", "ifsc"}
DIGIT_KEYS = {"aadhaar_number", "account_number", "pincode"}
DATE_KEYS = {"dob", "statement_from", "statement_to"}


def parse_date(s: str) -> date | None:
    s = re.sub(r"\s+", " ", s.strip())
    for fmt in _DATE_FORMATS:
        try:
            return datetime.strptime(s, fmt).date()
        except ValueError:
            continue
    return None


def parse_amount(s: str) -> Decimal | None:
    neg = s.strip().startswith("-") or (s.strip().startswith("(") and s.strip().endswith(")"))
    cleaned = re.sub(r"[^\d.]", "", s)
    if not cleaned or cleaned.count(".") > 1 or cleaned == ".":
        return None
    try:
        v = Decimal(cleaned)
    except InvalidOperation:
        return None
    return -v if neg else v


def parse_pay_month(s: str) -> tuple[int, int] | None:
    """'September 2026', 'Sep-26', 'Sep 2026', '09/2026', '2026-09' -> (2026, 9)."""
    t = re.sub(r"\s+", " ", s.strip().lower())
    m = re.fullmatch(r"([a-z]{3,9})[\s\-/,.]*(\d{4}|\d{2})", t)
    if m and m.group(1)[:3] in MONTHS:
        return _year(m.group(2)), MONTHS[m.group(1)[:3]]
    m = re.fullmatch(r"(\d{1,2})[\s\-/.](\d{4}|\d{2})", t)
    if m and 1 <= int(m.group(1)) <= 12:
        return _year(m.group(2)), int(m.group(1))
    m = re.fullmatch(r"(\d{4})[\s\-/.](\d{1,2})", t)
    if m and 1 <= int(m.group(2)) <= 12:
        return int(m.group(1)), int(m.group(2))
    return None


def _year(y: str) -> int:
    return int(y) if len(y) == 4 else 2000 + int(y)


def fmt_month(ym: tuple[int, int]) -> str:
    return f"{ym[0]:04d}-{ym[1]:02d}"


def parse_month_str(s: str) -> tuple[int, int]:
    y, m = s.split("-")
    return int(y), int(m)


def normalize_value(key: str, ftype: str, raw) -> str | None:
    """Return the normalised string, or None if empty. Unparseable values are returned
    cleaned-but-unchanged so format rules can reject them (pay_month is the exception: None)."""
    if raw is None:
        return None
    s = str(raw).strip()
    if s.lower() in {"", "n/a", "na", "-", "null", "none"}:
        return None
    if key in ID_KEYS:
        return re.sub(r"[\s\-]", "", s).upper()
    if key in DIGIT_KEYS:
        return re.sub(r"[\s\-]", "", s)
    if key in DATE_KEYS:
        d = parse_date(s)
        return d.isoformat() if d else s
    if key == "pay_month":
        ym = parse_pay_month(s)
        return fmt_month(ym) if ym else None
    if ftype == "number":
        v = parse_amount(s)
        return format(v, "f") if v is not None else s
    return re.sub(r"\s+", " ", s)
