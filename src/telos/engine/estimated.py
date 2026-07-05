"""Form 1040-ES — quarterly estimated-tax vouchers under the §6654 safe harbors.

Computes the *required annual payment* (the smaller of the 90%-of-current-year
harbor or the 100%/110%-of-prior-year harbor, per IRC §6654(d)(1)) and
splits the shortfall after withholding into four even quarterly vouchers with
their statutory due dates (§6654(c)(2)).

The annualized-income-installment method (Schedule AI, IRC §6654(d)(2), for
taxpayers whose income arrives unevenly across the year) is implemented:
per-period cumulative taxable income is placed on an annualized basis with the
statutory annualization factors and the applicable percentages (22.5/45/67.5/
90%) size each required installment. Even (ratable) income reproduces the
even-installment safe-harbor result to the dollar — a property test guards it.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Literal

from telos.contracts import EstimatedTaxRequest
from telos.engine.brackets import Bracket, tax_from_brackets
from telos.engine.rounding import round_whole_dollar
from telos.engine.trace import Traced
from telos.params import ParamPack

FORM_CITE = "IRC §6654"
_ZERO = Decimal(0)
_NUM_INSTALLMENTS = 4

# §6654(d)(2)(B)/(C) — the annualized-income-installment method for a
# calendar-year taxpayer. The four annualization PERIODS end 3/31, 5/31, 8/31
# and 12/31; income accumulated through each period end is annualized by
# dividing by the fraction of the year elapsed, i.e. multiplied by 12/N where
# N is the number of months in the period (12/3=4, 12/5=2.4, 12/8=1.5,
# 12/12=1). These factors are printed on Schedule AI (Form 2210) line 2.
_ANNUALIZATION_FACTORS: tuple[Decimal, ...] = (
    Decimal(4),
    Decimal("2.4"),
    Decimal("1.5"),
    Decimal(1),
)
# §6654(d)(2)(C)(ii) — the "applicable percentage" for each of the four
# installments (cumulative through that installment).
_APPLICABLE_PERCENTAGES: tuple[Decimal, ...] = (
    Decimal("0.225"),
    Decimal("0.45"),
    Decimal("0.675"),
    Decimal("0.90"),
)
_ANNUALIZATION_CITE = "IRC §6654(d)(2)(B)-(C); Schedule AI (Form 2210), Part I"

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
    """Retained for API/back-compat: the annualized method is now implemented
    (telos-ops#20), so ``compute_estimated_tax`` no longer raises this. It
    remains importable so any downstream ``except`` clause keeps type-checking;
    it is raised only if a future path re-introduces an unbuilt sub-case."""

    def __init__(self, detail: str = "annualized-income-installment sub-case not built") -> None:
        super().__init__(detail)


@dataclass(frozen=True)
class QuarterlyVoucher:
    quarter: int  # 1-4
    due_date: str  # ISO date, YYYY-MM-DD
    amount: Traced


@dataclass(frozen=True)
class AnnualizedInstallment:
    quarter: int  # 1-4
    annualization_factor: Traced
    annualized_taxable_income: Traced
    applicable_percentage: Traced
    cumulative_required: Traced  # applicable% * annualized tax (Schedule AI line 27)
    required_installment: Traced  # this period's incremental required payment


@dataclass(frozen=True)
class AnnualizedInstallmentResult:
    installments: tuple[AnnualizedInstallment, ...]

    def explain(self) -> str:
        return "\n".join(i.required_installment.explain() for i in self.installments)


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


def compute_annualized_installments(
    period_taxable_income: tuple[Decimal, Decimal, Decimal, Decimal],
    brackets: list[Bracket],
) -> AnnualizedInstallmentResult:
    """Schedule AI (Form 2210) required installments, IRC §6654(d)(2).

    ``period_taxable_income`` is the CUMULATIVE taxable income through each of
    the four annualization period ends (3/31, 5/31, 8/31, 12/31). Each is
    annualized (* the statutory factor), taxed on ``brackets``, taken to the
    applicable percentage, and differenced against the running total to give
    the incremental required installment. Installments are floored at 0 (a
    later period cannot have a *negative* required installment even if
    annualized tax fell) — matching Schedule AI's "not less than zero" lines.
    """
    installments: list[AnnualizedInstallment] = []
    cumulative_paid = _ZERO
    for i in range(_NUM_INSTALLMENTS):
        quarter = i + 1
        factor = Traced(
            label=f"annualized:factor_q{quarter}", value=_ANNUALIZATION_FACTORS[i],
            sources=(_ANNUALIZATION_CITE,),
        )
        period_income = Traced(
            label=f"annualized:period_taxable_income_q{quarter}",
            value=period_taxable_income[i],
            sources=("Schedule AI (Form 2210), Part I, line 1 (taxpayer-provided)",),
        )
        annualized = Traced(
            label=f"annualized:annualized_taxable_income_q{quarter}",
            value=period_income.value * factor.value,
            sources=(_ANNUALIZATION_CITE + ", line 3 (annualized income)",),
            inputs=(period_income, factor),
        )
        annualized_tax = round_whole_dollar(tax_from_brackets(annualized.value, brackets))
        pct = Traced(
            label=f"annualized:applicable_pct_q{quarter}", value=_APPLICABLE_PERCENTAGES[i],
            sources=("IRC §6654(d)(2)(C)(ii); Schedule AI (Form 2210), line 22",),
        )
        cumulative_required = Traced(
            label=f"annualized:cumulative_required_q{quarter}",
            value=round_whole_dollar(annualized_tax * pct.value),
            sources=(_ANNUALIZATION_CITE + ", line 23 (applicable % of annualized tax)",),
            inputs=(annualized, pct),
        )
        incremental = max(cumulative_required.value - cumulative_paid, _ZERO)
        required_installment = Traced(
            label=f"annualized:required_installment_q{quarter}",
            value=incremental,
            sources=(
                _ANNUALIZATION_CITE + ", line 27 (cumulative required less prior installments)",
            ),
            inputs=(cumulative_required,),
        )
        cumulative_paid += incremental
        installments.append(
            AnnualizedInstallment(
                quarter=quarter,
                annualization_factor=factor,
                annualized_taxable_income=annualized,
                applicable_percentage=pct,
                cumulative_required=cumulative_required,
                required_installment=required_installment,
            )
        )
    return AnnualizedInstallmentResult(installments=tuple(installments))


def compute_estimated_tax(
    request: EstimatedTaxRequest, pack: ParamPack, *, tax_year: int
) -> EstimatedTaxResult:
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

    if request.use_annualized_income_method:
        assert request.annualized_period_taxable_income is not None  # contract-guaranteed
        brackets = pack.brackets(f"ordinary_brackets.{request.filing_status.value}")
        annualized = compute_annualized_installments(
            request.annualized_period_taxable_income, brackets
        )
        vouchers = _split_annualized(total_estimated_tax_due, annualized, tax_year)
    else:
        vouchers = _split_into_vouchers(total_estimated_tax_due, tax_year)

    return EstimatedTaxResult(
        safe_harbor_basis=basis,
        required_annual_payment=required_annual_payment,
        total_estimated_tax_due=total_estimated_tax_due,
        vouchers=vouchers,
    )


def _split_annualized(
    total_due: Traced,
    annualized: AnnualizedInstallmentResult,
    tax_year: int,
) -> tuple[QuarterlyVoucher, ...]:
    """Distribute ``total_due`` across the four installments using the Schedule
    AI shares (§6654(d)(2)), each capped at the corresponding regular 25%
    installment (Schedule AI line 25: the required installment is the SMALLER of
    the annualized amount or the regular installment; the shortfall recaptures
    on later installments — line 26/27). The Q4 installment trues up any
    remainder so the vouchers always sum to ``total_due``.

    Even (ratable) income makes every annualized share exactly 22.5% of annual
    tax; capped at the 25% regular installment they collapse to four even
    quarters — the safe-harbor result (asserted by a property test)."""
    if total_due.value <= _ZERO:
        return ()

    regular = round_whole_dollar(total_due.value / _NUM_INSTALLMENTS)
    # Schedule AI shares of the *annual required payment*: the cumulative
    # required at each period is applicable% of annualized tax; scale those
    # shares onto total_due (the harbor after withholding) so the annualized
    # method never demands more than the safe harbor overall.
    total_annualized_required = annualized.installments[-1].cumulative_required.value
    amounts: list[Decimal] = []
    running = _ZERO
    for i, inst in enumerate(annualized.installments):
        cap = regular if i < _NUM_INSTALLMENTS - 1 else total_due.value - running
        if total_annualized_required > _ZERO:
            share = round_whole_dollar(
                total_due.value * (inst.required_installment.value / total_annualized_required)
            )
        else:
            share = _ZERO
        amount = min(share, cap) if i < _NUM_INSTALLMENTS - 1 else cap
        amount = max(amount, _ZERO)
        amounts.append(amount)
        running += amount

    vouchers = []
    for (quarter, month, day), inst, amount in zip(
        _DUE_DATES, annualized.installments, amounts, strict=True
    ):
        due_year = tax_year + 1 if quarter == _NUM_INSTALLMENTS else tax_year
        vouchers.append(
            QuarterlyVoucher(
                quarter=quarter,
                due_date=f"{due_year:04d}-{month:02d}-{day:02d}",
                amount=Traced(
                    label=f"estimated:voucher_q{quarter}", value=amount,
                    sources=(
                        f"{FORM_CITE}(d)(2) annualized installment {quarter} "
                        f"(Schedule AI), capped at the 25% regular installment",
                    ),
                    inputs=(total_due, inst.required_installment),
                ),
            )
        )
    return tuple(vouchers)


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
