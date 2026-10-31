"""Document-level and set-level rules (run after field rules)."""
from datetime import date
from decimal import Decimal

from core.models import DocIssue, FieldResult, FieldStatus
from core.validation.field_rules import RuleContext, make_context
from core.validation.months import check_bank_period, check_salary_months
from core.validation.normalize import parse_date, parse_month_str


def _values(fields: list[FieldResult]) -> dict[str, str]:
    return {f.key: f.normalized_value for f in fields
            if f.normalized_value is not None and f.status in (FieldStatus.VALID, FieldStatus.USER_ENTERED_VALID)}


def apply_document_rules(doc_type: str, fields: list[FieldResult], ctx: RuleContext | None = None) -> list[DocIssue]:
    ctx = ctx or make_context()
    v = _values(fields)
    issues: list[DocIssue] = []

    if doc_type == "salary_slip" and "gross_salary" in v and "net_salary" in v:
        gross, net = Decimal(v["gross_salary"]), Decimal(v["net_salary"])
        if net > gross:
            issues.append(DocIssue(rule_id="SALARY_NET_LE_GROSS", action="edit",
                                   message="Net salary is higher than gross salary. Please check both amounts."))
        elif "total_deductions" in v:
            diff = abs(gross - Decimal(v["total_deductions"]) - net)
            if gross > 0 and diff > gross * Decimal("0.02"):
                issues.append(DocIssue(rule_id="SALARY_DEDUCTION_MATH", severity="warning", action="edit",
                                       message="Gross minus deductions does not match net salary. Please check the amounts."))

    if doc_type == "form16" and "gross_salary" in v and "taxable_income" in v:
        if Decimal(v["taxable_income"]) > Decimal(v["gross_salary"]):
            issues.append(DocIssue(rule_id="FORM16_GROSS_GE_TAXABLE", severity="warning", action="edit",
                                   message="Taxable income is higher than gross salary. Please check both amounts."))

    if doc_type == "bank_statement" and "statement_from" in v and "statement_to" in v:
        start, end = parse_date(v["statement_from"]), parse_date(v["statement_to"])
        if start and end:
            issues += check_bank_period(start, end, ctx.today, ctx.policy)
    return issues


def apply_salary_set_rules(pay_months: list[str], ctx: RuleContext | None = None) -> list[DocIssue]:
    """pay_months: normalised 'YYYY-MM' strings, one per uploaded slip."""
    ctx = ctx or make_context()
    return check_salary_months([parse_month_str(m) for m in pay_months], ctx.today, ctx.policy)
