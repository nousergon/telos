"""Contract, 8949 grouping, Schedule D roll-up, wash-risk guard, reconciliation."""

import json
from decimal import Decimal
from pathlib import Path

import pytest
from pydantic import ValidationError

from telos.contracts import (
    Form8949Box,
    RealizedLot,
    RealizedLots,
    Term,
    realized_lots_json_schema,
)
from telos.engine import (
    Form1040Inputs,
    ScheduleDInputs,
    WashSaleRiskError,
    assemble_1040,
    form8949_totals,
    reconcile_lots,
    schedule_d,
)
from telos.engine.guard import CoverageError
from telos.models import FilingStatus
from telos.params import load_pack

D = Decimal
ROOT = Path(__file__).parent.parent
PACK = load_pack(ROOT / "params" / "ty2025.yaml")


def lot(desc="ACME", acq="2024-01-10", sold="2025-06-01", proceeds=10_000,
        basis=8_000, wash=0, term=Term.LONG, box=Form8949Box.D, source="test"):
    return RealizedLot(
        description=desc, date_acquired=acq, date_sold=sold,
        proceeds=D(proceeds), cost_basis=D(basis), wash_sale_disallowed=D(wash),
        term=term, box=box, source=source,
    )


def sched_d(lots, **kw):
    kw.setdefault("filing_status", FilingStatus.SINGLE)
    return schedule_d(ScheduleDInputs(realized=RealizedLots(lots=tuple(lots)), **kw))


class TestContract:
    def test_committed_schema_artifact_matches_models(self):
        committed = json.loads((ROOT / "contracts" / "realized_lots.schema.json").read_text())
        assert committed == json.loads(
            json.dumps(realized_lots_json_schema(), sort_keys=True)
        ), "contracts/realized_lots.schema.json drifted — regenerate from the models"

    def test_box_term_mismatch_rejected(self):
        with pytest.raises(ValidationError, match="short-term box"):
            lot(term=Term.LONG, box=Form8949Box.A)

    def test_digital_asset_boxes_accepted(self):
        crypto = lot(desc="BTC", box=Form8949Box.J, term=Term.LONG, source="cointracker")
        assert crypto.box is Form8949Box.J

    def test_gain_includes_wash_adjustment(self):
        washed = lot(proceeds=5_000, basis=6_000, wash=400)
        assert washed.gain == D(-600)


class TestForm8949:
    def test_groups_by_box_with_adjustments(self):
        rows = form8949_totals(RealizedLots(lots=(
            lot(desc="A1", proceeds=10_000, basis=8_000),
            lot(desc="A2", proceeds=5_000, basis=6_000, wash=400),
            lot(desc="S1", term=Term.SHORT, box=Form8949Box.A, proceeds=3_000, basis=2_500),
        )))
        by_box = {r.box: r for r in rows}
        d_row = by_box[Form8949Box.D]
        assert d_row.proceeds.value == D(15_000)
        assert d_row.adjustments.value == D(400)
        assert d_row.gain.value == D(1_400)  # 15,000 - 14,000 + 400
        assert by_box[Form8949Box.A].gain.value == D(500)

    def test_wash_risk_guard_fires_on_repurchase_within_30_days(self):
        with pytest.raises(WashSaleRiskError, match="RKLB"):
            form8949_totals(RealizedLots(lots=(
                lot(desc="RKLB", proceeds=4_000, basis=6_000, sold="2025-03-01",
                    term=Term.SHORT, box=Form8949Box.A),
                lot(desc="RKLB", acq="2025-03-15", sold="2025-11-01",
                    proceeds=7_000, basis=5_000, term=Term.SHORT, box=Form8949Box.A),
            )))

    def test_wash_risk_quiet_when_broker_reported(self):
        rows = form8949_totals(RealizedLots(lots=(
            lot(desc="RKLB", proceeds=4_000, basis=6_000, sold="2025-03-01",
                wash=2_000, term=Term.SHORT, box=Form8949Box.A),
            lot(desc="RKLB", acq="2025-03-15", sold="2025-11-01",
                proceeds=7_000, basis=5_000, term=Term.SHORT, box=Form8949Box.A),
        )))
        assert rows  # no raise

    def test_wash_risk_quiet_outside_window(self):
        form8949_totals(RealizedLots(lots=(
            lot(desc="TSLA", proceeds=4_000, basis=6_000, sold="2025-03-01",
                term=Term.SHORT, box=Form8949Box.A),
            lot(desc="TSLA", acq="2025-05-01", sold="2025-11-01",
                proceeds=7_000, basis=5_000, term=Term.SHORT, box=Form8949Box.A),
        )))


