"""Full-year projection: scenario -> the SAME deterministic engine -> flags.

The load-bearing choice: the projection is not a parallel estimator — it
builds ``FullReturnInputs`` from the scenario and runs
``compute_federal_return`` with the target year's parameter pack, so every
projected dollar rides the exact worksheet code the filing path uses (QDCGT,
NIIT, Additional Medicare, Schedule A SALT phase-down, QBI, AMT screen).
There is no second arithmetic to drift.

Aggregate expected gains become synthesized Schedule D lots (box C/F — not
broker-reported) so the real ST/LT netting and loss-cap logic runs; each is
labeled ``PLANNING AGGREGATE`` in the audit trail.

The AMT guard runs on the projection too: a scenario that trips it raises
``AmtReviewRequired`` rather than silently projecting without AMT — the
fail-loud posture applied to planning.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal

from telos.contracts import (
    EstimatedTaxRequest,
    Form8949Box,
    OhioSection,
    ProjectedLiability,
    RealizedLot,
    RealizedLots,
    SafeHarborSummary,
    TaxProjection,
    Term,
    WaExciseSection,
)
from telos.engine import marginal_rate
from telos.engine.estimated import EstimatedTaxResult, compute_estimated_tax
from telos.engine.ohio import OhioNonresidentInputs, ohio_estimated_tax_check, ohio_nonresident
from telos.engine.wa_excise import wa_excise_check
from telos.orchestrate import FederalReturn, FullReturnInputs, compute_federal_return
from telos.params import ParamPack
from telos.planning.flags import flag_quarters
from telos.planning.scenario import PlanningScenario

_ZERO = Decimal(0)
_LOT_SOURCE = "telos.planning:scenario aggregate"


@dataclass(frozen=True)
class ProjectionOutcome:
    """Everything the projection produced: the artifact (for consumers) plus
    the full traced return and voucher math (for the audit trail / report)."""

    federal: FederalReturn
    estimated: EstimatedTaxResult
    artifact: TaxProjection

    def explain(self) -> str:
        return "\n".join(
            [
                self.federal.result.total_tax.explain(),
                self.estimated.explain(),
            ]
        )


def _aggregate_lot(net: Decimal, term: Term, tax_year: int) -> RealizedLot:
    """One synthetic lot carrying an aggregate expected net gain or loss."""
    box = Form8949Box.C if term is Term.SHORT else Form8949Box.F
    return RealizedLot(
        description=f"PLANNING AGGREGATE {term.value}-term net",
        date_acquired="VARIOUS",
        date_sold=f"{tax_year}-12-31",
        proceeds=max(net, _ZERO),
        cost_basis=max(-net, _ZERO),
        term=term,
        box=box,
        source=_LOT_SOURCE,
    )


def build_full_year_inputs(scenario: PlanningScenario) -> FullReturnInputs:
    lots: list[RealizedLot] = []
    if scenario.st_net_gain != _ZERO:
        lots.append(_aggregate_lot(scenario.st_net_gain, Term.SHORT, scenario.tax_year))
    if scenario.lt_net_gain != _ZERO:
        lots.append(_aggregate_lot(scenario.lt_net_gain, Term.LONG, scenario.tax_year))
    has_capital_activity = bool(lots) or (
        scenario.st_loss_carryover > _ZERO or scenario.lt_loss_carryover > _ZERO
    )
    return FullReturnInputs(
        tax_year=scenario.tax_year,
        filing_status=scenario.filing_status,
        w2s=scenario.w2s,
        forms_1099_int=scenario.forms_1099_int,
        forms_1099_div=scenario.forms_1099_div,
        realized_lots=RealizedLots(lots=tuple(lots)) if has_capital_activity else None,
        capital_gain_distributions=scenario.capital_gain_distributions,
        st_loss_carryover=scenario.st_loss_carryover,
        lt_loss_carryover=scenario.lt_loss_carryover,
        schedule_e=scenario.schedule_e,
        schedule_a=scenario.schedule_a,
        qbi_businesses=scenario.qbi_businesses,
        other_income=scenario.other_income,
        credits=scenario.credits,
        niit_state_local_tax_allocable=scenario.niit_state_local_tax_allocable,
        estimated_payments=scenario.estimated_payments_total,
    )


def _dedupe(sources: tuple[str, ...]) -> tuple[str, ...]:
    seen: dict[str, None] = {}
    for src in sources:
        seen.setdefault(src)
    return tuple(seen)


def _build_wa_section(scenario: PlanningScenario, wa_pack: ParamPack) -> WaExciseSection:
    """Plan §6.4 checkers-cite-their-work: the determination is emitted WITH
    the computation shown even when the check is not applicable."""
    det = wa_excise_check(scenario.lt_net_gain, wa_pack)
    message = f"{det.explanation.label}: {'; '.join(det.explanation.sources)}"
    return WaExciseSection(
        applicable=det.applicable,
        wa_allocable_long_term_gain=scenario.lt_net_gain,
        taxable_gain=det.taxable_gain,
        tax=det.tax,
        message=message,
        citations=det.explanation.all_sources(),
    )


def _build_ohio_section(
    scenario: PlanningScenario, federal_agi: Decimal, oh_pack: ParamPack
) -> OhioSection:
    """telos-ops#21 scope: the scenario's ENTIRE Schedule E is treated as the
    Ohio-source duplex — ``RentalArrangement`` carries no per-property state
    tag, so a multi-state Schedule E would misattribute here."""
    schedule_e = scenario.schedule_e
    total_biz = (
        sum((a.net_income_post_caps for a in schedule_e.arrangements), start=_ZERO)
        if schedule_e is not None
        else _ZERO
    )
    oh_inputs = OhioNonresidentInputs(
        filing_status=scenario.filing_status,
        federal_agi=federal_agi,
        total_business_income=total_biz,
        ohio_sourced_business_income=total_biz,
        exemptions=scenario.oh_exemptions,
    )
    result = ohio_nonresident(oh_inputs, oh_pack)
    check = ohio_estimated_tax_check(
        current_year_oh_tax=result.net_tax.value,
        prior_year_oh_tax=scenario.prior_year_oh_tax,
        oh_withholding=scenario.oh_withholding,
        pack=oh_pack,
    )
    message = (
        f"OH net tax {result.net_tax.value} "
        f"(filing {'required' if result.filing_required else 'not required'}); "
        f"{check.explanation.label}: {'; '.join(check.explanation.sources)}"
    )
    citations = _dedupe(result.net_tax.all_sources() + check.explanation.all_sources())
    return OhioSection(
        filing_required=result.filing_required,
        net_tax=result.net_tax.value,
        estimated_payments_advisable=check.advisable,
        required_annual_payment=check.required_annual_payment.value,
        balance_after_withholding=check.balance_after_withholding.value,
        message=message,
        citations=citations,
    )


def project(
    scenario: PlanningScenario,
    pack: ParamPack,
    *,
    wa_pack: ParamPack | None = None,
    oh_pack: ParamPack | None = None,
) -> ProjectionOutcome:
    """``wa_pack``/``oh_pack`` are the telos-ops#21 extension point: when
    given, the projection also runs that state's applicability/liability
    check and attaches the optional ``wa``/``ohio`` sections. Unlike the
    federal ``pack``, these are NOT required to match ``scenario.tax_year`` —
    state parameter packs routinely trail the federal calendar (e.g. WA's
    DOR publishes the next year's inflation-adjusted standard deduction
    later in the year), and the state engine modules themselves
    (``wa_excise_check`` / ``ohio_nonresident``) never consult a tax-year at
    all. Callers are responsible for supplying the pack-year they intend."""
    if pack.tax_year != scenario.tax_year:
        raise ValueError(
            f"scenario is TY{scenario.tax_year} but pack is TY{pack.tax_year} — "
            f"a projection on the wrong year's constants is silently wrong"
        )

    federal = compute_federal_return(build_full_year_inputs(scenario), pack)
    result = federal.result

    total_tax = result.total_tax.value
    estimated_paid = scenario.estimated_payments_total
    # total_payments = withholding (25a-25c) + estimated payments; withholding
    # alone is what §6654 treats as paid ratably across the year.
    withholding_total = result.total_payments.value - estimated_paid

    request = EstimatedTaxRequest(
        filing_status=scenario.filing_status,
        prior_year_tax=scenario.prior_year_tax,
        prior_year_agi=scenario.prior_year_agi,
        prior_year_return_covered_12_months=scenario.prior_year_return_covered_12_months,
        current_year_projected_tax=total_tax,
        current_year_withholding=withholding_total,
    )
    estimated = compute_estimated_tax(request, pack, tax_year=scenario.tax_year)
    quarters, headline = flag_quarters(estimated, scenario)

    agi = result.lines["11"].value
    taxable = result.lines["15"].value
    effective = (
        (total_tax / agi).quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP)
        if agi > _ZERO
        else _ZERO
    )
    marginal = marginal_rate(
        taxable, pack.brackets(f"ordinary_brackets.{scenario.filing_status.value}")
    )

    artifact = TaxProjection(
        tax_year=scenario.tax_year,
        as_of=scenario.as_of,
        filing_status=scenario.filing_status,
        pack_status=pack.status,
        projected=ProjectedLiability(
            agi=agi,
            taxable_income=taxable,
            total_tax=total_tax,
            total_withholding=withholding_total,
            estimated_payments_made=estimated_paid,
            balance_due=result.balance_due.value,
            effective_rate_on_agi=effective,
            marginal_ordinary_rate=marginal,
        ),
        safe_harbor=SafeHarborSummary(
            basis=estimated.safe_harbor_basis,
            required_annual_payment=estimated.required_annual_payment.value,
            total_estimated_tax_due=estimated.total_estimated_tax_due.value,
        ),
        quarters=quarters,
        headline=headline,
        wa=_build_wa_section(scenario, wa_pack) if wa_pack is not None else None,
        ohio=_build_ohio_section(scenario, agi, oh_pack) if oh_pack is not None else None,
    )
    return ProjectionOutcome(federal=federal, estimated=estimated, artifact=artifact)


__all__ = ["ProjectionOutcome", "build_full_year_inputs", "project"]
