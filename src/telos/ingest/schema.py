"""Extraction schemas for the ingestion layer.

These are the *ingestion-side* models: the full set of boxes the vision call
transcribes, plus cross-foot validation and a projection down to the canonical
engine models (:class:`telos.models.W2`). The engine models stay minimal — they
carry only what the arithmetic consumes — while these carry everything on the
page needed to cross-check the document against its own printed totals.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field, model_validator

from telos.models import W2


class CrossFootError(ValueError):
    """An extracted field disagrees with the document's own printed total."""


class ExtractedW2(BaseModel):
    """Full W-2 transcription produced by the vision/tool-use call.

    ``extra="forbid"`` so a hallucinated field is rejected at the boundary.
    Identity fields (SSN/EIN) are NOT here — they never reach the API and are
    re-joined locally via :class:`IngestedW2`.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    employer: str
    wages: Decimal = Field(ge=0, description="Box 1 — wages, tips, other comp")
    federal_income_tax_withheld: Decimal = Field(
        default=Decimal(0), ge=0, description="Box 2"
    )
    social_security_wages: Optional[Decimal] = Field(  # noqa: UP045
        default=None, ge=0, description="Box 3"
    )
    social_security_tax_withheld: Optional[Decimal] = Field(  # noqa: UP045
        default=None, ge=0, description="Box 4"
    )
    medicare_wages: Optional[Decimal] = Field(  # noqa: UP045
        default=None, ge=0, description="Box 5"
    )
    medicare_tax_withheld: Optional[Decimal] = Field(  # noqa: UP045
        default=None, ge=0, description="Box 6"
    )

    def to_w2(self) -> W2:
        """Project down to the canonical engine :class:`telos.models.W2`."""
        return W2(
            employer=self.employer,
            wages=self.wages,
            federal_income_tax_withheld=self.federal_income_tax_withheld,
            medicare_wages=self.medicare_wages,
            medicare_tax_withheld=self.medicare_tax_withheld,
        )


# 2025 rates (fetched from the SSA wage-base / IRS instructions): the employee
# share is 6.2% Social Security and 1.45% Medicare. These are exact statutory
# rates, used only to CROSS-FOOT box 4 against box 3 and box 6 against box 5 —
# never to compute a return. A penny of rounding tolerance per box.
_SS_RATE = Decimal("0.062")
_MEDICARE_RATE = Decimal("0.0145")
_TOLERANCE = Decimal("0.01")


def cross_foot_w2(w2: ExtractedW2) -> None:
    """Validate an extracted W-2 against its own arithmetic. Raise on mismatch.

    Withholding boxes are the document's internal totals: Box 4 must equal
    6.2% of Box 3, and Box 6 must equal 1.45% of Box 5 (to the penny). A
    tampered or misread box fails loudly here rather than silently corrupting
    the return downstream.
    """
    if w2.social_security_wages is not None and w2.social_security_tax_withheld is not None:
        expected = (w2.social_security_wages * _SS_RATE).quantize(Decimal("0.01"))
        if abs(w2.social_security_tax_withheld - expected) > _TOLERANCE:
            raise CrossFootError(
                f"Box 4 SS tax {w2.social_security_tax_withheld} != 6.2% of Box 3 "
                f"SS wages {w2.social_security_wages} (expected ~{expected})"
            )
    if w2.medicare_wages is not None and w2.medicare_tax_withheld is not None:
        expected = (w2.medicare_wages * _MEDICARE_RATE).quantize(Decimal("0.01"))
        if abs(w2.medicare_tax_withheld - expected) > _TOLERANCE:
            raise CrossFootError(
                f"Box 6 Medicare tax {w2.medicare_tax_withheld} != 1.45% of Box 5 "
                f"Medicare wages {w2.medicare_wages} (expected ~{expected})"
            )


class ExtractedConsolidated1099(BaseModel):
    """Stub schema for a consolidated broker 1099 (INT/DIV/B summary).

    W-2 is the must-have; this models the summary structure so the same
    redaction → extraction → cross-foot → confirm flow applies. The B-section
    is a summary only here (per-lot detail flows through the existing
    ``telos.contracts.RealizedLots`` contract, not this schema).
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    payer: str
    interest_income: Optional[Decimal] = Field(  # noqa: UP045
        default=None, ge=0, description="1099-INT box 1"
    )
    ordinary_dividends: Optional[Decimal] = Field(  # noqa: UP045
        default=None, ge=0, description="1099-DIV box 1a"
    )
    qualified_dividends: Optional[Decimal] = Field(  # noqa: UP045
        default=None, ge=0, description="1099-DIV box 1b"
    )
    proceeds: Optional[Decimal] = Field(  # noqa: UP045
        default=None, ge=0, description="1099-B summary proceeds"
    )
    is_corrected: bool = Field(
        default=False, description="CORRECTED box checked — triggers re-ingest"
    )

    @model_validator(mode="after")
    def _qualified_within_ordinary(self) -> ExtractedConsolidated1099:
        if (
            self.qualified_dividends is not None
            and self.ordinary_dividends is not None
            and self.qualified_dividends > self.ordinary_dividends
        ):
            raise CrossFootError(
                f"qualified dividends ({self.qualified_dividends}) exceed ordinary "
                f"dividends ({self.ordinary_dividends}) — box 1b is a subset of box 1a"
            )
        return self
