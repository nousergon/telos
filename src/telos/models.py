"""Typed source-document inputs.

Pydantic models with ``extra="forbid"`` — an unexpected field is rejected at
the model boundary, the same fail-loud posture as the coverage guard. Money
is ``Decimal`` end to end (coerced through strings upstream; never float
arithmetic inside the engine).

This is the v0.1 foundation set; form models grow with the engine modules
that consume them, never ahead of them.
"""

from __future__ import annotations

from decimal import Decimal
from enum import StrEnum
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field, model_validator


class FilingStatus(StrEnum):
    SINGLE = "single"
    MARRIED_FILING_JOINTLY = "married_filing_jointly"
    MARRIED_FILING_SEPARATELY = "married_filing_separately"
    HEAD_OF_HOUSEHOLD = "head_of_household"
    QUALIFYING_SURVIVING_SPOUSE = "qualifying_surviving_spouse"


class _Doc(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class W2(_Doc):
    """Form W-2 (the fields the engine currently consumes)."""

    employer: str
    wages: Decimal = Field(ge=0, description="Box 1")
    federal_income_tax_withheld: Decimal = Field(default=Decimal(0), ge=0, description="Box 2")
    # Medicare boxes: None means "not provided" — Form 8959 REFUSES to run on a
    # W-2 without box 5 (box 1 is NOT a valid proxy: pre-tax 401(k) deferrals
    # make them differ). Fail loud, never substitute.
    medicare_wages: Optional[Decimal] = Field(  # noqa: UP045 — pydantic-friendly
        default=None, ge=0, description="Box 5"
    )
    medicare_tax_withheld: Optional[Decimal] = Field(  # noqa: UP045
        default=None, ge=0, description="Box 6"
    )


class Form1099Int(_Doc):
    """Form 1099-INT (foundation fields)."""

    payer: str
    interest_income: Decimal = Field(ge=0, description="Box 1")
    federal_income_tax_withheld: Decimal = Field(default=Decimal(0), ge=0, description="Box 4")


class Form1099Div(_Doc):
    """Form 1099-DIV (foundation fields)."""

    payer: str
    ordinary_dividends: Decimal = Field(ge=0, description="Box 1a")
    qualified_dividends: Decimal = Field(default=Decimal(0), ge=0, description="Box 1b")
    federal_income_tax_withheld: Decimal = Field(default=Decimal(0), ge=0, description="Box 4")

    @model_validator(mode="after")
    def _qualified_within_ordinary(self) -> Form1099Div:
        if self.qualified_dividends > self.ordinary_dividends:
            raise ValueError(
                f"qualified dividends ({self.qualified_dividends}) exceed ordinary "
                f"dividends ({self.ordinary_dividends}) — box 1b is a subset of box 1a"
            )
        return self
