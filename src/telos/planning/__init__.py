"""Year-round tax planning: projection + 1040-ES payment flagging.

``python -m telos.planning <scenario.yaml> --pack params/ty2026.yaml``
renders the report and (with ``--out`` or ``TELOS_WORK_DIR``) writes the
versioned ``TaxProjection`` artifact consumed by dashboards.
"""

from telos.planning.flags import flag_quarters
from telos.planning.projection import ProjectionOutcome, build_full_year_inputs, project
from telos.planning.scenario import (
    PLANNING_SCENARIO_SCHEMA_VERSION,
    EstimatedPaymentMade,
    PlanningScenario,
)

__all__ = [
    "PLANNING_SCENARIO_SCHEMA_VERSION",
    "EstimatedPaymentMade",
    "PlanningScenario",
    "ProjectionOutcome",
    "build_full_year_inputs",
    "flag_quarters",
    "project",
]
