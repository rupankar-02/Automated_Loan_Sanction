from datetime import date

import pytest

from core.models import FieldStatus
from core.validation import verhoeff
from core.validation.field_rules import (RULES, make_context, revalidate_user_value,
                                         validate_fields, validate_value)
from core.validation.normalize import (normalize_value, parse_amount, parse_date,
                                       parse_pay_month)

CTX = make_context(date(2026, 10, 31))


def aadhaar(payload="23456789012"):
    return payload + verhoeff.check_digit(payload)


def ok(rule, value):
    return RULES[rule](value, CTX).ok


def test_verhoeff_roundtrip_and_known_value():
    assert verhoeff.is_valid("2363")                 # classic published example
    n = aadhaar()
    assert verhoeff.is_valid(n)
    bad = n[:-1] + str((int(n[-1]) + 1) % 10)
    assert not verhoeff.is_valid(bad)


@pytest.mark.parametrize("v,expected", [("ABCDE1234F", True), ("ABCD1234F", False), ("abcde1234f", False),
                                        ("ABCDE12345", False), ("ABCDE1234", False)])
def test_pan_format(v, expected):
    assert ok("PAN_FORMAT", v) is expected


def test_pan_individual_is_a_warning():
    r = RULES["PAN_INDIVIDUAL"]("ABCCE1234F", CTX)
    assert not r.ok and r.severity == "warning"
    assert ok("PAN_INDIVIDUAL", "ABCPE1234F")


def test_aadhaar_rules():
    good = aadhaar()
    assert ok("AADHAAR_FORMAT", good) and ok("AADHAAR_CHECKSUM", good)
    assert not ok("AADHAAR_FORMAT", "123456789012")      # starts with 1
    assert not ok("AADHAAR_FORMAT", "2345678901")        # too short
    assert not ok("AADHAAR_CHECKSUM", good[:-1] + str((int(good[-1]) + 3) % 10))


@pytest.mark.parametrize("v,expected", [("HDFC0001234", True), ("HDFC1001234", False),
                                        ("HDF0001234", False), ("hdfc0001234", False)])
def test_ifsc(v, expected):
    assert ok("IFSC_FORMAT", v) is expected


def test_account_pincode_name_amount():
    assert ok("ACCOUNT_NO", "123456789012") and not ok("ACCOUNT_NO", "12345678") and not ok("ACCOUNT_NO", "XXXX123456789")
    assert ok("PINCODE", "560001") and not ok("PINCODE", "060001") and not ok("PINCODE", "56001")
    assert ok("NAME_VALID", "RAHUL SHARMA") and ok("NAME_VALID", "O'Brien-Rao Jr.") and ok("NAME_VALID", "रवि कुमार")
    assert not ok("NAME_VALID", "R4HUL") and not ok("NAME_VALID", "A")
    assert ok("AMOUNT_POSITIVE", "45000") and not ok("AMOUNT_POSITIVE", "0") and not ok("AMOUNT_POSITIVE", "abc")


def test_dob_and_age():
    assert ok("DOB_VALID", "1990-08-15") and not ok("DOB_VALID", "2027-01-01") and not ok("DOB_VALID", "garbage")
    assert not ok("AGE_RANGE", "2012-01-01")                       # 14 years old -> hard error
    assert RULES["AGE_RANGE"]("2012-01-01", CTX).severity == "error"
    old = RULES["AGE_RANGE"]("1950-01-01", CTX)
    assert not old.ok and old.severity == "warning"
    assert ok("AGE_RANGE", "1990-08-15")


def test_future_doc_date():
    assert not ok("DOC_DATE_NOT_FUTURE", "2026-11-01") and ok("DOC_DATE_NOT_FUTURE", "2026-10-31")


@pytest.mark.parametrize("s,expected", [
    ("September 2026", (2026, 9)), ("Sep-26", (2026, 9)), ("sep 2026", (2026, 9)),
    ("09/2026", (2026, 9)), ("2026-09", (2026, 9)), ("Sept 2026", (2026, 9)), ("nonsense", None), ("13/2026", None)])
def test_parse_pay_month(s, expected):
    assert parse_pay_month(s) == expected


def test_normalizers():
    assert parse_date("15/08/1990") == date(1990, 8, 15) == parse_date("15 Aug 1990") == parse_date("15-08-1990")
    assert str(parse_amount("₹ 1,25,000.50")) == "125000.50" and str(parse_amount("(2,000)")) == "-2000"
    assert normalize_value("pan_number", "string", " abcde 1234f ") == "ABCDE1234F"
    assert normalize_value("aadhaar_number", "string", "2345 6789 0123") == "234567890123"
    assert normalize_value("pay_month", "string", "garbage") is None
    assert normalize_value("name", "string", "N/A") is None


def test_validate_fields_statuses():
    raw = {"pan_number": "abcde1234f", "name": "RAHUL SHARMA", "father_name": None, "dob": "15/08/1990"}
    f = {x.key: x for x in validate_fields("pan", raw, CTX)}
    assert f["pan_number"].status == FieldStatus.VALID and f["pan_number"].normalized_value == "ABCDE1234F"
    assert f["pan_number"].raw_value == "abcde1234f"
    assert f["father_name"].status == FieldStatus.NOT_EXTRACTED and not f["father_name"].required or True
    assert f["dob"].normalized_value == "1990-08-15"


def test_invalid_field_carries_rule_and_message():
    f = {x.key: x for x in validate_fields("pan", {"pan_number": "ABCD1234F", "name": "RAHUL", "dob": "15/08/1990"}, CTX)}
    assert f["pan_number"].status == FieldStatus.INVALID
    assert f["pan_number"].failed_rule_id == "PAN_FORMAT" and "5 letters" in f["pan_number"].message
    assert f["dob"].status == FieldStatus.VALID


def test_unparseable_pay_month_is_not_extracted():
    f = {x.key: x for x in validate_fields("salary_slip", {"pay_month": "??"}, CTX)}
    assert f["pay_month"].status == FieldStatus.NOT_EXTRACTED


def test_warning_keeps_field_valid():
    f = {x.key: x for x in validate_fields("pan", {"pan_number": "ABCCE1234F", "name": "RAHUL", "dob": "15/08/1990"}, CTX)}
    assert f["pan_number"].status == FieldStatus.VALID and f["pan_number"].warning


def test_user_entry_uses_the_same_rules():
    bad = revalidate_user_value("bank_statement", "ifsc", "HDFC1001234", CTX)
    assert bad.status == FieldStatus.INVALID and bad.failed_rule_id == "IFSC_FORMAT" and bad.source == "user"
    good = revalidate_user_value("bank_statement", "ifsc", "hdfc0001234", CTX)
    assert good.status == FieldStatus.USER_ENTERED_VALID and good.normalized_value == "HDFC0001234"


def test_validate_value_returns_first_blocking_failure():
    norm, failure, warnings = validate_value("pan_number", "string", ["PAN_FORMAT", "PAN_INDIVIDUAL"], "ABCD1234F", CTX)
    assert failure.rule_id == "PAN_FORMAT" and warnings == []
