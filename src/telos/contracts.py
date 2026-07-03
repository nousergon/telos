"""Cross-repo data contracts (M0 discipline: versioned at birth).

``RealizedLots`` is the realized-capital-lots contract: produced by a broker
1099-B/1099-DA extraction or by Metron's lot export, consumed by the Form
8949 / Schedule D modules. The JSON Schema artifact
(``contracts/realized_lots.schema.json``) is GENERATED from these models —
a contract test asserts the committed file matches, so the pydantic model is
the single source of truth and drift is impossible.

2025 box taxonomy (fetched 2025 Schedule D/8949): boxes A/B/C (short) and
D/E/F (long) cover 1099-B; the NEW boxes G/H/I (short) and J/K/L (long)
cover 1099-DA digital assets. Schedule D folds them pairwise (line 1b = A|G,
2 = B|H, 3 = C|I; 8b = D|J, 9 = E|K, 10 = F|L).
"""

from __future__ import annotations

from decimal import Decimal
from enum import StrEnum
from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, model_validator

from telos.models import FilingStatus

REALIZED_LOTS_SCHEMA_VERSION = "1.0.0"

_ZERO = Decimal(0)


class Term(StrEnum):
    SHORT = "short"
    LONG = "long"


class Form8949Box(StrEnum):
    A = "A"  # short, 1099-B, basis reported
    B = "B"  # short, 1099-B, basis not reported
    C = "C"  # short, no 1099-B
    D = "D"  # long, 1099-B, basis reported
    E = "E"  # long, 1099-B, basis not reported
    F = "F"  # long, no 1099-B
    G = "G"  # short, 1099-DA, basis reported
    H = "H"  # short, 1099-DA, basis not reported
    I = "I"  # short, no 1099-DA  # noqa: E741 — the IRS named the box
    J = "J"  # long, 1099-DA, basis reported
    K = "K"  # long, 1099-DA, basis not reported
    L = "L"  # long, no 1099-DA


SHORT_BOXES = frozenset({Form8949Box.A, Form8949Box.B, Form8949Box.C,
                         Form8949Box.G, Form8949Box.H, Form8949Box.I})


