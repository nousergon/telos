"""Human rendering of a ``ProjectionOutcome`` — the terminal dashboard."""

from __future__ import annotations

from telos.contracts import QuarterPaymentStatus
from telos.planning.projection import ProjectionOutcome

_STATUS_MARK = {
    QuarterPaymentStatus.PAID: "PAID",
    QuarterPaymentStatus.OVERDUE: "OVERDUE",
    QuarterPaymentStatus.UPCOMING: "upcoming",
}


def render_report(outcome: ProjectionOutcome) -> str:
    a = outcome.artifact
    p = a.projected
    h = a.headline
    lines = [
        f"Telos tax projection — TY{a.tax_year} ({a.filing_status.value}), as of {a.as_of}",
        f"[parameter pack: {a.pack_status}]",
        "",
        f"  Projected AGI:            {p.agi:>12,}",
        f"  Projected taxable income: {p.taxable_income:>12,}",
        f"  Projected total tax:      {p.total_tax:>12,}",
        f"  Withholding (full year):  {p.total_withholding:>12,}",
        f"  Estimated payments made:  {p.estimated_payments_made:>12,}",
        f"  Balance due at filing:    {p.balance_due:>12,}   (negative = refund)",
        f"  Effective rate on AGI:    {p.effective_rate_on_agi:>12}",
        f"  Marginal ordinary rate:   {p.marginal_ordinary_rate:>12}",
        "",
        f"  Safe harbor: {a.safe_harbor.basis}",
        f"    Required annual payment:  {a.safe_harbor.required_annual_payment:>12,}",
        f"    Due beyond withholding:   {a.safe_harbor.total_estimated_tax_due:>12,}",
    ]
    if a.quarters:
        lines.append("")
        lines.append("  1040-ES installments:")
        for q in a.quarters:
            lines.append(
                f"    Q{q.quarter} due {q.due_date}: required {q.required:>10,}  "
                f"paid {q.paid:>10,}  shortfall {q.shortfall:>10,}  "
                f"[{_STATUS_MARK[q.status]}]"
            )
    lines += ["", f"  >>> {h.message}"]
    return "\n".join(lines)
