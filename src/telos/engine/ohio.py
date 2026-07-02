"""Ohio nonresident return (IT 1040 + IT BUS + IT NRC), rental-only profile.

Implements the line flow the filed-return inventory demands: federal AGI ->
business income deduction (IT BUS, $250k cap, remainder at flat 3%) -> Ohio
AGI -> tiered exemption (by Ohio MAGI = OAGI + BID, per the booklet) ->
taxable nonbusiness income -> the PRINTED bracket constants (which contain a
genuine $342 discontinuity at $26,050 — implemented exactly as printed,
never re-derived) -> nonresident credit (IT NRC: the non-Ohio share of tax).

Scope: FULL-YEAR NONRESIDENT whose Ohio-source income is business income
(the rental) plus optionally Ohio nonbusiness income. Part-year residency is
out of the declared universe. The typical outcome for a small out-of-state
rental — BID covers it, NRC credits the rest, net tax $0 but a filing-shaped
result — is exactly what the module reproduces and documents.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from decimal import ROUND_DOWN, Decimal
from types import MappingProxyType

from pydantic import BaseModel, ConfigDict, Field

from telos.engine.rounding import round_whole_dollar
from telos.engine.trace import Traced
from telos.models import FilingStatus
from telos.params import ParamPack

CITE = "2025 Ohio IT 1040 instructions"
_ZERO = Decimal(0)
_ONE = Decimal(1)


class OhioNonresidentInputs(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    filing_status: FilingStatus
    federal_agi: Decimal
    total_business_income: Decimal = Field(
        description="ALL business income in federal AGI (Ohio + elsewhere); rentals count"
    )
    ohio_sourced_business_income: Decimal = Field(
        description="the Ohio rental's share of the above (may be a loss)"
    )
    ohio_nonbusiness_income: Decimal = Field(default=_ZERO, ge=0)
    other_ohio_adjustments: Decimal = Field(
        default=_ZERO, description="net other Schedule of Adjustments items (signed)"
    )
    exemptions: int = Field(default=1, ge=1)


@dataclass(frozen=True)
class OhioResult:
    lines: Mapping[str, Traced]
    net_tax: Traced
    filing_required: bool


def _nonbusiness_tax(taxable: Decimal, pack: ParamPack) -> Decimal:
    """The printed 2025 bracket table, exactly as printed (p.18)."""
    zero_limit = pack.get("nonbusiness_brackets.zero_limit").value
    if taxable <= zero_limit:
        return _ZERO
    mid_limit = pack.get("nonbusiness_brackets.mid_limit").value
    if taxable <= mid_limit:
        base = pack.get("nonbusiness_brackets.mid_base").value
        rate = pack.get("nonbusiness_brackets.mid_rate").value
        return base + rate * (taxable - zero_limit)
    base = pack.get("nonbusiness_brackets.top_base").value
    rate = pack.get("nonbusiness_brackets.top_rate").value
    return base + rate * (taxable - mid_limit)


def _exemption_amount(oh_magi: Decimal, pack: ParamPack) -> Decimal:
    for tier in ("tier1", "tier2", "tier3"):
        if oh_magi <= pack.get(f"exemption.{tier}_magi_limit").value:
            return pack.get(f"exemption.{tier}_amount").value
    return _ZERO


def ohio_nonresident(inputs: OhioNonresidentInputs, pack: ParamPack) -> OhioResult:
    mfs = inputs.filing_status is FilingStatus.MARRIED_FILING_SEPARATELY
    bid_cap = pack.get(
        "business_income_deduction.cap_married_filing_separately" if mfs
        else "business_income_deduction.cap"
    )
    biz_total = max(inputs.total_business_income, _ZERO)
    bid = min(biz_total, bid_cap.value)

    ln: dict[str, Traced] = {}
    ln["1"] = Traced(label="OH IT1040:line1 federal AGI", value=inputs.federal_agi)
    ln["bid"] = Traced(
        label="OH:business income deduction (IT BUS)",
        value=bid,
        sources=(f"{CITE} p.11 (first ${bid_cap.value} of business income)",),
        inputs=(bid_cap,),
    )
    oagi = inputs.federal_agi - bid + inputs.other_ohio_adjustments
    ln["3"] = Traced(
        label="OH IT1040:line3 Ohio AGI", value=oagi,
        inputs=(ln["1"], ln["bid"]),
    )
    oh_magi = oagi + bid  # booklet p.8: MAGI = OAGI plus the BID
    exemption = _exemption_amount(oh_magi, pack) * inputs.exemptions
    ln["4"] = Traced(
        label="OH IT1040:line4 exemptions",
        value=exemption,
        sources=(f"{CITE} p.17 exemption table (MAGI {oh_magi})",),
    )
    ln["5"] = Traced(
        label="OH IT1040:line5", value=max(oagi - exemption, _ZERO),
        inputs=(ln["3"], ln["4"]),
    )
    taxable_biz = min(max(biz_total - bid, _ZERO), ln["5"].value)
    ln["6"] = Traced(
        label="OH IT1040:line6 taxable business income (IT BUS line 13)",
        value=taxable_biz, inputs=(ln["bid"],),
    )
    ln["7"] = Traced(
        label="OH IT1040:line7 taxable nonbusiness income",
        value=ln["5"].value - ln["6"].value,
        inputs=(ln["5"], ln["6"]),
    )
    ln["8a"] = Traced(
        label="OH IT1040:line8a nonbusiness tax",
        value=round_whole_dollar(_nonbusiness_tax(ln["7"].value, pack)),
        sources=(f"{CITE} p.18 printed bracket table",),
        inputs=(ln["7"],),
    )
    flat = pack.get("business_income_deduction.flat_rate_on_remainder")
    ln["8b"] = Traced(
        label="OH IT1040:line8b business income tax",
        value=round_whole_dollar(ln["6"].value * flat.value),
        inputs=(ln["6"], flat),
    )
    ln["8c"] = Traced(
        label="OH IT1040:line8c income tax liability before credits",
        value=ln["8a"].value + ln["8b"].value,
        inputs=(ln["8a"], ln["8b"]),
    )

    # IT NRC per the filed-return mechanics (verified against a real 2025
    # TurboTax IT NRC): Section I uses the UN-NETTED Ohio-sourced business
    # income (no BID apportionment inside the ratio), and the ratio is
    # TRUNCATED to four decimals on the form (0.996166 -> 0.9961).
    oh_biz = max(inputs.ohio_sourced_business_income, _ZERO)
    ohio_portion = oh_biz + inputs.ohio_nonbusiness_income
    if oagi > 0:
        ratio = min(max((oagi - ohio_portion) / oagi, _ZERO), _ONE)
        ratio = ratio.quantize(Decimal("0.0001"), rounding=ROUND_DOWN)
    else:
        ratio = _ONE
    ln["nrc"] = Traced(
        label="OH Schedule of Credits: nonresident credit (IT NRC)",
        value=round_whole_dollar(ln["8c"].value * ratio),
        sources=(
            f"{CITE} pp.35-40 (IT NRC): credit = tax x non-Ohio share "
            f"(Ohio portion {ohio_portion}, ratio {ratio:.6f})",
        ),
        inputs=(ln["8c"],),
    )
    net = Traced(
        label="OH IT1040: net tax after nonresident credit",
        value=max(ln["8c"].value - ln["nrc"].value, _ZERO),
        inputs=(ln["8c"], ln["nrc"]),
    )
    filing_required = ohio_portion > 0 or inputs.ohio_sourced_business_income != 0
    return OhioResult(lines=MappingProxyType(ln), net_tax=net, filing_required=filing_required)
