"""Washington capital-gains excise tax — an applicability CHECKER.

Plan §6.4: output the determination WITH the computation shown, even when
the answer is "not applicable" — an unexamined exemption is
indistinguishable from a silent omission. 2025 structure (dor.wa.gov):
standard deduction $278,000; 7% on taxable WA gains up to $1,000,000 plus
an additional 2.9% above (tiered, new for 2025).
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from telos.engine.rounding import round_whole_dollar
from telos.engine.trace import Traced
from telos.params import ParamPack

_ZERO = Decimal(0)


@dataclass(frozen=True)
class WaExciseDetermination:
    applicable: bool
    taxable_gain: Decimal
    tax: Decimal
    explanation: Traced


def wa_excise_check(wa_allocable_long_term_gain: Decimal, pack: ParamPack) -> WaExciseDetermination:
    """Long-term, WA-allocable gains only (the statute exempts real estate
    and retirement accounts upstream — the caller passes the allocable base)."""
    deduction = pack.get("standard_deduction")
    taxable = max(wa_allocable_long_term_gain - deduction.value, _ZERO)
    if taxable == 0:
        expl = Traced(
            label="wa_excise:not applicable",
            value=_ZERO,
            sources=(
                f"WA capital gains excise: allocable LT gain "
                f"{wa_allocable_long_term_gain} <= standard deduction "
                f"{deduction.value} -> no filing obligation from this check",
            ),
            inputs=(deduction,),
        )
        return WaExciseDetermination(False, _ZERO, _ZERO, expl)

    rate = pack.get("rate")
    threshold = pack.get("surcharge_threshold")
    surcharge = pack.get("surcharge_rate")
    # 7% applies to ALL taxable gains; the 2.9% surcharge stacks on the
    # excess over $1M (9.9% marginal above the threshold, per the dor.wa.gov
    # tiered-rates notice).
    base_tax = rate.value * taxable
    extra = surcharge.value * max(taxable - threshold.value, _ZERO)
    tax = round_whole_dollar(base_tax + extra)
    expl = Traced(
        label="wa_excise:APPLICABLE — file the WA capital gains return",
        value=tax,
        sources=(
            f"taxable {taxable} = gain - deduction {deduction.value}; "
            f"7% to {threshold.value} + 2.9% above (2025 tiered rates)",
        ),
        inputs=(deduction, rate, threshold, surcharge),
    )
    return WaExciseDetermination(True, taxable, tax, expl)
