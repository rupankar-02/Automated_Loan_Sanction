import pytest

from core.requirements import UnsupportedProfile, build_checklist, required_count


def test_personal_salaried_checklist():
    docs = build_checklist("personal", "salaried")
    assert [d.id for d in docs] == ["pan", "aadhaar", "salary_slip", "bank_statement", "form16_or_itr"]
    assert required_count(docs) == 4


def test_form16_is_optional():
    docs = {d.id: d for d in build_checklist("personal", "salaried")}
    assert docs["form16_or_itr"].optional
    assert not docs["pan"].optional


def test_salary_slip_needs_three_and_aadhaar_two_sides():
    docs = {d.id: d for d in build_checklist("personal", "salaried")}
    assert docs["salary_slip"].count == 3 and docs["salary_slip"].recency_months == 3
    assert docs["aadhaar"].sides == ["front", "back"]


def test_unsupported_profile_gives_clear_error():
    with pytest.raises(UnsupportedProfile, match="not available yet"):
        build_checklist("home", "business")