class TestScheduleD:
    def test_mixed_boxes_roll_up_hand_computed(self):
        """ST: box A gain 500 (line 1b) + box H (crypto) gain -200 (line 2)
        -> line 7 = 300. LT: box D gain 2,000 (8b) + box J gain 1,000 (8b too)
        + distributions 150 (13) -> line 15 = 3,150. Line 16 = 3,450 -> 7a."""
        r = sched_d(
            [
                lot(desc="S", term=Term.SHORT, box=Form8949Box.A, proceeds=1_500, basis=1_000),
                lot(desc="ETH", term=Term.SHORT, box=Form8949Box.H, proceeds=800, basis=1_000),
                lot(desc="L", proceeds=12_000, basis=10_000),
                lot(desc="BTC", box=Form8949Box.J, proceeds=3_000, basis=2_000),
            ],
            capital_gain_distributions=D(150),
        )
        assert r.lines["7"].value == D(300)
        assert r.lines["8b"].value == D(3_000)  # boxes D|J fold into 8b
        assert r.lines["15"].value == D(3_150)
        assert r.line7a.value == D(3_450)
        assert r.qdcgt_net_capital_gain.value == D(3_150)  # smaller of 15/16

    def test_loss_year_limited_to_3000(self):
        r = sched_d([lot(proceeds=1_000, basis=9_000)])  # -8,000 LT
        assert r.lines["16"].value == D(-8_000)
        assert r.line7a.value == D(-3_000)
        assert r.qdcgt_net_capital_gain.value == D(0)

    def test_mfs_loss_limit_1500(self):
        r = sched_d([lot(proceeds=1_000, basis=9_000)],
                    filing_status=FilingStatus.MARRIED_FILING_SEPARATELY)
        assert r.line7a.value == D(-1_500)

    def test_st_gain_lt_loss_qdcgt_zero(self):
        """Line 15 loss, line 16 gain: QDCGT L3 is 0 (both must be gains)."""
        r = sched_d([
            lot(desc="S", term=Term.SHORT, box=Form8949Box.A, proceeds=9_000, basis=2_000),
            lot(desc="L", proceeds=1_000, basis=3_000),
        ])
        assert r.lines["16"].value == D(5_000)
        assert r.qdcgt_net_capital_gain.value == D(0)

    def test_carryovers_subtract(self):
        r = sched_d([lot(proceeds=10_000, basis=4_000)],
                    st_loss_carryover=D(1_000), lt_loss_carryover=D(2_000))
        assert r.lines["15"].value == D(4_000)
        assert r.lines["7"].value == D(-1_000)
        assert r.line7a.value == D(3_000)

    def test_28pct_or_1250_guard(self):
        with pytest.raises(CoverageError, match="Schedule D Tax"):
            sched_d([lot()], unrecaptured_1250=D(5_000))

    def test_feeds_1040_end_to_end(self):
        r = sched_d([lot(proceeds=60_000, basis=20_000)])
        result = assemble_1040(
            Form1040Inputs(
                filing_status=FilingStatus.SINGLE,
                capital_gain_line7=r.line7a.value,
                qdcgt_net_capital_gain=r.qdcgt_net_capital_gain.value,
            ),
            PACK,
        )
        assert result.qdcgt is not None
        assert result.lines["7"].value == D(40_000)

    def test_provenance_reaches_lot_sources(self):
        r = sched_d([lot(source="fidelity-1099b-2025")])
        assert "fidelity-1099b-2025" in r.line7a.all_sources()


class TestReconciliation:
    def _metron(self):
        return RealizedLots(lots=(
            lot(desc="ACME", source="metron"),
            lot(desc="BTC", box=Form8949Box.J, proceeds=3_000, basis=2_000, source="metron"),
        ))

    def test_clean_match(self):
        broker = RealizedLots(lots=(
            lot(desc="ACME", source="fidelity"),
            lot(desc="BTC", box=Form8949Box.J, proceeds=3_000, basis=2_000, source="1099-DA"),
        ))
        rec = reconcile_lots(self._metron(), broker)
        assert rec.is_clean and rec.matched_clean == 2

    def test_injected_basis_mismatch_surfaced_per_lot(self):
        broker = RealizedLots(lots=(
            lot(desc="ACME", basis=8_500, source="fidelity"),  # injected +500 basis
            lot(desc="BTC", box=Form8949Box.J, proceeds=3_000, basis=2_000, source="1099-DA"),
        ))
        rec = reconcile_lots(self._metron(), broker)
        assert not rec.is_clean
        assert len(rec.mismatches) == 1
        m = rec.mismatches[0]
        assert m.field_name == "cost_basis"
        assert m.metron_value == D(8_000) and m.broker_value == D(8_500)
        assert "delta -500" in str(m)

    def test_unmatched_lots_listed_both_sides(self):
        broker = RealizedLots(lots=(lot(desc="ACME", source="fidelity"),))
        rec = reconcile_lots(self._metron(), broker)
        assert rec.only_in_metron == (("BTC", "2024-01-10", "2025-06-01"),)
        assert rec.only_in_broker == ()

    def test_duplicate_keys_rejected(self):
        dupes = RealizedLots(lots=(lot(source="a"), lot(source="b")))
        with pytest.raises(ValueError, match="duplicate lot keys"):
            reconcile_lots(dupes, self._metron())

    def test_report_renders(self):
        broker = RealizedLots(lots=(lot(desc="ACME", basis=8_500, source="fidelity"),))
        text = reconcile_lots(self._metron(), broker).report()
        assert "MISMATCH" in text and "METRON-ONLY" in text
