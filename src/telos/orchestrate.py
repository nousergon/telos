"""The full-return orchestrator: sequence every module in dependency order.

``assemble_1040`` deliberately takes precomputed seams; this layer computes
them in the order the forms require:

1. Schedule D (lots -> line 7a + the QDCGT net-capital-gain input);
2. Schedule E (worksheet contract -> Schedule 1, NIIT 4a, QBI component);
3. AGI (income only — independent of deductions);
4. Schedule A with AGI -> ``choose_deduction`` (standard vs itemized);
5. Form 8995-A with taxable-income-before-QBI;
6. Forms 8959/8960 (Schedule 2 taxes + the line-25c withholding credit);
7. the 1040 assembly;
8. the AMT guard as a MANDATORY post-assembly check (raises on triggers).

Pure computation — no I/O; the replay harness (``telos.replay``) owns files.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field

from telos.contracts import RealizedLots, ScheduleEWorksheet
from telos.engine import (
    AmtGuardInputs,
    AmtScreenResult,
    Form1040Inputs,
    Form1040Result,
    Form8959Result,
    Form8960Inputs,
    Form8960Result,
    Form8995AInputs,
    Form8995AResult,
    QbiBusiness,
    ScheduleAInputs,
    ScheduleAResult,
    ScheduleDInputs,
    ScheduleDResult,
    ScheduleEResult,
    amt_screen,
    assemble_1040,
    choose_deduction,
    form8959,
    form8960,
    form8995a,
    schedule_a,
    schedule_d,
    schedule_e,
)
from telos.models import W2, FilingStatus, Form1099Div, Form1099Int
from telos.params import ParamPack

_ZERO = Decimal(0)


class ScheduleAItems(BaseModel):
    """Schedule A inputs minus AGI/filing status (the orchestrator supplies those)."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    medical_expenses: Decimal = Field(default=_ZERO, ge=0)
    state_local_income_or_sales_tax: Decimal = Field(default=_ZERO, ge=0)
    real_estate_taxes: Decimal = Field(default=_ZERO, ge=0)
    personal_property_taxes: Decimal = Field(default=_ZERO, ge=0)
    other_taxes: Decimal = Field(default=_ZERO, ge=0)
    mortgage_interest_1098: Decimal = Field(default=_ZERO, ge=0)
    mortgage_interest_no_1098: Decimal = Field(default=_ZERO, ge=0)
    points_no_1098: Decimal = Field(default=_ZERO, ge=0)
    investment_interest: Decimal = Field(default=_ZERO, ge=0)
    charitable_cash: Decimal = Field(default=_ZERO, ge=0)
    charitable_noncash: Decimal = Field(default=_ZERO, ge=0)
    charitable_carryover: Decimal = Field(default=_ZERO, ge=0)
    casualty_losses: Decimal = Field(default=_ZERO, ge=0)
    other_itemized: Decimal = Field(default=_ZERO, ge=0)


