"""Schedule E contract + consumption — regime invariants, flags, seams."""

import json
from decimal import Decimal
from pathlib import Path

import pytest
from pydantic import ValidationError

from telos.contracts import (
    LossRegime,
    RentalArrangement,
    ScheduleEWorksheet,
    schedule_e_worksheet_json_schema,
)
from telos.engine import Form1040Inputs, assemble_1040
from telos.engine.guard import CoverageError
from telos.engine.schedule_e import require_qbi_total, schedule_e
from telos.models import FilingStatus
from telos.params import load_pack

D = Decimal
ROOT = Path(__file__).parent.parent
PACK = load_pack(ROOT / "params" / "ty2025.yaml")


def arrangement(**overrides):
    base = dict(
        arrangement_id="ballard-room",
        property_name="Ballard townhome",
        regime=LossRegime.SECTION_280A,
        net_income_post_caps=D(4_000),
        depreciation_taken=D(1_800),
        qbi_eligible_income=D(4_000),
        source="manual:filed-return-transcription",
    )
    base.update(overrides)
    return RentalArrangement(**base)


def worksheet(*arrangements, tax_year=2025):
    return ScheduleEWorksheet(tax_year=tax_year, arrangements=tuple(arrangements))


class TestContract:
    def test_committed_schema_artifact_matches_models(self):
        committed = json.loads(
            (ROOT / "contracts" / "schedule_e_worksheet.schema.json").read_text()
        )
        assert committed == json.loads(
            json.dumps(schedule_e_worksheet_json_schema(), sort_keys=True)
        ), "contracts/schedule_e_worksheet.schema.json drifted — regenerate"

    def test_not_for_profit_loss_rejected(self):
        with pytest.raises(ValidationError, match=r"cannot show a loss"):
            arrangement(regime=LossRegime.NOT_FOR_PROFIT, net_income_post_caps=D(-100))

    def test_280a_negative_net_rejected(self):
        with pytest.raises(ValidationError, match="280A"):
            arrangement(net_income_post_caps=D(-500))

    def test_469_loss_allowed(self):
        a = arrangement(
            arrangement_id="wadsworth", property_name="Wadsworth duplex",
            regime=LossRegime.SECTION_469_PASSIVE, net_income_post_caps=D(-2_500),
            suspended_loss_carryforward=D(1_200), qbi_eligible_income=D(-2_500),
        )
        assert a.net_income_post_caps == D(-2_500)

    def test_manual_path_is_the_identical_contract_object(self):
        """The 'manual fallback' is literally constructing the same model —
        equality with a parsed-JSON version proves no second path exists."""
        manual = worksheet(arrangement())
        parsed = ScheduleEWorksheet.model_validate_json(manual.model_dump_json())
        assert parsed == manual


class TestConsumption:
    def _two_property_ws(self):
        return worksheet(
            arrangement(),  # ballard 280A +4,000
            arrangement(
                arrangement_id="wadsworth", property_name="Wadsworth duplex",
                regime=LossRegime.SECTION_469_PASSIVE, net_income_post_caps=D(-2_500),
                suspended_loss_carryforward=D(1_200), qbi_eligible_income=D(-2_500),
                contested_flags=("28-day-vs-60-day stay character",),
                source="ktema",
            ),
        )

    def test_totals_and_seams(self):
        r = schedule_e(self._two_property_ws(), expected_tax_year=2025)
        assert r.total.value == D(1_500)
        assert r.total_for_8960_line4a.value == D(1_500)
        assert r.form_8582_expected is True
        assert r.cpa_confirm_items == ("wadsworth: 28-day-vs-60-day stay character",)

    def test_contested_flags_ride_the_audit_trail(self):
        r = schedule_e(self._two_property_ws(), expected_tax_year=2025)
        assert any("CPA-CONFIRM" in s for s in r.total.all_sources())

    def test_qbi_total_when_fully_determined(self):
        r = schedule_e(self._two_property_ws(), expected_tax_year=2025)
        assert require_qbi_total(r).value == D(1_500)

    def test_undetermined_qbi_fails_loud_at_accessor(self):
        ws = worksheet(arrangement(qbi_eligible_income=None))
        r = schedule_e(ws, expected_tax_year=2025)
        assert r.qbi_total is None
        with pytest.raises(CoverageError, match="QBI eligibility undetermined"):
            require_qbi_total(r)

    def test_no_8582_flag_without_suspension(self):
        r = schedule_e(worksheet(arrangement()), expected_tax_year=2025)
        assert r.form_8582_expected is False

    def test_wrong_tax_year_refused(self):
        with pytest.raises(CoverageError, match="TY2024"):
            schedule_e(worksheet(arrangement(), tax_year=2024), expected_tax_year=2025)

    def test_empty_worksheet_refused(self):
        with pytest.raises(CoverageError, match="no arrangements"):
            schedule_e(worksheet(), expected_tax_year=2025)

    def test_flows_into_1040_schedule_1_seam(self):
        r = schedule_e(self._two_property_ws(), expected_tax_year=2025)
        result = assemble_1040(
            Form1040Inputs(
                filing_status=FilingStatus.SINGLE,
                schedule_1_income=r.total.value,
            ),
            PACK,
        )
        assert result.lines["8"].value == D(1_500)
        assert result.lines["9"].value == D(1_500)
