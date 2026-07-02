"""Schedule A — itemized deductions, per the 2025 form (fetched 2026-07-02).

The 2025 line 5e carries the OBBBA SALT limitation: the smaller of line 5d or
$40,000 ($20,000 MFS), REDUCED when MAGI exceeds $500,000 ($250,000 MFS) by
30% of the excess, but never below $10,000 ($5,000 MFS) — cap, thresholds,
rate, and floor all from the parameter pack (cited to the 2025 Schedule A
instructions, line 5e).

Coverage guards (fail loud, never silently mis-deduct):
- charitable cash gifts above 60% of AGI, or non-cash above 30%, trigger the
  Pub. 526 AGI-limitation worksheets this module does not implement — refuse
  rather than deduct an unlimited amount;
- ``choose_deduction`` decides standard-vs-itemized with BOTH totals named in
  the provenance, so the choice is auditable.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from decimal import Decimal
from types import MappingProxyType

from pydantic import BaseModel, ConfigDict, Field

from telos.engine.guard import CoverageError
from telos.engine.trace import Traced
from telos.models import FilingStatus
from telos.params import ParamPack

FORM_CITE = "2025 Schedule A (Form 1040)"
SALT_CITE = "2025 Instructions for Schedule A (Form 1040), line 5e"
_ZERO = Decimal(0)
_MEDICAL_FLOOR_RATE = Decimal("0.075")  # printed on Schedule A line 3
_CASH_GIFT_AGI_LIMIT = Decimal("0.60")  # IRC §170(b)(1)(G); Pub. 526
_NONCASH_GIFT_AGI_LIMIT = Decimal("0.30")


class ScheduleAInputs(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    filing_status: FilingStatus
    agi: Decimal = Field(ge=0, description="Form 1040 line 11b — feeds lines 2 and 5e")
    medical_expenses: Decimal = Field(default=_ZERO, ge=0, description="line 1")
    state_local_income_or_sales_tax: Decimal = Field(default=_ZERO, ge=0, description="line 5a")
    real_estate_taxes: Decimal = Field(default=_ZERO, ge=0, description="line 5b")
    personal_property_taxes: Decimal = Field(default=_ZERO, ge=0, description="line 5c")
    other_taxes: Decimal = Field(default=_ZERO, ge=0, description="line 6")
    mortgage_interest_1098: Decimal = Field(default=_ZERO, ge=0, description="line 8a")
    mortgage_interest_no_1098: Decimal = Field(default=_ZERO, ge=0, description="line 8b")
    points_no_1098: Decimal = Field(default=_ZERO, ge=0, description="line 8c")
    investment_interest: Decimal = Field(default=_ZERO, ge=0, description="line 9")
    charitable_cash: Decimal = Field(default=_ZERO, ge=0, description="line 11")
    charitable_noncash: Decimal = Field(default=_ZERO, ge=0, description="line 12")
    charitable_carryover: Decimal = Field(default=_ZERO, ge=0, description="line 13")
    casualty_losses: Decimal = Field(default=_ZERO, ge=0, description="line 15")
    other_itemized: Decimal = Field(default=_ZERO, ge=0, description="line 16")


@dataclass(frozen=True)
class ScheduleAResult:
    lines: Mapping[str, Traced]
    total_itemized: Traced  # line 17


def _line(n: str, value: Decimal, *inputs: Traced, note: str = "") -> Traced:
    src = f"{FORM_CITE}, line {n}" + (f" ({note})" if note else "")
    return Traced(label=f"schA:line{n}", value=value, sources=(src,), inputs=tuple(inputs))


def _salt_cap(fs: FilingStatus, magi: Traced, pack: ParamPack) -> Traced:
    """The line-5e limitation with the OBBBA phase-down."""
    mfs = fs is FilingStatus.MARRIED_FILING_SEPARATELY
    cap = pack.get("salt.cap_married_filing_separately" if mfs else "salt.cap")
    threshold = pack.get(
        "salt.magi_phase_down_threshold_mfs" if mfs else "salt.magi_phase_down_threshold"
    )
    floor = pack.get("salt.floor_married_filing_separately" if mfs else "salt.floor")
    rate = pack.get("salt.phase_down_rate")
    if magi.value <= threshold.value:
        return Traced(
            label="schA:salt_cap", value=cap.value, sources=(SALT_CITE,),
            inputs=(cap, threshold, magi),
        )
    reduction = rate.value * (magi.value - threshold.value)
    reduced = max(cap.value - reduction, floor.value)
    return Traced(
        label="schA:salt_cap",
        value=reduced,
        sources=(SALT_CITE + " (phase-down: cap minus 30% of MAGI excess, not below the floor)",),
        inputs=(cap, threshold, floor, rate, magi),
    )


def schedule_a(inputs: ScheduleAInputs, pack: ParamPack) -> ScheduleAResult:
    if inputs.charitable_cash > inputs.agi * _CASH_GIFT_AGI_LIMIT:
        raise CoverageError(
            f"charitable cash gifts ({inputs.charitable_cash}) exceed 60% of AGI — the "
            f"Pub. 526 AGI-limitation worksheet is not implemented; refusing to deduct "
            f"an unlimited amount. Route to manual review."
        )
    if inputs.charitable_noncash > inputs.agi * _NONCASH_GIFT_AGI_LIMIT:
        raise CoverageError(
            f"non-cash charitable gifts ({inputs.charitable_noncash}) exceed 30% of AGI — "
            f"Pub. 526 limitation worksheet not implemented; route to manual review."
        )

    ln: dict[str, Traced] = {}
    agi = Traced(label="1040:line11b AGI", value=inputs.agi)

    # Medical (lines 1-4)
    ln["1"] = _line("1", inputs.medical_expenses)
    ln["2"] = _line("2", agi.value, agi)
    ln["3"] = _line("3", agi.value * _MEDICAL_FLOOR_RATE, ln["2"], note="7.5% of AGI")
    ln["4"] = _line("4", max(ln["1"].value - ln["3"].value, _ZERO), ln["1"], ln["3"],
                    note="floor 0")

    # Taxes (lines 5-7)
    ln["5a"] = _line("5a", inputs.state_local_income_or_sales_tax)
    ln["5b"] = _line("5b", inputs.real_estate_taxes)
    ln["5c"] = _line("5c", inputs.personal_property_taxes)
    ln["5d"] = _line("5d", ln["5a"].value + ln["5b"].value + ln["5c"].value,
                     ln["5a"], ln["5b"], ln["5c"])
    cap = _salt_cap(inputs.filing_status, agi, pack)
    ln["5e"] = _line("5e", min(ln["5d"].value, cap.value), ln["5d"], cap,
                     note="smaller of 5d or the OBBBA-limited cap")
    ln["6"] = _line("6", inputs.other_taxes)
    ln["7"] = _line("7", ln["5e"].value + ln["6"].value, ln["5e"], ln["6"])

    # Interest (lines 8-10)
    ln["8e"] = _line(
        "8e",
        inputs.mortgage_interest_1098 + inputs.mortgage_interest_no_1098
        + inputs.points_no_1098,
        note="8a+8b+8c",
    )
    ln["9"] = _line("9", inputs.investment_interest)
    ln["10"] = _line("10", ln["8e"].value + ln["9"].value, ln["8e"], ln["9"])

    # Charity (lines 11-14)
    ln["11"] = _line("11", inputs.charitable_cash)
    ln["12"] = _line("12", inputs.charitable_noncash)
    ln["13"] = _line("13", inputs.charitable_carryover)
    ln["14"] = _line("14", ln["11"].value + ln["12"].value + ln["13"].value,
                     ln["11"], ln["12"], ln["13"])

    ln["15"] = _line("15", inputs.casualty_losses)
    ln["16"] = _line("16", inputs.other_itemized)
    ln["17"] = _line(
        "17",
        ln["4"].value + ln["7"].value + ln["10"].value + ln["14"].value
        + ln["15"].value + ln["16"].value,
        ln["4"], ln["7"], ln["10"], ln["14"], ln["15"], ln["16"],
        note="total itemized — to Form 1040 line 12",
    )
    return ScheduleAResult(lines=MappingProxyType(ln), total_itemized=ln["17"])


def choose_deduction(
    itemized: ScheduleAResult, filing_status: FilingStatus, pack: ParamPack
) -> Traced:
    """The greater of itemized vs standard, with both totals in the provenance."""
    std = pack.get(f"standard_deduction.{filing_status.value}")
    it = itemized.total_itemized
    if it.value >= std.value:
        winner, note = it, f"itemized {it.value} >= standard {std.value}"
    else:
        winner, note = std, f"standard {std.value} > itemized {it.value}"
    return Traced(
        label="1040:line12 deduction choice",
        value=winner.value,
        sources=(f"Form 1040 line 12 ({note})",),
        inputs=(it, std),
    )
