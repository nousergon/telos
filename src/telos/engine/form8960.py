"""Form 8960 — Net Investment Income Tax (individuals), per the 2025 form.

Structure fetched from the 2025 Form 8960 (irs.gov, 2026-07-02). Individuals
path only (lines 1-17); the estates-and-trusts section (18a-21) is out of the
engine's declared universe and callers never reach it.

Inputs arrive as a typed model so the 1040 assembly and the Schedule E/D
modules can populate them; every line is ``Traced``. Line 9b (state/local
income tax allocable to investment income) exists as an input — a WA-resident
return leaves it zero, but the line is form-real and stays explicit.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from decimal import Decimal
from types import MappingProxyType

from pydantic import BaseModel, ConfigDict, Field

from telos.engine.rounding import round_whole_dollar
from telos.engine.trace import Traced
from telos.models import FilingStatus
from telos.params import ParamPack

FORM_CITE = "2025 Form 8960"
_ZERO = Decimal(0)


class Form8960Inputs(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    filing_status: FilingStatus
    taxable_interest: Decimal = Field(default=_ZERO, ge=0, description="line 1")
    ordinary_dividends: Decimal = Field(default=_ZERO, ge=0, description="line 2")
    annuities: Decimal = Field(default=_ZERO, ge=0, description="line 3")
    rental_and_passthrough: Decimal = Field(default=_ZERO, description="line 4a (may be a loss)")
    non_section_1411_adjustment: Decimal = Field(default=_ZERO, description="line 4b")
    net_gain: Decimal = Field(default=_ZERO, description="line 5a (may be a loss)")
    non_nii_gain_adjustment: Decimal = Field(default=_ZERO, description="line 5b")
    investment_expenses: Decimal = Field(default=_ZERO, ge=0, description="line 9a+9c")
    state_local_tax_allocable: Decimal = Field(default=_ZERO, ge=0, description="line 9b")
    magi: Decimal = Field(ge=0, description="line 13 — MAGI (AGI absent foreign exclusions)")


@dataclass(frozen=True)
class Form8960Result:
    lines: Mapping[str, Traced]
    niit: Traced  # line 17 -> Schedule 2


def _line(n: str, value: Decimal, *inputs: Traced, note: str = "") -> Traced:
    src = f"{FORM_CITE}, line {n}" + (f" ({note})" if note else "")
    return Traced(label=f"8960:line{n}", value=value, sources=(src,), inputs=tuple(inputs))


def form8960(inputs: Form8960Inputs, pack: ParamPack) -> Form8960Result:
    ln: dict[str, Traced] = {}
    ln["1"] = _line("1", inputs.taxable_interest)
    ln["2"] = _line("2", inputs.ordinary_dividends)
    ln["3"] = _line("3", inputs.annuities)
    ln["4a"] = _line("4a", inputs.rental_and_passthrough)
    ln["4b"] = _line("4b", inputs.non_section_1411_adjustment)
    ln["4c"] = _line("4c", ln["4a"].value + ln["4b"].value, ln["4a"], ln["4b"])
    ln["5a"] = _line("5a", inputs.net_gain)
    ln["5b"] = _line("5b", inputs.non_nii_gain_adjustment)
    ln["5d"] = _line("5d", ln["5a"].value + ln["5b"].value, ln["5a"], ln["5b"])
    ln["8"] = _line(
        "8",
        ln["1"].value + ln["2"].value + ln["3"].value + ln["4c"].value + ln["5d"].value,
        ln["1"], ln["2"], ln["3"], ln["4c"], ln["5d"],
        note="total investment income",
    )
    ln["9d"] = _line(
        "9d", inputs.investment_expenses + inputs.state_local_tax_allocable,
        note="9a+9b+9c",
    )
    ln["11"] = _line("11", ln["9d"].value, ln["9d"])
    ln["12"] = _line(
        "12", max(ln["8"].value - ln["11"].value, _ZERO), ln["8"], ln["11"],
        note="net investment income, floor 0",
    )

    threshold = pack.get(f"niit.magi_threshold.{inputs.filing_status.value}")
    rate = pack.get("niit.rate")
    ln["13"] = _line("13", inputs.magi)
    ln["14"] = _line("14", threshold.value, threshold)
    ln["15"] = _line(
        "15", max(ln["13"].value - ln["14"].value, _ZERO), ln["13"], ln["14"], note="floor 0"
    )
    ln["16"] = _line("16", min(ln["12"].value, ln["15"].value), ln["12"], ln["15"])
    ln["17"] = _line(
        "17", round_whole_dollar(ln["16"].value * rate.value), ln["16"], rate,
        note="3.8% — to Schedule 2",
    )
    return Form8960Result(lines=MappingProxyType(ln), niit=ln["17"])
