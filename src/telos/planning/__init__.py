"""Year-round tax planning: actuals feeder + projection + 1040-ES flagging.

``python -m telos.planning.feeder <actuals-export.yaml>`` pre-fills the
actuals half of a ``PlanningScenario`` from a Metron realized-lots export
plus YTD dividends/interest (telos-ops#19), leaving the expectations half for
the human. ``python -m telos.planning <scenario.yaml> --pack
params/ty2026.yaml`` then renders the report and (with ``--out`` or
``TELOS_WORK_DIR``) writes the versioned ``TaxProjection`` artifact consumed
by dashboards.
"""

from telos.planning.flags import flag_quarters
from telos.planning.projection import ProjectionOutcome, build_full_year_inputs, project
from telos.planning.scenario import (
    PLANNING_SCENARIO_SCHEMA_VERSION,
    EstimatedPaymentMade,
    PlanningScenario,
)

# telos.planning.feeder is deliberately NOT re-exported here (like
# telos.planning.report / telos.planning.__main__): it's runnable directly
# (``python -m telos.planning.feeder``), and importing it eagerly at the
# package level would make that invocation re-import the module under two
# names (RuntimeWarning). Use ``from telos.planning.feeder import ...`` for
# library access.

__all__ = [
    "PLANNING_SCENARIO_SCHEMA_VERSION",
    "EstimatedPaymentMade",
    "PlanningScenario",
    "ProjectionOutcome",
    "build_full_year_inputs",
    "flag_quarters",
    "project",
]
