"""Progressive bracket arithmetic.

Pure mechanics: the bracket *tables* live in parameter packs
(``telos.params``), never here. A bracket schedule is a list of ``Bracket``
rows in ascending order; exactly the last row has ``upto=None`` (open-ended).
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Optional


@dataclass(frozen=True)
class Bracket:
    """One bracket row: income up to ``upto`` (None = unbounded) taxed at ``rate``."""

    upto: Optional[Decimal]  # noqa: UP045 — Optional survives dataclass introspection cleanly
    rate: Decimal


class BracketScheduleError(ValueError):
    """The bracket table itself is malformed — a parameter-pack defect."""


def validate_brackets(brackets: list[Bracket]) -> None:
    if not brackets:
        raise BracketScheduleError("empty bracket schedule")
    if brackets[-1].upto is not None:
        raise BracketScheduleError("last bracket must be open-ended (upto=None)")
    prev = Decimal(0)
    for i, br in enumerate(brackets):
        if not (Decimal(0) <= br.rate <= Decimal(1)):
            raise BracketScheduleError(f"bracket {i}: rate {br.rate} outside [0, 1]")
        if br.upto is None:
            if i != len(brackets) - 1:
                raise BracketScheduleError(f"bracket {i}: open-ended row before the last row")
            continue
        if br.upto <= prev:
            raise BracketScheduleError(
                f"bracket {i}: upto {br.upto} not strictly greater than prior bound {prev}"
            )
        prev = br.upto


def tax_from_brackets(taxable: Decimal, brackets: list[Bracket]) -> Decimal:
    """Exact (unrounded) progressive tax on ``taxable``.

    Rounding is a form-level concern — apply ``round_whole_dollar`` at the
    line where the form instructions say to, not here.
    """
    validate_brackets(brackets)
    if taxable < 0:
        raise ValueError(f"taxable income must be >= 0, got {taxable}")
    tax = Decimal(0)
    lower = Decimal(0)
    for br in brackets:
        upper = br.upto if br.upto is not None else taxable
        if taxable <= lower:
            break
        span = min(taxable, upper) - lower
        if span > 0:
            tax += span * br.rate
        lower = upper
    return tax


def marginal_rate(taxable: Decimal, brackets: list[Bracket]) -> Decimal:
    """The rate applying to the next dollar of income at ``taxable``."""
    validate_brackets(brackets)
    if taxable < 0:
        raise ValueError(f"taxable income must be >= 0, got {taxable}")
    for br in brackets:
        if br.upto is None or taxable < br.upto:
            return br.rate
    raise AssertionError("unreachable: last bracket is open-ended")
