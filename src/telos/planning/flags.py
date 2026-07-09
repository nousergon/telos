"""Quarter-by-quarter payment flags: the "should I send a check?" layer.

Pure data-in/data-out: vouchers from ``telos.engine.estimated``, payments
made and ``as_of`` from the scenario. ISO-8601 date strings compare
correctly as strings, so no datetime arithmetic is needed — and no clock is
consulted anywhere (``as_of`` is scenario data).

The headline's recommended amount is catch-up semantics: every overdue
installment's shortfall plus the next upcoming installment's shortfall. It
answers the planning question — what should be paid now to stop the hole
from deepening — and does NOT itself run the §6654 underpayment penalty.
That penalty (Form 2210 Part III) and the Schedule AI annualized-income
method now live in ``telos.engine.form2210`` and
``telos.engine.estimated`` (telos-ops#20); a caller wanting the dollar
penalty feeds the per-installment underpayments to
``telos.engine.form2210.compute_form2210_penalty``.
"""

from __future__ import annotations

from decimal import Decimal

from telos.contracts import PaymentHeadline, QuarterFlag, QuarterPaymentStatus
from telos.engine.estimated import EstimatedTaxResult
from telos.planning.scenario import PlanningScenario

_ZERO = Decimal(0)


def flag_quarters(
    estimated: EstimatedTaxResult, scenario: PlanningScenario
) -> tuple[tuple[QuarterFlag, ...], PaymentHeadline]:
    paid_by_quarter: dict[int, Decimal] = {}
    for payment in scenario.estimated_payments_made:
        paid_by_quarter[payment.quarter] = (
            paid_by_quarter.get(payment.quarter, _ZERO) + payment.amount
        )

    flags: list[QuarterFlag] = []
    for voucher in estimated.vouchers:
        required = voucher.amount.value
        paid = paid_by_quarter.get(voucher.quarter, _ZERO)
        shortfall = max(required - paid, _ZERO)
        if shortfall == _ZERO:
            status = QuarterPaymentStatus.PAID
        elif voucher.due_date < scenario.as_of:
            status = QuarterPaymentStatus.OVERDUE
        else:
            status = QuarterPaymentStatus.UPCOMING
        flags.append(
            QuarterFlag(
                quarter=voucher.quarter,
                due_date=voucher.due_date,
                required=required,
                paid=paid,
                shortfall=shortfall,
                status=status,
            )
        )

    return tuple(flags), _headline(tuple(flags), estimated)


def _headline(
    flags: tuple[QuarterFlag, ...], estimated: EstimatedTaxResult
) -> PaymentHeadline:
    if not flags:
        return PaymentHeadline(
            payment_recommended=False,
            recommended_amount=_ZERO,
            next_due_date=None,
            message=(
                "No estimated payments required — withholding meets the "
                f"required annual payment ({estimated.safe_harbor_basis} harbor)."
            ),
        )

    overdue = [f for f in flags if f.status is QuarterPaymentStatus.OVERDUE]
    upcoming = [f for f in flags if f.status is QuarterPaymentStatus.UPCOMING]
    next_flag = upcoming[0] if upcoming else None

    amount = sum((f.shortfall for f in overdue), start=_ZERO)
    if next_flag is not None:
        amount += next_flag.shortfall
    next_due = next_flag.due_date if next_flag is not None else None

    if amount == _ZERO:
        return PaymentHeadline(
            payment_recommended=False,
            recommended_amount=_ZERO,
            next_due_date=next_due,
            message="All installments due so far are covered; nothing to pay right now.",
        )

    parts = []
    if overdue:
        qs = ", ".join(f"Q{f.quarter}" for f in overdue)
        parts.append(f"{qs} overdue (shortfall {sum(f.shortfall for f in overdue)})")
    if next_flag is not None and next_flag.shortfall > _ZERO:
        parts.append(f"Q{next_flag.quarter} due {next_flag.due_date}")
    return PaymentHeadline(
        payment_recommended=True,
        recommended_amount=amount,
        next_due_date=next_due,
        message=(
            f"Pay {amount} ({'; '.join(parts)}) — "
            f"{estimated.safe_harbor_basis} harbor governs."
        ),
    )
