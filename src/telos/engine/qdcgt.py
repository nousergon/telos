"""Qualified Dividends and Capital Gain Tax Worksheet — Line 16.

Implemented line-for-line from the 2025 Instructions for Form 1040, p. 38
(fetched 2026-07-02), all 25 lines under their printed semantics — never an
algebraic shortcut. Notable 2025 facts confirmed by the fetch: there is no
investment-interest (Form 4952) adjustment line this year (line 5 is directly
line 1 minus line 4), and lines 22/24 use the Tax Table below $100,000 / Tax
Computation Worksheet at or above (see ``telos.engine.tax_lookup``).

Inputs the caller must supply per the worksheet's own text:
- line 2: Form 1040 line 3a (qualified dividends).
- line 3: if filing Schedule D, the smaller of Schedule D lines 15 or 16
  (zero if either is blank or a loss); otherwise Form 1040 line 7a. The
  Schedule D module (telos-ops#4) produces this; it is never negative.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from decimal import Decimal
from types import MappingProxyType

from telos.engine.tax_lookup import line16_tax
from telos.engine.trace import Traced
from telos.models import FilingStatus
from telos.params import ParamPack

WORKSHEET_CITE = (
    "2025 Form 1040 instructions, Qualified Dividends and Capital Gain Tax Worksheet—Line 16"
)

_ZERO = Decimal(0)


@dataclass(frozen=True)
class QdcgtResult:
    """All 25 worksheet lines, plus the final tax (line 25)."""

    lines: Mapping[int, Traced]
    tax: Traced


def _line(n: int, value: Decimal, *inputs: Traced, note: str = "") -> Traced:
    src = f"{WORKSHEET_CITE}, line {n}" + (f" ({note})" if note else "")
    return Traced(label=f"qdcgt:line{n}", value=value, sources=(src,), inputs=tuple(inputs))


def qdcgt_worksheet(
    *,
    taxable_income: Traced,
    qualified_dividends: Traced,
    net_capital_gain: Traced,
    filing_status: FilingStatus,
    pack: ParamPack,
) -> QdcgtResult:
    """Compute line 16 tax per the worksheet. All amounts must be >= 0
    except none: the worksheet's own floors handle interior negatives."""
    for t in (taxable_income, qualified_dividends, net_capital_gain):
        if t.value < 0:
            raise ValueError(f"{t.label}: worksheet inputs must be >= 0, got {t.value}")

    ln: dict[int, Traced] = {}
    ln[1] = _line(1, taxable_income.value, taxable_income, note="Form 1040 line 15")
    ln[2] = _line(2, qualified_dividends.value, qualified_dividends, note="Form 1040 line 3a")
    ln[3] = _line(
        3, net_capital_gain.value, net_capital_gain,
        note="smaller of Sch D lines 15/16, or Form 1040 line 7a",
    )
    ln[4] = _line(4, ln[2].value + ln[3].value, ln[2], ln[3])
    ln[5] = _line(5, max(ln[1].value - ln[4].value, _ZERO), ln[1], ln[4], note="floor 0")

    zero_max = pack.get(f"ltcg.zero_rate_max.{filing_status.value}")
    ln[6] = _line(6, zero_max.value, zero_max)
    ln[7] = _line(7, min(ln[1].value, ln[6].value), ln[1], ln[6])
    ln[8] = _line(8, min(ln[5].value, ln[7].value), ln[5], ln[7])
    ln[9] = _line(9, ln[7].value - ln[8].value, ln[7], ln[8], note="taxed at 0%")
    ln[10] = _line(10, min(ln[1].value, ln[4].value), ln[1], ln[4])
    ln[11] = _line(11, ln[9].value, ln[9])
    ln[12] = _line(12, ln[10].value - ln[11].value, ln[10], ln[11])

    fifteen_max = pack.get(f"ltcg.fifteen_rate_max.{filing_status.value}")
    ln[13] = _line(13, fifteen_max.value, fifteen_max)
    ln[14] = _line(14, min(ln[1].value, ln[13].value), ln[1], ln[13])
    ln[15] = _line(15, ln[5].value + ln[9].value, ln[5], ln[9])
    ln[16] = _line(16, max(ln[14].value - ln[15].value, _ZERO), ln[14], ln[15], note="floor 0")
    ln[17] = _line(17, min(ln[12].value, ln[16].value), ln[12], ln[16])
    ln[18] = _line(18, ln[17].value * Decimal("0.15"), ln[17], note="15% rate")
    ln[19] = _line(19, ln[9].value + ln[17].value, ln[9], ln[17])
    ln[20] = _line(20, ln[10].value - ln[19].value, ln[10], ln[19])
    ln[21] = _line(21, ln[20].value * Decimal("0.20"), ln[20], note="20% rate")

    schedule = pack.brackets(f"ordinary_brackets.{filing_status.value}")
    ln[22] = line16_tax("qdcgt:line22", ln[5], schedule)
    ln[23] = _line(23, ln[18].value + ln[21].value + ln[22].value, ln[18], ln[21], ln[22])
    ln[24] = line16_tax("qdcgt:line24", ln[1], schedule)
    ln[25] = _line(
        25, min(ln[23].value, ln[24].value), ln[23], ln[24],
        note="smaller of 23 or 24 — Form 1040 line 16",
    )
    return QdcgtResult(lines=MappingProxyType(ln), tax=ln[25])
