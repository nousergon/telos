"""Schedule D — capital gains roll-up, per the fetched 2025 form.

Line map (2025): Part I nets short-term (1b = boxes A|G, 2 = B|H, 3 = C|I,
plus lines 4-6) into line 7; Part II nets long-term (8b = D|J, 9 = E|K,
10 = F|L, plus 11-14) into line 15; Part III line 16 = 7 + 15 -> Form 1040
line 7a (gain), or the loss limited to $3,000 ($1,500 MFS) via line 21.

Outputs feed the existing seams:
- ``line7a`` -> ``Form1040Inputs.capital_gain_line7``;
- ``qdcgt_net_capital_gain`` (smaller of lines 15/16 when both are gains,
  else 0 — the QDCGT worksheet's line-3 rule) ->
  ``Form1040Inputs.qdcgt_net_capital_gain``;
- ``line7a`` is also Form 8960 line 5a for the NIIT module.

Coverage guard: a non-zero 28%-rate gain (line 18) or unrecaptured §1250
gain (line 19) routes tax to the Schedule D Tax Worksheet, which this engine
does not implement — fail loud (line 20's own gate).
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from decimal import Decimal
from types import MappingProxyType

from pydantic import BaseModel, ConfigDict, Field

from telos.contracts import Form8949Box, RealizedLots
from telos.engine.form8949 import BoxTotals, form8949_totals
from telos.engine.guard import CoverageError
from telos.engine.trace import Traced
from telos.models import FilingStatus

FORM_CITE = "2025 Schedule D (Form 1040)"
_ZERO = Decimal(0)
_LOSS_LIMIT = Decimal(3_000)  # printed on Schedule D line 21
_LOSS_LIMIT_MFS = Decimal(1_500)

_ST_LINES: dict[str, tuple[Form8949Box, Form8949Box]] = {
    "1b": (Form8949Box.A, Form8949Box.G),
    "2": (Form8949Box.B, Form8949Box.H),
    "3": (Form8949Box.C, Form8949Box.I),
}
_LT_LINES: dict[str, tuple[Form8949Box, Form8949Box]] = {
    "8b": (Form8949Box.D, Form8949Box.J),
    "9": (Form8949Box.E, Form8949Box.K),
    "10": (Form8949Box.F, Form8949Box.L),
}


class ScheduleDInputs(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    filing_status: FilingStatus
    realized: RealizedLots
    st_other_gains: Decimal = Field(default=_ZERO, description="line 4 (6252/4684/6781/8824)")
    st_passthrough: Decimal = Field(default=_ZERO, description="line 5 (K-1s)")
    st_loss_carryover: Decimal = Field(default=_ZERO, ge=0, description="line 6, as positive")
    lt_other_gains: Decimal = Field(default=_ZERO, description="line 11")
    lt_passthrough: Decimal = Field(default=_ZERO, description="line 12 (K-1s)")
    capital_gain_distributions: Decimal = Field(default=_ZERO, ge=0, description="line 13")
    lt_loss_carryover: Decimal = Field(default=_ZERO, ge=0, description="line 14, as positive")
    gain_28_percent: Decimal = Field(default=_ZERO, ge=0, description="line 18 worksheet result")
    unrecaptured_1250: Decimal = Field(default=_ZERO, ge=0, description="line 19 worksheet result")


@dataclass(frozen=True)
class ScheduleDResult:
    lines: Mapping[str, Traced]
    box_totals: tuple[BoxTotals, ...]
    line7a: Traced  # Form 1040 line 7a (and Form 8960 line 5a)
    qdcgt_net_capital_gain: Traced  # QDCGT worksheet line 3


def _line(n: str, value: Decimal, *inputs: Traced, note: str = "") -> Traced:
    src = f"{FORM_CITE}, line {n}" + (f" ({note})" if note else "")
    return Traced(label=f"schD:line{n}", value=value, sources=(src,), inputs=tuple(inputs))


def schedule_d(inputs: ScheduleDInputs) -> ScheduleDResult:
    if inputs.gain_28_percent > 0 or inputs.unrecaptured_1250 > 0:
        raise CoverageError(
            "Schedule D line 18/19 is non-zero: tax routes to the Schedule D Tax "
            "Worksheet (line 20 gate), which this engine does not implement — "
            "manual review required."
        )

    rows = form8949_totals(inputs.realized)
    by_box = {r.box: r for r in rows}

    def line_from_boxes(n: str, boxes: tuple[Form8949Box, Form8949Box]) -> Traced:
        parts = [by_box[b].gain for b in boxes if b in by_box]
        value = sum((p.value for p in parts), start=_ZERO)
        return _line(n, value, *parts, note=f"boxes {boxes[0].value}|{boxes[1].value}")

    ln: dict[str, Traced] = {}
    for n, boxes in _ST_LINES.items():
        ln[n] = line_from_boxes(n, boxes)
    ln["4"] = _line("4", inputs.st_other_gains)
    ln["5"] = _line("5", inputs.st_passthrough)
    ln["6"] = _line("6", -inputs.st_loss_carryover, note="loss carryover")
    ln["7"] = _line(
        "7",
        ln["1b"].value + ln["2"].value + ln["3"].value
        + ln["4"].value + ln["5"].value + ln["6"].value,
        ln["1b"], ln["2"], ln["3"], ln["4"], ln["5"], ln["6"],
        note="net short-term",
    )

    for n, boxes in _LT_LINES.items():
        ln[n] = line_from_boxes(n, boxes)
    ln["11"] = _line("11", inputs.lt_other_gains)
    ln["12"] = _line("12", inputs.lt_passthrough)
    ln["13"] = _line("13", inputs.capital_gain_distributions)
    ln["14"] = _line("14", -inputs.lt_loss_carryover, note="loss carryover")
    ln["15"] = _line(
        "15",
        ln["8b"].value + ln["9"].value + ln["10"].value
        + ln["11"].value + ln["12"].value + ln["13"].value + ln["14"].value,
        ln["8b"], ln["9"], ln["10"], ln["11"], ln["12"], ln["13"], ln["14"],
        note="net long-term",
    )

    ln["16"] = _line("16", ln["7"].value + ln["15"].value, ln["7"], ln["15"])

    if ln["16"].value >= 0:
        line7a = ln["16"].derive("schD:line7a to 1040", ln["16"].value)
    else:
        limit = (
            _LOSS_LIMIT_MFS
            if inputs.filing_status is FilingStatus.MARRIED_FILING_SEPARATELY
            else _LOSS_LIMIT
        )
        allowed = -min(-ln["16"].value, limit)
        line7a = Traced(
            label="schD:line7a to 1040",
            value=allowed,
            sources=(f"{FORM_CITE}, line 21 (loss limited to {limit})",),
            inputs=(ln["16"],),
        )
    ln["21"] = line7a

    both_gains = ln["15"].value > 0 and ln["16"].value > 0
    qdcgt_ncg = Traced(
        label="schD:qdcgt net capital gain (smaller of 15/16)",
        value=min(ln["15"].value, ln["16"].value) if both_gains else _ZERO,
        sources=(
            "QDCGT worksheet line 3: smaller of Schedule D lines 15/16; "
            "0 if either is blank or a loss",
        ),
        inputs=(ln["15"], ln["16"]),
    )
    return ScheduleDResult(
        lines=MappingProxyType(ln),
        box_totals=tuple(rows),
        line7a=line7a,
        qdcgt_net_capital_gain=qdcgt_ncg,
    )
