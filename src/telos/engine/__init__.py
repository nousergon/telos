"""Pure deterministic computation. No I/O, no LLM, no clock.

Everything in this package is a pure function or an immutable value object.
Parameters (brackets, thresholds, deduction amounts) are injected via
``telos.params`` parameter packs — never hardcoded here.
"""

from telos.engine.amt_guard import (
    AmtGuardInputs,
    AmtReviewRequired,
    AmtScreenResult,
    amt_screen,
)
from telos.engine.brackets import Bracket, marginal_rate, tax_from_brackets
from telos.engine.form1040 import Form1040Inputs, Form1040Result, assemble_1040
from telos.engine.form8949 import BoxTotals, WashSaleRiskError, check_wash_risk, form8949_totals
from telos.engine.form8959 import Form8959Result, MissingMedicareWagesError, form8959
from telos.engine.form8960 import Form8960Inputs, Form8960Result, form8960
from telos.engine.guard import (
    CoverageError,
    CoverageGuard,
    UnsupportedDocumentError,
    UnsupportedFieldError,
)
from telos.engine.qdcgt import QdcgtResult, qdcgt_worksheet
from telos.engine.reconcile_lots import FieldMismatch, LotReconciliation, reconcile_lots
from telos.engine.rounding import round_whole_dollar, to_decimal
from telos.engine.schedule_a import (
    ScheduleAInputs,
    ScheduleAResult,
    choose_deduction,
    schedule_a,
)
from telos.engine.schedule_d import ScheduleDInputs, ScheduleDResult, schedule_d
from telos.engine.schedule_e import ScheduleEResult, require_qbi_total, schedule_e
from telos.engine.tax_lookup import line16_tax, line16_tax_amount, tax_from_table
from telos.engine.trace import Traced, traced_sum

__all__ = [
    "AmtGuardInputs",
    "AmtReviewRequired",
    "AmtScreenResult",
    "BoxTotals",
    "Bracket",
    "CoverageError",
    "CoverageGuard",
    "FieldMismatch",
    "Form1040Inputs",
    "Form1040Result",
    "Form8959Result",
    "Form8960Inputs",
    "Form8960Result",
    "LotReconciliation",
    "MissingMedicareWagesError",
    "QdcgtResult",
    "ScheduleAInputs",
    "ScheduleAResult",
    "ScheduleDInputs",
    "ScheduleDResult",
    "ScheduleEResult",
    "Traced",
    "UnsupportedDocumentError",
    "UnsupportedFieldError",
    "WashSaleRiskError",
    "amt_screen",
    "assemble_1040",
    "check_wash_risk",
    "choose_deduction",
    "form8949_totals",
    "form8959",
    "form8960",
    "line16_tax",
    "line16_tax_amount",
    "marginal_rate",
    "qdcgt_worksheet",
    "reconcile_lots",
    "require_qbi_total",
    "round_whole_dollar",
    "schedule_a",
    "schedule_d",
    "schedule_e",
    "tax_from_brackets",
    "tax_from_table",
    "to_decimal",
    "traced_sum",
]
