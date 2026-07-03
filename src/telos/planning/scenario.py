"""The planning scenario: income EXPECTATIONS for a tax year in flight.

A ``PlanningScenario`` is the year-round-planning counterpart of the filing
path's ``FullReturnInputs``: instead of transcribed source documents it
carries the owner's expected FULL-YEAR figures (actuals-to-date plus
expected remainder, combined by the human or an upstream feeder), the
prior-year safe-harbor anchors, and the estimated payments already made.

Personal scenarios are YAML files in ``TELOS_DATA_DIR`` — never in any repo
(plan §5.5). Money amounts in the YAML should be written as strings
(``"125000"``) so they enter the engine as exact ``Decimal``s.

No clock anywhere: ``as_of`` is data supplied by the caller, so the same
scenario re-run later gives the same answer (the replay property planning
inherits from the engine).
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator

from telos.contracts import ScheduleEWorksheet
from telos.engine import QbiBusiness
from telos.models import W2, FilingStatus, Form1099Div, Form1099Int
from telos.orchestrate import ScheduleAItems

PLANNING_SCENARIO_SCHEMA_VERSION = "1.0.0"

_ZERO = Decimal(0)


def _validate_iso_date(value: str, field_name: str) -> str:
    try:
        date.fromisoformat(value)
    except ValueError as exc:
        raise ValueError(f"{field_name} must be an ISO date (YYYY-MM-DD): {value!r}") from exc
    return value


class EstimatedPaymentMade(BaseModel):
    """A 1040-ES payment already sent for the scenario's tax year."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    quarter: int = Field(ge=1, le=4, description="the §6654(c)(2) installment it covers")
    date_paid: str = Field(description="ISO date the payment was made")
    amount: Decimal = Field(gt=0)

    @field_validator("date_paid")
    @classmethod
    def _date_paid_iso(cls, v: str) -> str:
        return _validate_iso_date(v, "date_paid")


class PlanningScenario(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal["1.0.0"] = PLANNING_SCENARIO_SCHEMA_VERSION
    tax_year: int
    as_of: str = Field(
        description=(
            "ISO date the expectations and payments-to-date reflect; quarter "
            "flags (overdue vs upcoming) are computed against this, never a clock"
        )
    )
    filing_status: FilingStatus

    # Expected FULL-YEAR income, per source — same typed models as the filing
    # path, holding expectation-values instead of transcribed documents.
    w2s: tuple[W2, ...] = ()
    forms_1099_int: tuple[Form1099Int, ...] = ()
    forms_1099_div: tuple[Form1099Div, ...] = ()

    # Capital gains as aggregate expected nets (realized-to-date + expected
    # remainder); the projection synthesizes aggregate Schedule D lots so the
    # real ST/LT netting and QDCGT paths run. Either sign.
    st_net_gain: Decimal = Field(default=_ZERO)
    lt_net_gain: Decimal = Field(default=_ZERO)
    capital_gain_distributions: Decimal = Field(default=_ZERO, ge=0)
    st_loss_carryover: Decimal = Field(default=_ZERO, ge=0)
    lt_loss_carryover: Decimal = Field(default=_ZERO, ge=0)

    schedule_e: Optional[ScheduleEWorksheet] = None  # noqa: UP045 — pydantic-friendly
    schedule_a: Optional[ScheduleAItems] = None  # noqa: UP045
    qbi_businesses: tuple[QbiBusiness, ...] = ()
    other_income: tuple[tuple[str, Decimal], ...] = ()
    credits: tuple[tuple[str, Decimal], ...] = ()
    niit_state_local_tax_allocable: Decimal = Field(default=_ZERO, ge=0)

    # Prior-year safe-harbor anchors (from the FILED prior return).
    prior_year_agi: Decimal = Field(ge=0)
    prior_year_tax: Decimal = Field(ge=0, description="prior-year total tax (Form 2210 line 8)")
    prior_year_return_covered_12_months: bool = True

    estimated_payments_made: tuple[EstimatedPaymentMade, ...] = ()

    @field_validator("as_of")
    @classmethod
    def _as_of_iso(cls, v: str) -> str:
        return _validate_iso_date(v, "as_of")

    @property
    def estimated_payments_total(self) -> Decimal:
        return sum((p.amount for p in self.estimated_payments_made), start=_ZERO)
