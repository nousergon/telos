"""telos.planning.feeder: actuals-to-date scenario builder (telos-ops#19).

Synthetic fixtures only — no personal data. The end-to-end acceptance
criterion (Closes-when) is exercised directly: a synthetic Metron-shaped
export builds a scenario that ``python -m telos.planning`` accepts.
"""

from __future__ import annotations

import json
from decimal import Decimal
from pathlib import Path

import pytest
import yaml
from pydantic import ValidationError

from telos.contracts import Form8949Box, RealizedLot, RealizedLots, Term
from telos.models import FilingStatus, Form1099Div, Form1099Int
from telos.params import load_pack
from telos.planning.feeder import (
    MetronActualsExport,
    build_actuals_scenario_yaml,
    net_realized_gains,
)
from telos.planning.projection import project
from telos.planning.scenario import PlanningScenario

D = Decimal
ROOT = Path(__file__).parent.parent
PACK_2026 = load_pack(ROOT / "params" / "ty2026.yaml")


def synthetic_lot(desc, acq, sold, proceeds, basis, term, box, wash=0):
    return RealizedLot(
        description=desc,
        date_acquired=acq,
        date_sold=sold,
        proceeds=D(proceeds),
        cost_basis=D(basis),
        wash_sale_disallowed=D(wash),
        term=term,
        box=box,
        source="metron:synthetic-export",
    )


def synthetic_export(**overrides) -> MetronActualsExport:
    base = dict(
        tax_year=2026,
        as_of="2026-07-01",
        filing_status=FilingStatus.SINGLE,
        prior_year_agi=D(90_000),
        prior_year_tax=D(13_000),
        realized_lots=RealizedLots(
            lots=(
                synthetic_lot(
                    "SYNTH LONG LOT", "2024-01-15", "2026-03-01",
                    12_000, 9_000, Term.LONG, Form8949Box.F,
                ),
                synthetic_lot(
                    "SYNTH SHORT LOT", "2026-02-01", "2026-04-01",
                    5_000, 6_000, Term.SHORT, Form8949Box.C,
                ),
            )
        ),
        forms_1099_div_ytd=(
            Form1099Div(
                payer="Synth Brokerage",
                ordinary_dividends=D(300),
                qualified_dividends=D(250),
            ),
        ),
        forms_1099_int_ytd=(
            Form1099Int(payer="Synth Bank", interest_income=D(50)),
        ),
    )
    base.update(overrides)
    return MetronActualsExport(**base)


class TestNetRealizedGains:
    def test_nets_by_term(self):
        st, lt = net_realized_gains(synthetic_export().realized_lots)
        assert st == D(-1_000)  # 5,000 proceeds - 6,000 basis
        assert lt == D(3_000)  # 12,000 proceeds - 9,000 basis

    def test_empty_lots_net_to_zero(self):
        st, lt = net_realized_gains(RealizedLots())
        assert st == D(0)
        assert lt == D(0)

    def test_wash_sale_disallowed_folds_into_gain(self):
        lots = RealizedLots(
            lots=(
                synthetic_lot(
                    "WASH LOT", "2026-01-01", "2026-02-01",
                    1_000, 2_000, Term.SHORT, Form8949Box.C, wash=500,
                ),
            )
        )
        st, _ = net_realized_gains(lots)
        assert st == D(-500)  # 1,000 - 2,000 + 500 disallowed


class TestBuildActualsScenarioYaml:
    def test_produces_valid_planning_scenario(self):
        rendered = build_actuals_scenario_yaml(synthetic_export())
        scenario = PlanningScenario.model_validate(yaml.safe_load(rendered))
        assert scenario.tax_year == 2026
        assert scenario.as_of == "2026-07-01"
        assert scenario.st_net_gain == D(-1_000)
        assert scenario.lt_net_gain == D(3_000)
        assert scenario.forms_1099_div[0].ordinary_dividends == D(300)
        assert scenario.forms_1099_int[0].interest_income == D(50)

    def test_w2_placeholder_is_explicit_zero_not_omitted(self):
        rendered = build_actuals_scenario_yaml(synthetic_export())
        scenario = PlanningScenario.model_validate(yaml.safe_load(rendered))
        assert len(scenario.w2s) == 1
        assert scenario.w2s[0].wages == D(0)
        assert "# TODO expectations" in rendered

    def test_no_dividends_or_interest_omits_those_sections(self):
        export = synthetic_export(forms_1099_div_ytd=(), forms_1099_int_ytd=())
        rendered = build_actuals_scenario_yaml(export)
        assert "forms_1099_div:" not in rendered
        assert "forms_1099_int:" not in rendered
        # still a valid scenario
        PlanningScenario.model_validate(yaml.safe_load(rendered))

    def test_todo_expectations_marks_every_unknown_or_partial_field(self):
        rendered = build_actuals_scenario_yaml(synthetic_export())
        # capital gains (partially known — realized-to-date only)
        assert "st_net_gain:" in rendered and "# TODO expectations" in rendered
        assert "lt_net_gain:" in rendered
        # dividends/interest (YTD actual only)
        assert "ordinary_dividends:" in rendered
        assert "interest_income:" in rendered
        # every unknown/partial field is marked, never silently omitted
        assert rendered.count("# TODO expectations") >= 8

    def test_realized_to_date_values_not_silently_zero_when_known(self):
        rendered = build_actuals_scenario_yaml(synthetic_export())
        assert 'lt_net_gain: "3000"' in rendered

    def test_amounts_are_quoted_yaml_strings(self):
        rendered = build_actuals_scenario_yaml(synthetic_export())
        loaded = yaml.safe_load(rendered)
        assert isinstance(loaded["st_net_gain"], str)
        assert isinstance(loaded["lt_net_gain"], str)
        assert isinstance(loaded["prior_year_agi"], str)