class RealizedLot(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    description: str = Field(min_length=1, description="8949 column (a)")
    date_acquired: str = Field(description="ISO date or 'VARIOUS' — column (b)")
    date_sold: str = Field(description="ISO date — column (c)")
    proceeds: Decimal = Field(ge=0, description="column (d)")
    cost_basis: Decimal = Field(ge=0, description="column (e)")
    wash_sale_disallowed: Decimal = Field(
        default=_ZERO, ge=0,
        description="broker-reported code-W adjustment, column (g); never recomputed year 1",
    )
    term: Term
    box: Form8949Box
    source: str = Field(min_length=1, description="producing system/document id")

    @model_validator(mode="after")
    def _box_term_consistent(self) -> RealizedLot:
        box_is_short = self.box in SHORT_BOXES
        if box_is_short != (self.term is Term.SHORT):
            raise ValueError(
                f"lot {self.description!r}: box {self.box} is a "
                f"{'short' if box_is_short else 'long'}-term box but term={self.term}"
            )
        return self

    @property
    def gain(self) -> Decimal:
        """8949 column (h): (d) - (e) combined with the column-(g) adjustment."""
        return self.proceeds - self.cost_basis + self.wash_sale_disallowed


class RealizedLots(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal["1.0.0"] = REALIZED_LOTS_SCHEMA_VERSION
    lots: tuple[RealizedLot, ...] = ()


def realized_lots_json_schema() -> dict:
    """The contract artifact, generated — never hand-edited."""
    return RealizedLots.model_json_schema()


SCHEDULE_E_SCHEMA_VERSION = "1.0.0"


class LossRegime(StrEnum):
    """Which limitation engine governed the arrangement (computed UPSTREAM).

    The regime math is the producer's job (ktema's allocation engine, or the
    preparer whose filed return the manual path transcribes) — telos consumes
    post-cap numbers and enforces only the invariants each regime implies.
    """

    SECTION_280A = "section_280a"  # room-in-home: deductions capped at income
    SECTION_469_PASSIVE = "section_469_passive"  # standalone rental passive rules
    NOT_FOR_PROFIT = "not_for_profit"  # below-FMV / §183: no loss allowed


class RentalArrangement(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    arrangement_id: str = Field(min_length=1)
    property_name: str = Field(min_length=1)
    regime: LossRegime
    net_income_post_caps: Decimal = Field(
        description="the Schedule E result AFTER the regime cap — may be negative "
        "only under §469 (the post-8582 allowed loss)"
    )
    depreciation_taken: Decimal = Field(default=_ZERO, ge=0)
    suspended_loss_carryforward: Decimal = Field(
        default=_ZERO, ge=0,
        description="§280A carryforward or §469 suspended loss, per the regime",
    )
    qbi_eligible_income: Optional[Decimal] = Field(  # noqa: UP045 — pydantic-friendly
        default=None,
        description="QBI component for Form 8995-A; None = producer did not determine",
    )
    contested_flags: tuple[str, ...] = Field(
        default=(),
        description="CPA-confirm positions, preserved verbatim through the audit trail",
    )
    source: str = Field(min_length=1, description="'ktema' or 'manual:<who/when>'")

    @model_validator(mode="after")
    def _regime_invariants(self) -> RentalArrangement:
        if self.regime is LossRegime.NOT_FOR_PROFIT and self.net_income_post_caps < 0:
            raise ValueError(
                f"{self.arrangement_id}: not-for-profit (§183) arrangements cannot "
                f"show a loss — no loss is allowed under that regime"
            )
        if self.regime is LossRegime.SECTION_280A and self.net_income_post_caps < 0:
            raise ValueError(
                f"{self.arrangement_id}: §280A caps deductions at rental income — "
                f"post-cap net cannot be negative (the excess belongs in "
                f"suspended_loss_carryforward)"
            )
        return self


class ScheduleEWorksheet(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal["1.0.0"] = SCHEDULE_E_SCHEMA_VERSION
    tax_year: int
    arrangements: tuple[RentalArrangement, ...] = ()


def schedule_e_worksheet_json_schema() -> dict:
    """The contract artifact, generated — never hand-edited."""
    return ScheduleEWorksheet.model_json_schema()


ESTIMATED_TAX_REQUEST_SCHEMA_VERSION = "1.0.0"


class EstimatedTaxRequest(BaseModel):
    """1040-ES / 2210 quarterly-voucher inputs — Metron-callable (telos-ops#7).

    Plain typed data only (filing status + prior/current-year totals): a
    caller assembles this from its own tax-liability estimate without
    importing anything from ``telos.engine``. Feed it to
    ``telos.engine.estimated.compute_estimated_tax`` alongside a
    ``ParamPack`` for the target tax year.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal["1.0.0"] = ESTIMATED_TAX_REQUEST_SCHEMA_VERSION
    filing_status: FilingStatus
    prior_year_tax: Decimal = Field(
        ge=0, description="prior-year total tax (Form 2210 line 8 equivalent)"
    )
    prior_year_agi: Decimal = Field(ge=0)
    prior_year_return_covered_12_months: bool = Field(
        default=True,
        description=(
            "the 100%/110%-of-prior-year safe harbors require the prior-year "
            "return to have covered a full 12-month period (26 U.S.C. "
            "§6654(d)(1)(B)(ii)); when False only the 90%-of-current-year "
            "harbor is available"
        ),
    )
    current_year_projected_tax: Decimal = Field(
        ge=0, description="projected current-year total tax liability"
    )
    current_year_withholding: Decimal = Field(
        default=_ZERO, ge=0,
        description="current-year withholding, treated as paid ratably across the year",
    )
    use_annualized_income_method: bool = Field(
        default=False,
        description=(
            "annualized-income-installment method (Schedule AI) for unevenly "
            "distributed income — NOT YET IMPLEMENTED (telos-ops#7 stub); "
            "compute_estimated_tax raises rather than silently falling back "
            "to the even-installment method"
        ),
    )


def estimated_tax_request_json_schema() -> dict:
    """The contract artifact, generated — never hand-edited."""
    return EstimatedTaxRequest.model_json_schema()


TAX_PROJECTION_SCHEMA_VERSION = "1.0.0"


class QuarterPaymentStatus(StrEnum):
    PAID = "paid"  # installment fully covered by payments made
    OVERDUE = "overdue"  # due date has passed with a shortfall
    UPCOMING = "upcoming"  # due date is at or after as_of, shortfall remains


class QuarterFlag(BaseModel):
    """One §6654(c)(2) installment, judged against payments made as of ``as_of``."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    quarter: int = Field(ge=1, le=4)
    due_date: str = Field(description="ISO date (statutory, un-shifted for weekends/holidays)")
    required: Decimal = Field(ge=0)
    paid: Decimal = Field(ge=0)
    shortfall: Decimal = Field(ge=0)
    status: QuarterPaymentStatus


class ProjectedLiability(BaseModel):
    """The projected full-year federal picture, from the deterministic engine."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    agi: Decimal
    taxable_income: Decimal = Field(ge=0)
    total_tax: Decimal = Field(ge=0, description="Form 1040 line 24 (incl. NIIT/Add'l Medicare)")
    total_withholding: Decimal = Field(ge=0, description="lines 25a-25c, treated as ratable")
    estimated_payments_made: Decimal = Field(ge=0)
    balance_due: Decimal = Field(description="total tax minus all payments; negative = refund")
    effective_rate_on_agi: Decimal = Field(
        ge=0, description="total_tax / AGI, 4dp; 0 when AGI <= 0"
    )
    marginal_ordinary_rate: Decimal = Field(
        ge=0, description="ordinary bracket rate at projected taxable income"
    )


class SafeHarborSummary(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    basis: str = Field(
        description="which §6654(d)(1) harbor bound: 90pct_current_year / "
        "100pct_prior_year / 110pct_prior_year"
    )
    required_annual_payment: Decimal = Field(ge=0)
    total_estimated_tax_due: Decimal = Field(
        ge=0, description="required annual payment less withholding, floored at 0"
    )


class PaymentHeadline(BaseModel):
    """The one-glance answer: should a payment be made, how much, by when."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    payment_recommended: bool
    recommended_amount: Decimal = Field(
        ge=0, description="overdue shortfalls + the next upcoming installment's shortfall"
    )
    next_due_date: Optional[str] = Field(  # noqa: UP045 — pydantic-friendly
        default=None, description="ISO date of the next unpaid installment; None if all past"
    )
    message: str


class TaxProjection(BaseModel):
    """Year-round tax-projection artifact — produced by ``telos.planning``,
    consumed by dashboards (Metron /tax Planning panel). Plain data only; the
    full audit trail stays in-process (``ProjectionOutcome.federal``)."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal["1.0.0"] = TAX_PROJECTION_SCHEMA_VERSION
    tax_year: int
    as_of: str = Field(description="ISO date the scenario reflects")
    filing_status: FilingStatus
    pack_status: str = Field(
        description="parameter-pack status the projection ran on (example/provisional/final)"
    )
    projected: ProjectedLiability
    safe_harbor: SafeHarborSummary
    quarters: tuple[QuarterFlag, ...] = ()
    headline: PaymentHeadline


def tax_projection_json_schema() -> dict:
    """The contract artifact, generated — never hand-edited."""
    return TaxProjection.model_json_schema()
