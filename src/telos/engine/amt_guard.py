"""Form 6251 trigger guard — a SCREEN, never the full AMT engine (plan §2).

The 2025 "Who Must File" test is Form 6251 line 7 vs line 10 — i.e., you only
know by computing tentative minimum tax. This module answers one question
conservatively: *could* AMT plausibly apply to this return? If yes, it raises
``AmtReviewRequired`` and the return routes to manual review — silently
skipping AMT is structurally impossible, and silently mis-computing it is out
of scope by design.

Two layers:

1. **Hard triggers** — items whose AMT treatment requires refiguring this
   engine does not do (Form 6251 lines 2c-3 territory): ISO exercise spread,
   specified private-activity-bond interest, depreciation/passive
   adjustments, general-business or prior-year-AMT credits. Any present ->
   review, no arithmetic.
2. **Arithmetic screen** — for the simple profile (wages/investment/rental
   income, SALT-or-standard-deduction addback as the only preference):
   AMTI ~= taxable income + deduction addback (Form 6251 line 2a semantics);
   exemption per the Exemption Worksheet (25% phaseout above the threshold,
   zero at complete phaseout — pack values verified against the printed
   worksheet); 26%/28% on the ordinary AMT base with preferential income
   taxed at 15%/20% (a screen-level approximation of Part III that IGNORES
   the 0% bracket, overstating TMT — the safe direction). The screen flags
   when TMT reaches 98% of regular tax: a 2% conservatism margin against the
   Part III approximation error.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field

from telos.engine.guard import CoverageError
from telos.engine.trace import Traced
from telos.models import FilingStatus
from telos.params import ParamPack

INSTR_CITE = "2025 Instructions for Form 6251"
_ZERO = Decimal(0)
_PHASEOUT_RATE = Decimal("0.25")  # Exemption Worksheet line 5 (verified in print)
_RATE_26 = Decimal("0.26")
_RATE_28 = Decimal("0.28")
_RATE_15 = Decimal("0.15")
_RATE_20 = Decimal("0.20")
_MARGIN = Decimal("0.98")  # flag when TMT reaches 98% of regular tax


class AmtReviewRequired(CoverageError):
    """The return might owe AMT — route to manual review; never skip silently."""


class AmtGuardInputs(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    filing_status: FilingStatus
    taxable_income: Decimal = Field(ge=0, description="Form 1040 line 15")
    deduction_addback: Decimal = Field(
        ge=0,
        description=(
            "Form 6251 line 2a semantics: Schedule A line 7 if itemizing, "
            "otherwise the standard deduction claimed"
        ),
    )
    preferential_income: Decimal = Field(
        default=_ZERO, ge=0, description="qualified dividends + net capital gain"
    )
    regular_tax: Decimal = Field(ge=0, description="Form 1040 line 16")
    # hard triggers
    iso_exercise_spread: Decimal = Field(default=_ZERO, ge=0, description="6251 line 2i")
    private_activity_bond_interest: Decimal = Field(default=_ZERO, ge=0, description="line 2g")
    other_amt_adjustments: Decimal = Field(
        default=_ZERO, description="any other 2c-3 amount, either sign"
    )
    has_depreciation_or_passive_adjustments: bool = False
    has_general_business_credit: bool = False
    has_prior_year_amt_credit: bool = False


@dataclass(frozen=True)
class AmtScreenResult:
    amti: Decimal
    exemption: Decimal
    tentative_minimum_tax: Decimal
    regular_tax: Decimal
    explanation: Traced


def _hard_triggers(inputs: AmtGuardInputs) -> list[str]:
    triggers = []
    if inputs.iso_exercise_spread > 0:
        triggers.append("ISO exercise spread (Form 6251 line 2i)")
    if inputs.private_activity_bond_interest > 0:
        triggers.append("specified private-activity-bond interest (line 2g)")
    if inputs.other_amt_adjustments != 0:
        triggers.append("other AMT adjustments (lines 2c-3)")
    if inputs.has_depreciation_or_passive_adjustments:
        triggers.append("depreciation/passive-activity AMT adjustments (lines 2l/2m)")
    if inputs.has_general_business_credit:
        triggers.append("general business credit (Who Must File item 2)")
    if inputs.has_prior_year_amt_credit:
        triggers.append("prior-year minimum tax credit / Form 8801 (Who Must File item 3)")
    return triggers


def amt_screen(inputs: AmtGuardInputs, pack: ParamPack) -> AmtScreenResult:
    """Run the guard. Raises ``AmtReviewRequired`` on any trigger; returns the
    screen arithmetic (for the audit trail) when the return passes."""
    triggers = _hard_triggers(inputs)
    if triggers:
        raise AmtReviewRequired(
            "AMT manual review required — this engine does not refigure: "
            + "; ".join(triggers)
        )

    fs = inputs.filing_status.value
    exemption_full = pack.get(f"amt.exemption.{fs}")
    threshold = pack.get(f"amt.exemption_phaseout_threshold.{fs}")
    breakpoint_28 = pack.get("amt.rate_28pct_breakpoint")
    if inputs.filing_status is FilingStatus.MARRIED_FILING_SEPARATELY:
        # §2.11: the 28% breakpoint is halved for MFS ($119,550) — the pack
        # stores the all-other value; refuse rather than compute wrongly.
        raise AmtReviewRequired(
            "AMT screen not calibrated for MFS (28% breakpoint differs); manual review"
        )

    amti = inputs.taxable_income + inputs.deduction_addback
    phaseout = max(amti - threshold.value, _ZERO) * _PHASEOUT_RATE
    exemption = max(exemption_full.value - phaseout, _ZERO)
    base = max(amti - exemption, _ZERO)

    pref_in_base = min(inputs.preferential_income, base)
    ordinary_base = base - pref_in_base
    fifteen_max = pack.get(f"ltcg.fifteen_rate_max.{fs}")
    tmt = (
        _RATE_26 * min(ordinary_base, breakpoint_28.value)
        + _RATE_28 * max(ordinary_base - breakpoint_28.value, _ZERO)
        + _RATE_15 * min(pref_in_base, fifteen_max.value)
        + _RATE_20 * max(pref_in_base - fifteen_max.value, _ZERO)
    )

    if tmt > inputs.regular_tax * _MARGIN:
        raise AmtReviewRequired(
            f"AMT screen fired: screen TMT {tmt:.0f} reaches 98% of regular tax "
            f"{inputs.regular_tax:.0f} (AMTI {amti}, exemption {exemption}). "
            f"Complete Form 6251 manually (or against the filed return) before "
            f"trusting this return — the screen overstates TMT by design, so "
            f"this may be a false alarm, but it must be resolved, not skipped."
        )

    explanation = Traced(
        label="amt_guard:passed",
        value=tmt,
        sources=(
            f"{INSTR_CITE} (Who Must File; Exemption Worksheet 25% phaseout); "
            f"screen TMT vs regular tax {inputs.regular_tax} with 2% margin",
        ),
        inputs=(exemption_full, threshold, breakpoint_28),
    )
    return AmtScreenResult(
        amti=amti,
        exemption=exemption,
        tentative_minimum_tax=tmt,
        regular_tax=inputs.regular_tax,
        explanation=explanation,
    )