class TestEndToEndAcceptance:
    """Closes-when: a synthetic Metron export -> valid scenario -> accepted
    end-to-end by ``python -m telos.planning`` (via the same ``project()``
    the CLI calls)."""

    def test_synthetic_export_projects_cleanly(self):
        rendered = build_actuals_scenario_yaml(synthetic_export())
        scenario = PlanningScenario.model_validate(yaml.safe_load(rendered))
        outcome = project(scenario, PACK_2026)
        # net capital activity flows into AGI: 3,000 LT net + 350 div/int - 1,000 ST net...
        # (synthesized aggregate lots ride the real Schedule D netting)
        assert outcome.artifact.tax_year == 2026
        assert outcome.artifact.projected.agi >= D(0)

    def test_cli_main_accepts_feeder_output(self, tmp_path):
        from telos.planning.__main__ import main as planning_main

        rendered = build_actuals_scenario_yaml(synthetic_export())
        scenario_path = tmp_path / "scenario.yaml"
        scenario_path.write_text(rendered)
        out = tmp_path / "proj.json"
        rc = planning_main(
            [str(scenario_path), "--pack", str(ROOT / "params" / "ty2026.yaml"), "--out", str(out)]
        )
        assert rc == 0
        written = json.loads(out.read_text())
        assert written["schema_version"].startswith("1.")


class TestMetronActualsExportGuards:
    def test_extra_field_rejected(self):
        with pytest.raises(ValidationError):
            MetronActualsExport.model_validate(
                {
                    "tax_year": 2026,
                    "as_of": "2026-07-01",
                    "filing_status": "single",
                    "prior_year_agi": "90000",
                    "prior_year_tax": "13000",
                    "unexpected_field": "nope",
                }
            )

    def test_as_of_must_be_iso_date(self):
        with pytest.raises(ValidationError, match="ISO date"):
            synthetic_export(as_of="not-a-date")


class TestFeederCli:
    def test_writes_to_out_path(self, tmp_path):
        from telos.planning.feeder import main as feeder_main

        export_path = tmp_path / "export.yaml"
        export_path.write_text(
            yaml.safe_dump(
                {
                    "tax_year": 2026,
                    "as_of": "2026-07-01",
                    "filing_status": "single",
                    "prior_year_agi": "90000",
                    "prior_year_tax": "13000",
                    "realized_lots": {
                        "lots": [
                            {
                                "description": "SYNTH",
                                "date_acquired": "2024-01-01",
                                "date_sold": "2026-06-01",
                                "proceeds": "10000",
                                "cost_basis": "7000",
                                "term": "long",
                                "box": "F",
                                "source": "metron:synthetic",
                            }
                        ]
                    },
                }
            )
        )
        out_path = tmp_path / "scenario.yaml"
        rc = feeder_main([str(export_path), "--out", str(out_path)])
        assert rc == 0
        scenario = PlanningScenario.model_validate(yaml.safe_load(out_path.read_text()))
        assert scenario.lt_net_gain == D(3_000)

    def test_no_out_prints_to_stdout(self, tmp_path, capsys, monkeypatch):
        from telos.planning.feeder import main as feeder_main

        monkeypatch.delenv("TELOS_WORK_DIR", raising=False)
        export_path = tmp_path / "export.yaml"
        export_path.write_text(
            yaml.safe_dump(
                {
                    "tax_year": 2026,
                    "as_of": "2026-07-01",
                    "filing_status": "single",
                    "prior_year_agi": "90000",
                    "prior_year_tax": "13000",
                }
            )
        )
        rc = feeder_main([str(export_path)])
        assert rc == 0
        out = capsys.readouterr().out
        assert "schema_version" in out

    def test_default_out_uses_work_dir_env(self, tmp_path, monkeypatch):
        from telos.planning.feeder import main as feeder_main

        monkeypatch.setenv("TELOS_WORK_DIR", str(tmp_path))
        export_path = tmp_path / "export.yaml"
        export_path.write_text(
            yaml.safe_dump(
                {
                    "tax_year": 2026,
                    "as_of": "2026-07-01",
                    "filing_status": "single",
                    "prior_year_agi": "90000",
                    "prior_year_tax": "13000",
                }
            )
        )
        rc = feeder_main([str(export_path)])
        assert rc == 0
        expected = tmp_path / "planning" / "scenario_ty2026.yaml"
        assert expected.exists()
        PlanningScenario.model_validate(yaml.safe_load(expected.read_text()))
