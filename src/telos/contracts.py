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
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

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
