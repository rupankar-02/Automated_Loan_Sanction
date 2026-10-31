"""Loan arithmetic. Pure functions; the only place EMI maths lives."""


def _r(annual_pct: float) -> float:
    return annual_pct / 12 / 100


def emi(principal: float, annual_pct: float, months: int) -> float:
    r = _r(annual_pct)
    if r == 0:
        return principal / months
    f = (1 + r) ** months
    return principal * r * f / (f - 1)


def max_principal(emi_capacity: float, annual_pct: float, months: int) -> float:
    """Largest loan whose EMI fits in `emi_capacity`."""
    if emi_capacity <= 0:
        return 0.0
    r = _r(annual_pct)
    if r == 0:
        return emi_capacity * months
    f = (1 + r) ** months
    return emi_capacity * (f - 1) / (r * f)


def total_interest(principal: float, annual_pct: float, months: int) -> float:
    return emi(principal, annual_pct, months) * months - principal


def processing_fee(principal: float, fee_pct: float) -> float:
    return principal * fee_pct / 100


def total_cost(principal: float, annual_pct: float, months: int, fee_pct: float) -> float:
    """Total interest + processing fee (not a regulatory APR)."""
    return total_interest(principal, annual_pct, months) + processing_fee(principal, fee_pct)
