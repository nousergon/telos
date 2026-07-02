"""Pure deterministic computation. No I/O, no LLM, no clock.

Everything in this package is a pure function or an immutable value object.
Parameters (brackets, thresholds, deduction amounts) are injected via
``telos.params`` parameter packs — never hardcoded here.
"""

from telos.engine.brackets import Bracket, marginal_rate, tax_from_brackets
from telos.engine.guard import (
    CoverageError,
    CoverageGuard,
    UnsupportedDocumentError,
    UnsupportedFieldError,
)
from telos.engine.rounding import round_whole_dollar, to_decimal
from telos.engine.trace import Traced, traced_sum

__all__ = [
    "Bracket",
    "CoverageError",
    "CoverageGuard",
    "Traced",
    "UnsupportedDocumentError",
    "UnsupportedFieldError",
    "marginal_rate",
    "round_whole_dollar",
    "tax_from_brackets",
    "to_decimal",
    "traced_sum",
]
