"""Form 8959 — Additional Medicare Tax, line-for-line per the 2025 form.

Structure fetched from the 2025 Form 8959 (irs.gov, 2026-07-02). Two outputs
matter downstream:
- line 18: total Additional Medicare Tax -> Schedule 2 line 11 (an
  ``other_taxes`` entry in the 1040 assembly);
- line 24: Additional Medicare Tax *withholding* -> Form 1040 line 25c (it is
  withholding CREDIT, not tax — omitting it overstates the balance due).

Fail-loud rule: a W-2 without box 5 (``medicare_wages``) refuses to compute —
box 1 wages are NOT a valid proxy (pre-tax 401(k) deferrals make them differ).
Parts II (self-employment) and III (RRTA) are implemented per the form; their
inputs default to zero until the Schedule SE arc exists.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from decimal import Decimal
from types import MappingProxyType

from telos.engine.rounding import round_whole_dollar
from telos.engine.trace import Traced, traced_sum
from telos.models import W2, FilingStatus
from telos.params import ParamPack

FORM_CITE = "2025 Form 8959"
_ZERO = Decimal(0)
_REGULAR_MEDICARE_RATE = Decimal("0.0145")  # printed on Form 8959 line 21


class MissingMedicareWagesError(ValueError):
    """A W-2 lacks box 5 — refusing to guess (box 1 is not a proxy)."""


@dataclass(frozen=True)
class Form8959Result:
    lines: Mapping[int, Traced]
    additional_medicare_tax: Traced  # line 18 -> Schedule 2 line 11
    additional_withholding: Traced  # line 24 -> Form 1040 line 25c


def _line(n: int, value: Decimal, *inputs: Traced, note: str = "") -> Traced:
    src = f"{FORM_CITE}, line {n}" + (f" ({note})" if note else "")
    return Traced(label=f"8959:line{n}", value=value, sources=(src,), inputs=tuple(inputs))


def form8959(
    *,
    w2s: Sequence[W2],
    filing_status: FilingStatus,
    pack: ParamPack,
    self_employment_income: Decimal = _ZERO,
    rrta_compensation: Decimal = _ZERO,
    rrta_additional_withholding: Decimal = _ZERO,
) -> Form8959Result:
    for w in w2s:
        if w.medicare_wages is None or w.medicare_tax_withheld is None:
            raise MissingMedicareWagesError(
                f"W-2 {w.employer!r} lacks box 5/6 (medicare_wages / "
                f"medicare_tax_withheld); Form 8959 refuses to run without them"
            )

    threshold = pack.get(f"additional_medicare.threshold.{filing_status.value}")
    rate = pack.get("additional_medicare.rate")
    ln: dict[int, Traced] = {}

    # Part I — Medicare wages
    ln[1] = traced_sum(
        "8959:line1",
        [Traced(label=f"w2:{w.employer}.box5", value=w.medicare_wages) for w in w2s],
        sources=(f"{FORM_CITE}, line 1 (W-2 box 5 total)",),
    )
    ln[2] = _line(2, _ZERO, note="Form 4137 unreported tips — none")
    ln[3] = _line(3, _ZERO, note="Form 8919 wages — none")
    ln[4] = _line(4, ln[1].value + ln[2].value + ln[3].value, ln[1], ln[2], ln[3])
    ln[5] = _line(5, threshold.value, threshold)
    ln[6] = _line(6, max(ln[4].value - ln[5].value, _ZERO), ln[4], ln[5], note="floor 0")
    ln[7] = _line(
        7, round_whole_dollar(ln[6].value * rate.value), ln[6], rate, note="0.9% rate"
    )

    # Part II — self-employment income (Schedule SE arc; zero until it exists)
    ln[8] = _line(8, max(self_employment_income, _ZERO), note="Schedule SE line 6, loss -> 0")
    ln[9] = _line(9, threshold.value, threshold)
    ln[10] = _line(10, ln[4].value, ln[4])
    ln[11] = _line(11, max(ln[9].value - ln[10].value, _ZERO), ln[9], ln[10], note="floor 0")
    ln[12] = _line(12, max(ln[8].value - ln[11].value, _ZERO), ln[8], ln[11], note="floor 0")
    ln[13] = _line(
        13, round_whole_dollar(ln[12].value * rate.value), ln[12], rate, note="0.9% rate"
    )

    # Part III — RRTA compensation
    ln[14] = _line(14, rrta_compensation, note="W-2 box 14 RRTA")
    ln[15] = _line(15, threshold.value, threshold)
    ln[16] = _line(16, max(ln[14].value - ln[15].value, _ZERO), ln[14], ln[15], note="floor 0")
    ln[17] = _line(
        17, round_whole_dollar(ln[16].value * rate.value), ln[16], rate, note="0.9% rate"
    )

    # Part IV — total
    ln[18] = _line(
        18, ln[7].value + ln[13].value + ln[17].value, ln[7], ln[13], ln[17],
        note="to Schedule 2, line 11",
    )

    # Part V — withholding reconciliation
    ln[19] = traced_sum(
        "8959:line19",
        [Traced(label=f"w2:{w.employer}.box6", value=w.medicare_tax_withheld) for w in w2s],
        sources=(f"{FORM_CITE}, line 19 (W-2 box 6 total)",),
    )
    ln[20] = _line(20, ln[1].value, ln[1])
    ln[21] = _line(
        21, round_whole_dollar(ln[20].value * _REGULAR_MEDICARE_RATE), ln[20],
        note="1.45% regular Medicare withholding",
    )
    ln[22] = _line(22, max(ln[19].value - ln[21].value, _ZERO), ln[19], ln[21], note="floor 0")
    ln[23] = _line(23, rrta_additional_withholding, note="W-2 box 14 RRTA additional withholding")
    ln[24] = _line(
        24, ln[22].value + ln[23].value, ln[22], ln[23],
        note="to Form 1040 line 25c (withholding credit)",
    )
    return Form8959Result(
        lines=MappingProxyType(ln),
        additional_medicare_tax=ln[18],
        additional_withholding=ln[24],
    )
