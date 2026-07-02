"""Form 8995-A — QBI deduction with the wage/UBIA limitation, per the 2025 form.

Structure fetched 2026-07-02; the printed thresholds ($197,300 / $247,300
single, $50,000 range) match the parameter pack's Rev. Proc. 2024-40 §2.27
values, which the computation reads from the pack (never inline).

Three regimes per the form's own gates:
- taxable income <= threshold: line 13 = line 3 (skip the limitation);
- within the phase-in range AND line 10 < line 3: Part III phased reduction;
- above the range: line 11 = smaller of line 3 or the wage/UBIA limit —
  for rentals (W-2 wages 0) the 2.5%-of-UBIA leg is what keeps the
  deduction alive.

Coverage guards (fail loud, never approximate):
- an SSTB business with taxable income above the threshold (exclusion /
  phase-out logic not implemented);
- mixed-sign QBI across businesses (Schedule C (8995-A) negative-QBI
  allocation not implemented); all-negative QBI returns a zero deduction
  with the carryforward surfaced;
- a section 199A(g) DPAD amount (line 38, co-op patrons only).
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from decimal import Decimal
from types import MappingProxyType

from pydantic import BaseModel, ConfigDict, Field

from telos.engine.guard import CoverageError
from telos.engine.rounding import round_whole_dollar
from telos.engine.trace import Traced
from telos.models import FilingStatus
from telos.params import ParamPack

FORM_CITE = "2025 Form 8995-A"
_ZERO = Decimal(0)


class QbiBusiness(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    name: str = Field(min_length=1)
    qbi: Decimal = Field(description="line 2 — qualified business income (may be a loss)")
    w2_wages: Decimal = Field(default=_ZERO, ge=0, description="line 4")
    ubia: Decimal = Field(default=_ZERO, ge=0, description="line 7 — unadjusted basis")
    is_sstb: bool = False


class Form8995AInputs(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    filing_status: FilingStatus
    businesses: tuple[QbiBusiness, ...] = Field(min_length=1)
    taxable_income_before_qbi: Decimal = Field(ge=0, description="lines 20/33")
    net_capital_gain_plus_qualified_dividends: Decimal = Field(
        default=_ZERO, ge=0, description="line 34"
    )
    reit_ptp_income: Decimal = Field(default=_ZERO, description="line 28")
    reit_ptp_carryforward: Decimal = Field(default=_ZERO, le=0, description="line 29 (<= 0)")
    dpad_199ag: Decimal = Field(default=_ZERO, ge=0, description="line 38 — guard only")


@dataclass(frozen=True)
class Form8995AResult:
    per_business: Mapping[str, Mapping[int, Traced]]
    lines: Mapping[int, Traced]  # Part IV
    deduction: Traced  # line 39 -> Form 1040 line 13
    negative_qbi_carryforward: Decimal  # informational (all-negative case)


def _line(n: int, value: Decimal, *inputs: Traced, note: str = "") -> Traced:
    src = f"{FORM_CITE}, line {n}" + (f" ({note})" if note else "")
    return Traced(label=f"8995A:line{n}", value=value, sources=(src,), inputs=tuple(inputs))


def form8995a(inputs: Form8995AInputs, pack: ParamPack) -> Form8995AResult:
    if inputs.dpad_199ag > 0:
        raise CoverageError("Form 8995-A line 38 (DPAD, co-op patrons) not implemented")

    fs = inputs.filing_status.value
    threshold = pack.get(f"qbi.threshold.{fs}")
    range_top = pack.get(f"qbi.phase_in_range_top.{fs}")
    ti = inputs.taxable_income_before_qbi

    signs = {b.qbi > 0 for b in inputs.businesses if b.qbi != 0}
    if signs == {True, False}:
        raise CoverageError(
            "mixed-sign QBI across businesses — Schedule C (Form 8995-A) "
            "negative-QBI allocation is not implemented; manual review"
        )
    if all(b.qbi <= 0 for b in inputs.businesses):
        carryforward = sum((b.qbi for b in inputs.businesses), start=_ZERO)
        zero = _line(39, _ZERO, note="all QBI negative — deduction 0, loss carries forward")
        return Form8995AResult(
            per_business=MappingProxyType({}),
            lines=MappingProxyType({39: zero}),
            deduction=zero,
            negative_qbi_carryforward=carryforward,
        )

    per_business: dict[str, dict[int, Traced]] = {}
    total_component = _ZERO
    component_traces: list[Traced] = []
    for biz in inputs.businesses:
        if biz.is_sstb and ti > threshold.value:
            raise CoverageError(
                f"{biz.name!r} is an SSTB with taxable income above the threshold — "
                f"the SSTB exclusion/phase-out is not implemented; manual review"
            )
        ln: dict[int, Traced] = {}
        ln[2] = _line(2, biz.qbi, note=biz.name)
        ln[3] = _line(3, round_whole_dollar(ln[2].value * Decimal("0.20")), ln[2],
                      note="20% of QBI")
        if ti <= threshold.value:
            ln[13] = _line(13, ln[3].value, ln[3], threshold,
                           note="taxable income at or below threshold — line 3 directly")
        else:
            ln[4] = _line(4, biz.w2_wages)
            ln[5] = _line(5, round_whole_dollar(ln[4].value * Decimal("0.50")), ln[4])
            ln[6] = _line(6, round_whole_dollar(ln[4].value * Decimal("0.25")), ln[4])
            ln[7] = _line(7, biz.ubia)
            ln[8] = _line(8, round_whole_dollar(ln[7].value * Decimal("0.025")), ln[7],
                          note="2.5% of UBIA")
            ln[9] = _line(9, ln[6].value + ln[8].value, ln[6], ln[8])
            ln[10] = _line(10, max(ln[5].value, ln[9].value), ln[5], ln[9])
            ln[11] = _line(11, min(ln[3].value, ln[10].value), ln[3], ln[10],
                           note="wage/UBIA limitation")
            in_phase_range = ti <= range_top.value
            if in_phase_range and ln[10].value < ln[3].value:
                phase_range = range_top.value - threshold.value
                pct = (ti - threshold.value) / phase_range
                ln[19] = _line(19, ln[3].value - ln[10].value, ln[3], ln[10])
                ln[25] = _line(25, round_whole_dollar(ln[19].value * pct), ln[19],
                               threshold, range_top,
                               note=f"phase-in {pct:.4f} of the reduction")
                ln[26] = _line(26, ln[3].value - ln[25].value, ln[3], ln[25])
                ln[12] = _line(12, ln[26].value, ln[26])
                ln[13] = _line(13, max(ln[11].value, ln[12].value), ln[11], ln[12])
            else:
                ln[13] = _line(13, ln[11].value, ln[11],
                               note="above phase-in range — fully limited")
        ln[15] = _line(15, ln[13].value, ln[13], note="QBI component (no patron reduction)")
        per_business[biz.name] = ln
        total_component += ln[15].value
        component_traces.append(ln[15])

    pt: dict[int, Traced] = {}
    pt[27] = _line(27, total_component, *component_traces)
    pt[28] = _line(28, inputs.reit_ptp_income)
    pt[29] = _line(29, inputs.reit_ptp_carryforward)
    pt[30] = _line(30, max(pt[28].value + pt[29].value, _ZERO), pt[28], pt[29], note="floor 0")
    pt[31] = _line(31, round_whole_dollar(pt[30].value * Decimal("0.20")), pt[30])
    pt[32] = _line(32, pt[27].value + pt[31].value, pt[27], pt[31])
    pt[33] = _line(33, ti)
    pt[34] = _line(34, inputs.net_capital_gain_plus_qualified_dividends)
    pt[35] = _line(35, max(pt[33].value - pt[34].value, _ZERO), pt[33], pt[34], note="floor 0")
    pt[36] = _line(36, round_whole_dollar(pt[35].value * Decimal("0.20")), pt[35],
                   note="income limitation")
    pt[37] = _line(37, min(pt[32].value, pt[36].value), pt[32], pt[36])
    pt[39] = _line(39, pt[37].value, pt[37], note="to Form 1040 line 13")

    return Form8995AResult(
        per_business=MappingProxyType(
            {k: MappingProxyType(v) for k, v in per_business.items()}
        ),
        lines=MappingProxyType(pt),
        deduction=pt[39],
        negative_qbi_carryforward=_ZERO,
    )
