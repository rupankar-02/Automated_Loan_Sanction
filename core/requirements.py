"""Build the exact document checklist for a (loan type, employment type) profile."""
from core.config.loader import get_requirements
from core.models import DocSpec

LOAN_TYPES = {"personal": "Personal loan", "car": "Car loan", "home": "Home loan"}
EMPLOYMENT_TYPES = {"salaried": "Salaried", "business": "Self-employed / Business",
                    "unemployed": "Not currently employed"}


class UnsupportedProfile(Exception):
    pass


def supported_profiles() -> dict[str, list[str]]:
    return {loan: list(emp) for loan, emp in get_requirements()["profiles"].items()}


def build_checklist(loan_type: str, employment: str) -> list[DocSpec]:
    req = get_requirements()
    try:
        entries = req["profiles"][loan_type][employment]
    except KeyError:
        raise UnsupportedProfile(
            f"{LOAN_TYPES.get(loan_type, loan_type)} for "
            f"{EMPLOYMENT_TYPES.get(employment, employment)} applicants is not available yet."
        ) from None
    specs = []
    for e in entries:
        doc = req["documents"][e["doc"]]
        specs.append(DocSpec(id=e["doc"], optional=e.get("optional", False), **doc))
    return specs


def required_count(checklist: list[DocSpec]) -> int:
    return sum(1 for d in checklist if not d.optional)
