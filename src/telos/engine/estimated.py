"""Form 1040-ES — quarterly estimated-tax vouchers under the §6654 safe harbors.

Computes the *required annual payment* (the smaller of the 90%-of-current-year
harbor or the 100%/110%-of-prior-year harbor, per IRC §6654(d)(1)) and
splits the shortfall after withholding into four even quarterly vouchers with
their statutory due dates (§6654(c)(2)).

Deliberate seam: the annualized-income-installment method (Schedule AI, for
taxpayers whose income arrives unevenly across the year) is NOT implemented.
Per the coverage-guard philosophy elsewhere in this engine (fail loud, never
silently substitute), requesting it raises
``AnnualizedIncomeMethodNotImplementedError`` rather than quietly falling
back to even installments.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Literal

from telos.contracts import EstimatedTaxRequest
from telos.engine.rounding import round_whole_dollar
from telos.engine.trace import Traced
from telos.params import ParamPack

FORM_CITE = "IRC §6654"
_ZERO = Decimal(0)
_NUM_INSTALLMENTS = 4

# Statutory installment due dates (month, day) — §6654(c)(2). The 4th
# installment falls in the January of the *following* calendar year. These
# are the un-shifted statutory dates: the IRS moves a date that falls on a
# weekend/federal holiday to the next business day, which this module does
# NOT compute (that's a calendar lookup, not a tax constant) — callers
# needing the shifted date should override ``QuarterlyVoucher.due_date``.
_DUE_DATES: tuple[tuple[int, int, int], ...] = (
    (1, 4, 15),
    (2, 6, 15),
    (3, 9, 15),
    (4, 1, 15),  # of tax_year + 1
)

SafeHarborBasis = Literal["90pct_current_year", "100pct_prior_year", "110pct_prior_year"]


class AnnualizedIncomeMethodNotImplementedError(NotImplementedError):
    """Schedule AI is not built yet — refusing to silently use even installments."""

    def __init__(self) -> None:
        super().__init__(
            "annualized-income-installment method (Schedule AI) is not implemented "
            "(telos-ops#7 stub) — refusing to silently fall back to the even-"
            "installment method; set use_annualized_income_method=False, or compute "
            "quarterly income splits upstream and call this module per-quarter"
        )


@dataclass(frozen=True)
class QuarterlyVoucher:
    quarter: int  # 1-4
    due_date: str  # ISO date, YYYY-MM-DD
    amount: Traced


@dataclass(frozen=True)
class EstimatedTaxResult:
    safe_harbor_basis: SafeHarborBasis
    required_annual_payment: Traced
    total_estimated_tax_due: Traced  # required_annual_payment - withholding, floored at 0
    vouchers: tuple[QuarterlyVoucher, ...]

    def explain(self) -> str:
        parts = [self.required_annual_payment.explain(), self.total_estimated_tax_due.explain()]
        parts += [f"Q{v.quarter} due {v.due_date}: {v.amount.value}" for v in self.vouchers]
        return "\n".join(parts)


def _prior_year_safe_harbor(request: EstimatedTaxRequest, pack: ParamPack) -> tuple[Traced, bool]:
    """The 100%/110%-of-prior-year harbor amount, and whether the higher-income fork applied."""
    threshold = pack.get(f"estimated_tax.higher_income_agi_threshold.{request.filing_status.value}")
    higher_income = request.prior_year_agi > threshold.value
    pct = pack.get(
        "estimated_tax.safe_harbor_higher_income_prior_year_pct"
        if higher_income
        else "estimated_tax.safe_harbor_standard_prior_year_pct"
    )
    prior_year_tax = Traced(
        label="estimated:prior_year_tax", value=request.prior_year_tax,
        sources=("taxpayer-provided prior-year total tax",),
    )
    amount = Traced(
        label="estimated:prior_year_safe_harbor",
        value=round_whole_dollar(prior_year_tax.value * pct.value),
        sources=(f"{FORM_CITE}(d)(1)(B)(ii)/(C)(i)",),
        inputs=(prior_year_tax, pct, threshold),
    )
    return amount, higher_income


def compute_estimated_tax(
    request: EstimatedTaxRequest, pack: ParamPack, *, tax_year: int
) -> EstimatedTaxResult:
    if request.use_annualized_income_method:
        raise AnnualizedIncomeMethodNotImplementedError

    current_year_pct = pack.get("estimated_tax.safe_harbor_current_year_pct")
    current_year_tax = Traced(
        label="estimated:current_year_projected_tax", value=request.current_year_projected_tax,
        sources=("taxpayer-provided current-year projected tax",),
    )
    current_year_harbor = Traced(
        label="estimated:current_year_safe_harbor",
        value=round_whole_dollar(current_year_tax.value * current_year_pct.value),
        sources=(f"{FORM_CITE}(d)(1)(B)(i)",),
        inputs=(current_year_tax, current_year_pct),
    )

    if request.prior_year_return_covered_12_months:
        prior_year_harbor, higher_income = _prior_year_safe_harbor(request, pack)
        if prior_year_harbor.value <= current_year_harbor.value:
            required_annual_payment = prior_year_harbor
            basis: SafeHarborBasis = "110pct_prior_year" if higher_income else "100pct_prior_year"
        else:
            required_annual_payment = current_year_harbor
            basis = "90pct_current_year"
    else:
        # §6654(d)(1)(B)(ii) requires the prior return to cover 12 months for
        # the prior-year harbors to apply at all — only the current-year
        # harbor is available otherwise.
        required_annual_payment = current_year_harbor
        basis = "90pct_current_year"

    withholding = Traced(
        label="estimated:current_year_withholding", value=request.current_year_withholding,
        sources=("taxpayer-provided current-year withholding",),
    )
    total_due_value = max(required_annual_payment.value - withholding.value, _ZERO)
    total_estimated_tax_due = Traced(
        label="estimated:total_estimated_tax_due", value=total_due_value,
        sources=(f"{FORM_CITE}(a) required annual payment less withholding, floored at 0",),
        inputs=(required_annual_payment, withholding),
    )

    vouchers = _split_into_vouchers(total_estimated_tax_due, tax_year)

    return EstimatedTaxResult(
        safe_harbor_basis=basis,
        required_annual_payment=required_annual_payment,
        total_estimated_tax_due=total_estimated_tax_due,
        vouchers=vouchers,
    )


def _split_into_vouchers(total_due: Traced, tax_year: int) -> tuple[QuarterlyVoucher, ...]:
    """Four even installments (§6654(d)(1) default); remainder trues up on Q4."""
    if total_due.value <= _ZERO:
        return ()
    base = round_whole_dollar(total_due.value / _NUM_INSTALLMENTS)
    amounts = [base] * (_NUM_INSTALLMENTS - 1)
    amounts.append(total_due.value - base * (_NUM_INSTALLMENTS - 1))
    vouchers = []
    for (quarter, month, day), amount in zip(_DUE_DATES, amounts, strict=True):
        due_year = tax_year + 1 if quarter == _NUM_INSTALLMENTS else tax_year
        vouchers.append(
            QuarterlyVoucher(
                quarter=quarter,
                due_date=f"{due_year:04d}-{month:02d}-{day:02d}",
                amount=Traced(
                    label=f"estimated:voucher_q{quarter}", value=amount,
                    sources=(f"{FORM_CITE}(c)(2) installment {quarter}",),
                    inputs=(total_due,),
                ),
            )
        )
    return tuple(vouchers)
