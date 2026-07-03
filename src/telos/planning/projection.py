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
    ProjectedLiability,
    RealizedLot,
    RealizedLots,
    SafeHarborSummary,
    TaxProjection,
    Term,
)
from telos.engine import marginal_rate
from telos.engine.estimated import EstimatedTaxResult, compute_estimated_tax
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


def project(scenario: PlanningScenario, pack: ParamPack) -> ProjectionOutcome:
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
    )
    return ProjectionOutcome(federal=federal, estimated=estimated, artifact=artifact)


__all__ = ["ProjectionOutcome", "build_full_year_inputs", "project"]