class FullReturnInputs(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    tax_year: int
    filing_status: FilingStatus
    w2s: tuple[W2, ...] = ()
    forms_1099_int: tuple[Form1099Int, ...] = ()
    forms_1099_div: tuple[Form1099Div, ...] = ()
    realized_lots: Optional[RealizedLots] = None  # noqa: UP045 — pydantic-friendly
    capital_gain_distributions: Decimal = Field(default=_ZERO, ge=0)
    st_loss_carryover: Decimal = Field(default=_ZERO, ge=0)
    lt_loss_carryover: Decimal = Field(default=_ZERO, ge=0)
    schedule_e: Optional[ScheduleEWorksheet] = None  # noqa: UP045
    schedule_a: Optional[ScheduleAItems] = None  # noqa: UP045
    qbi_businesses: tuple[QbiBusiness, ...] = ()
    other_income: tuple[tuple[str, Decimal], ...] = Field(
        default=(), description="Schedule 1 line 8z items (e.g. crypto income)"
    )
    credits: tuple[tuple[str, Decimal], ...] = Field(
        default=(), description="Schedule 3 credits (e.g. foreign tax credit)"
    )
    niit_state_local_tax_allocable: Decimal = Field(
        default=_ZERO, ge=0, description="Form 8960 line 9b"
    )
    estimated_payments: Decimal = Field(default=_ZERO, ge=0)


@dataclass(frozen=True)
class FederalReturn:
    result: Form1040Result
    schedule_d: Optional[ScheduleDResult]  # noqa: UP045
    schedule_e: Optional[ScheduleEResult]  # noqa: UP045
    schedule_a: Optional[ScheduleAResult]  # noqa: UP045
    qbi: Optional[Form8995AResult]  # noqa: UP045
    f8959: Optional[Form8959Result]  # noqa: UP045
    f8960: Form8960Result
    amt: AmtScreenResult


def compute_federal_return(inputs: FullReturnInputs, pack: ParamPack) -> FederalReturn:
    fs = inputs.filing_status

    schd: Optional[ScheduleDResult] = None  # noqa: UP045
    if inputs.realized_lots is not None or inputs.capital_gain_distributions > 0:
        schd = schedule_d(
            ScheduleDInputs(
                filing_status=fs,
                realized=inputs.realized_lots or RealizedLots(),
                capital_gain_distributions=inputs.capital_gain_distributions,
                st_loss_carryover=inputs.st_loss_carryover,
                lt_loss_carryover=inputs.lt_loss_carryover,
            )
        )

    sche: Optional[ScheduleEResult] = None  # noqa: UP045
    if inputs.schedule_e is not None:
        sche = schedule_e(inputs.schedule_e, expected_tax_year=inputs.tax_year)

    line7a = schd.line7a.value if schd else _ZERO
    qdcgt_ncg = schd.qdcgt_net_capital_gain.value if schd else _ZERO
    sch1 = (sche.total.value if sche else _ZERO) + sum(
        (amount for _, amount in inputs.other_income), start=_ZERO
    )
    wages = sum((w.wages for w in inputs.w2s), start=_ZERO)
    interest = sum((f.interest_income for f in inputs.forms_1099_int), start=_ZERO)
    ordinary_div = sum((f.ordinary_dividends for f in inputs.forms_1099_div), start=_ZERO)
    qualified_div = sum((f.qualified_dividends for f in inputs.forms_1099_div), start=_ZERO)
    agi = wages + interest + ordinary_div + line7a + sch1

    scha: Optional[ScheduleAResult] = None  # noqa: UP045
    itemized_for_assembly: Optional[Decimal] = None  # noqa: UP045
    if inputs.schedule_a is not None:
        scha = schedule_a(
            ScheduleAInputs(filing_status=fs, agi=agi, **inputs.schedule_a.model_dump()),
            pack,
        )
        choice = choose_deduction(scha, fs, pack)
        if choice.value == scha.total_itemized.value and (
            choice.value > pack.get(f"standard_deduction.{fs.value}").value
        ):
            itemized_for_assembly = choice.value
    deduction = (
        itemized_for_assembly
        if itemized_for_assembly is not None
        else pack.get(f"standard_deduction.{fs.value}").value
    )

    qbi: Optional[Form8995AResult] = None  # noqa: UP045
    qbi_amount = _ZERO
    if inputs.qbi_businesses:
        ti_before_qbi = max(agi - deduction, _ZERO)
        qbi = form8995a(
            Form8995AInputs(
                filing_status=fs,
                businesses=inputs.qbi_businesses,
                taxable_income_before_qbi=ti_before_qbi,
                net_capital_gain_plus_qualified_dividends=qdcgt_ncg + qualified_div,
            ),
            pack,
        )
        qbi_amount = qbi.deduction.value

    f59: Optional[Form8959Result] = None  # noqa: UP045
    other_taxes: list[tuple[str, Decimal]] = []
    line25c = _ZERO
    if any(w.medicare_wages is not None for w in inputs.w2s):
        f59 = form8959(w2s=inputs.w2s, filing_status=fs, pack=pack)
        if f59.additional_medicare_tax.value > 0:
            other_taxes.append(("form8959:additional_medicare",
                                f59.additional_medicare_tax.value))
        line25c = f59.additional_withholding.value

    f60 = form8960(
        Form8960Inputs(
            filing_status=fs,
            taxable_interest=interest,
            ordinary_dividends=ordinary_div,
            rental_and_passthrough=sche.total_for_8960_line4a.value if sche else _ZERO,
            net_gain=line7a,
            state_local_tax_allocable=inputs.niit_state_local_tax_allocable,
            magi=max(agi, _ZERO),
        ),
        pack,
    )
    if f60.niit.value > 0:
        other_taxes.append(("form8960:niit", f60.niit.value))

    result = assemble_1040(
        Form1040Inputs(
            filing_status=fs,
            w2s=inputs.w2s,
            forms_1099_int=inputs.forms_1099_int,
            forms_1099_div=inputs.forms_1099_div,
            capital_gain_line7=line7a,
            qdcgt_net_capital_gain=qdcgt_ncg,
            schedule_1_income=sch1,
            itemized_deduction=itemized_for_assembly,
            qbi_deduction=qbi_amount,
            credits=inputs.credits,
            other_taxes=tuple(other_taxes),
            estimated_payments=inputs.estimated_payments,
            additional_medicare_withholding=line25c,
        ),
        pack,
    )

    addback = (
        scha.lines["7"].value
        if (scha is not None and itemized_for_assembly is not None)
        else pack.get(f"standard_deduction.{fs.value}").value
    )
    amt = amt_screen(
        AmtGuardInputs(
            filing_status=fs,
            taxable_income=result.lines["15"].value,
            deduction_addback=addback,
            preferential_income=result.lines["3a"].value + qdcgt_ncg,
            regular_tax=result.lines["16"].value,
        ),
        pack,
    )
    return FederalReturn(
        result=result, schedule_d=schd, schedule_e=sche, schedule_a=scha,
        qbi=qbi, f8959=f59, f8960=f60, amt=amt,
    )
