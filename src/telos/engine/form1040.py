"""Form 1040 assembly (v0.2 foundation): income -> taxable income -> line-16 tax.

Composes the typed source documents into the 1040's income lines, applies the
deduction, and computes the line-16 tax — via the Qualified Dividends and
Capital Gain Tax Worksheet whenever preferential-rate income is present,
otherwise via the plain line-16 lookup. Every line is ``Traced``.

Deliberate v0.2 seams (each owned by a milestone issue, wired here as typed
inputs rather than rebuilt):
- ``capital_gain_line7`` / ``qdcgt_net_capital_gain`` — Schedule D / 8949
  (telos-ops#4) produces these; line 7 may be negative (capital-loss year,
  limited upstream by Schedule D itself).
- ``schedule_1_income`` — Schedule E flows in via Schedule 1 (telos-ops#8).
- ``itemized_deduction`` — the Schedule A comparison (telos-ops#11) decides
  standard-vs-itemized; when None the standard deduction from the parameter
  pack applies.
- ``other_taxes`` — Schedule 2 additions (NIIT #5, Additional Medicare #15).
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from decimal import Decimal
from types import MappingProxyType
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field

from telos.engine.qdcgt import QdcgtResult, qdcgt_worksheet
from telos.engine.tax_lookup import line16_tax
from telos.engine.trace import Traced, traced_sum
from telos.models import W2, FilingStatus, Form1099Div, Form1099Int
from telos.params import ParamPack

_ZERO = Decimal(0)


class Form1040Inputs(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    filing_status: FilingStatus
    w2s: tuple[W2, ...] = ()
    forms_1099_int: tuple[Form1099Int, ...] = ()
    forms_1099_div: tuple[Form1099Div, ...] = ()
    capital_gain_line7: Decimal = _ZERO
    qdcgt_net_capital_gain: Optional[Decimal] = Field(  # noqa: UP045 — pydantic-friendly
        default=None,
        ge=0,
        description=(
            "QDCGT worksheet line 3: smaller of Schedule D lines 15/16 (0 if "
            "either is blank or a loss). None => derived as max(capital_gain_line7, 0) "
            "for the no-Schedule-D case (Form 1040 line 7a)."
        ),
    )
    schedule_1_income: Decimal = _ZERO
    itemized_deduction: Optional[Decimal] = Field(default=None, ge=0)  # noqa: UP045
    other_taxes: tuple[tuple[str, Decimal], ...] = ()
    estimated_payments: Decimal = Field(default=_ZERO, ge=0)


@dataclass(frozen=True)
class Form1040Result:
    lines: Mapping[str, Traced]
    qdcgt: Optional[QdcgtResult]  # noqa: UP045
    total_tax: Traced
    total_payments: Traced
    balance_due: Traced  # negative => refund

    def explain(self) -> str:
        order = ["1a", "2b", "3a", "3b", "7", "8", "9", "11", "12", "15", "16"]
        parts = [self.lines[k].explain() for k in order if k in self.lines]
        parts += [self.total_tax.explain(), self.total_payments.explain(),
                  self.balance_due.explain()]
        return "\n".join(parts)


def assemble_1040(inputs: Form1040Inputs, pack: ParamPack) -> Form1040Result:
    fs = inputs.filing_status
    ln: dict[str, Traced] = {}

    ln["1a"] = traced_sum(
        "1040:line1a wages",
        [Traced(label=f"w2:{w.employer}.wages", value=w.wages) for w in inputs.w2s],
    )
    ln["2b"] = traced_sum(
        "1040:line2b taxable interest",
        [Traced(label=f"1099int:{f.payer}", value=f.interest_income)
         for f in inputs.forms_1099_int],
    )
    ln["3a"] = traced_sum(
        "1040:line3a qualified dividends",
        [Traced(label=f"1099div:{f.payer}.qualified", value=f.qualified_dividends)
         for f in inputs.forms_1099_div],
    )
    ln["3b"] = traced_sum(
        "1040:line3b ordinary dividends",
        [Traced(label=f"1099div:{f.payer}.ordinary", value=f.ordinary_dividends)
         for f in inputs.forms_1099_div],
    )
    ln["7"] = Traced(
        label="1040:line7 capital gain or (loss)",
        value=inputs.capital_gain_line7,
        sources=("Schedule D (telos-ops#4 seam)",),
    )
    ln["8"] = Traced(
        label="1040:line8 additional income (Schedule 1)",
        value=inputs.schedule_1_income,
        sources=("Schedule 1 (telos-ops#8 seam)",),
    )
    ln["9"] = traced_sum(
        "1040:line9 total income",
        [ln["1a"], ln["2b"], ln["3b"], ln["7"], ln["8"]],
    )
    ln["11"] = ln["9"].derive("1040:line11 AGI", ln["9"].value)

    if inputs.itemized_deduction is not None:
        ln["12"] = Traced(
            label="1040:line12 itemized deduction",
            value=inputs.itemized_deduction,
            sources=("Schedule A (telos-ops#11 seam)",),
        )
    else:
        std = pack.get(f"standard_deduction.{fs.value}")
        ln["12"] = std.derive("1040:line12 standard deduction", std.value)

    ln["15"] = Traced(
        label="1040:line15 taxable income",
        value=max(ln["11"].value - ln["12"].value, _ZERO),
        sources=("Form 1040, line 15 (floor 0)",),
        inputs=(ln["11"], ln["12"]),
    )

    schedule = pack.brackets(f"ordinary_brackets.{fs.value}")
    qdcgt_result: Optional[QdcgtResult] = None  # noqa: UP045
    net_cap = (
        inputs.qdcgt_net_capital_gain
        if inputs.qdcgt_net_capital_gain is not None
        else max(inputs.capital_gain_line7, _ZERO)
    )
    if ln["3a"].value > 0 or net_cap > 0:
        qdcgt_result = qdcgt_worksheet(
            taxable_income=ln["15"],
            qualified_dividends=ln["3a"],
            net_capital_gain=Traced(label="qdcgt:net capital gain input", value=net_cap),
            filing_status=fs,
            pack=pack,
        )
        ln["16"] = qdcgt_result.tax.derive("1040:line16 tax (QDCGT worksheet)",
                                           qdcgt_result.tax.value)
    else:
        ln["16"] = line16_tax("1040:line16 tax", ln["15"], schedule)

    other = [
        Traced(label=f"schedule2:{name}", value=amount)
        for name, amount in inputs.other_taxes
    ]
    total_tax = traced_sum("1040:line24 total tax", [ln["16"], *other])

    withholding = traced_sum(
        "1040:line25 federal income tax withheld",
        [Traced(label=f"w2:{w.employer}.withheld", value=w.federal_income_tax_withheld)
         for w in inputs.w2s]
        + [Traced(label=f"1099int:{f.payer}.withheld", value=f.federal_income_tax_withheld)
           for f in inputs.forms_1099_int]
        + [Traced(label=f"1099div:{f.payer}.withheld", value=f.federal_income_tax_withheld)
           for f in inputs.forms_1099_div],
    )
    estimated = Traced(label="1040:line26 estimated payments", value=inputs.estimated_payments)
    total_payments = traced_sum("1040:line33 total payments", [withholding, estimated])
    ln["25"] = withholding
    ln["26"] = estimated

    balance = Traced(
        label="1040:balance due (negative = refund)",
        value=total_tax.value - total_payments.value,
        inputs=(total_tax, total_payments),
    )
    return Form1040Result(
        lines=MappingProxyType(ln),
        qdcgt=qdcgt_result,
        total_tax=total_tax,
        total_payments=total_payments,
        balance_due=balance,
    )
