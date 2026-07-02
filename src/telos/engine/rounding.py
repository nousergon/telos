"""IRS rounding rules.

Form 1040 instructions permit whole-dollar rounding: drop amounts under 50
cents, round 50 cents and above up. That is ``ROUND_HALF_UP`` on the dollar —
NOT Python's default banker's rounding (``ROUND_HALF_EVEN``), which would
round $0.50 to $0 and diverge from every commercial preparer's output.
"""

from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal

_DOLLAR = Decimal("1")


def to_decimal(value: int | float | str | Decimal) -> Decimal:
    """Coerce to Decimal via ``str`` so floats don't smuggle in binary error.

    ``Decimal(0.1)`` is 0.1000000000000000055511151231257827; ``Decimal("0.1")``
    is exact. Everything entering the engine passes through here.
    """
    if isinstance(value, Decimal):
        return value
    return Decimal(str(value))


def round_whole_dollar(value: int | float | str | Decimal) -> Decimal:
    """Round to whole dollars per the Form 1040 rounding rule (half up)."""
    return to_decimal(value).quantize(_DOLLAR, rounding=ROUND_HALF_UP)
