"""Pure deterministic computation. No I/O, no LLM, no clock.

Everything in this package is a pure function or an immutable value object.
Parameters (brackets, thresholds, deduction amounts) are injected via
``telos.params`` parameter packs — never hardcoded here.
"""

from telos.engine.brackets import Bracket, marginal_rate, tax_from_brackets
from telos.engine.form1040 import Form1040Inputs, Form1040Result, assemble_1040
from telos.engine.form8959 import Form8959Result, MissingMedicareWagesError, form8959
from telos.engine.form8960 import Form8960Inputs, Form8960Result, form8960
from telos.engine.guard import (
    CoverageError,
    CoverageGuard,
    UnsupportedDocumentError,
    UnsupportedFieldError,
)
from telos.engine.qdcgt import QdcgtResult, qdcgt_worksheet
from telos.engine.rounding import round_whole_dollar, to_decimal
from telos.engine.schedule_a import (
    ScheduleAInputs,
    ScheduleAResult,
    choose_deduction,
    schedule_a,
)
from telos.engine.tax_lookup import line16_tax, line16_tax_amount, tax_from_table
from telos.engine.trace import Traced, traced_sum

__all__ = [
    "Bracket",
    "CoverageError",
    "CoverageGuard",
    "Form1040Inputs",
    "Form1040Result",
    "Form8959Result",
    "Form8960Inputs",
    "Form8960Result",
    "MissingMedicareWagesError",
    "QdcgtResult",
    "ScheduleAInputs",
    "ScheduleAResult",
    "Traced",
    "UnsupportedDocumentError",
    "UnsupportedFieldError",
    "assemble_1040",
    "choose_deduction",
    "form8959",
    "form8960",
    "line16_tax",
    "line16_tax_amount",
    "marginal_rate",
    "qdcgt_worksheet",
    "round_whole_dollar",
    "schedule_a",
    "tax_from_brackets",
    "tax_from_table",
    "to_decimal",
    "traced_sum",
]
