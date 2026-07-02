"""Replay harness, CI side: synthetic fixture end-to-end, diffs, guards.

The synthetic fixture's goldens are hand-computed in the docstring of
``TestSyntheticDressRehearsal`` so a reviewer can re-derive every number.
"""

from decimal import Decimal
from pathlib import Path

import pytest

from telos.engine.guard import CoverageError
from telos.params import load_pack
from telos.replay import (
    ReplayFixture,
    fixture_path,
    load_fixture,
    run_replay,
    source_write_guard,
)

D = Decimal
ROOT = Path(__file__).parent.parent
PACK = load_pack(ROOT / "params" / "ty2025.yaml")
SYNTH = ROOT / "tests" / "fixtures" / "synthetic_ty2025_replay.json"


class TestSyntheticDressRehearsal:
    """Wages 200,000 (box5 210,000, box6 3,135, wh 40,000) + interest 1,000
    + dividends 8,000 (6,000 qualified) + one LT lot gain 20,000 + Schedule E
    5,000 -> AGI 234,000. Schedule A: SALT 17,000 (under cap) + mortgage
    18,000 + charity 2,000 = 37,000 itemized (beats 15,750). TI before QBI
    197,000 <= threshold -> QBI = 20% * 5,000 = 1,000. Taxable 196,000.
    QDCGT: preferential 26,000; L22 = TCW(170,000) = .24*170,000 - 7,153 =
    33,647; L18 = 3,900; L23 = 37,547 < L24 = 39,887 -> line 16 = 37,547.
    8959: 0.9% * 10,000 = 90 tax and 90 withholding credit. 8960: NII
    34,000, MAGI excess 34,000 -> 1,292. Total tax 38,929; payments 40,000
    + 90 = 40,090 -> balance -1,161 (refund)."""

    def test_loads_and_replays_clean(self):
        fixture = load_fixture(SYNTH)
        report = run_replay(fixture, PACK)
        assert report.is_clean, "\n" + report.render()
        assert len(report.rows) == 17

    def test_injected_mismatch_is_surfaced_not_averaged(self):
        fixture = load_fixture(SYNTH)
        tampered = fixture.model_copy(
            update={"golden": {**fixture.golden, "total_tax": D(38_930)}}
        )
        report = run_replay(tampered, PACK)
        assert not report.is_clean
        assert len(report.mismatches) == 1
        assert "DIFF" in report.render() and "delta -1" in report.render()

    def test_unknown_golden_name_fails_loud(self):
        fixture = load_fixture(SYNTH)
        bad = fixture.model_copy(update={"golden": {**fixture.golden, "line_999": D(1)}})
        with pytest.raises(CoverageError, match="line_999"):
            run_replay(bad, PACK)

    def test_ohio_golden_without_pack_fails_loud(self):
        import json

        raw = json.loads(SYNTH.read_text())
        raw["ohio"] = {
            "filing_status": "single",
            "federal_agi": 234000,
            "total_business_income": 5000,
            "ohio_sourced_business_income": 0,
        }
        with pytest.raises(CoverageError, match="no Ohio pack"):
            run_replay(ReplayFixture.model_validate(raw), PACK)


class TestFixtureResolution:
    def test_explicit_env_wins(self, monkeypatch, tmp_path):
        monkeypatch.setenv("TELOS_REPLAY_FIXTURE", str(tmp_path / "x.json"))
        assert fixture_path(2025) == tmp_path / "x.json"

    def test_source_dir_convention(self, monkeypatch, tmp_path):
        monkeypatch.delenv("TELOS_REPLAY_FIXTURE", raising=False)
        f = tmp_path / "telos" / "ty2025_replay.json"
        f.parent.mkdir()
        f.write_text("{}")
        monkeypatch.setenv("TELOS_SOURCE_DIR", str(tmp_path))
        monkeypatch.delenv("TELOS_WORK_DIR", raising=False)
        assert fixture_path(2025) == f

    def test_absent_everywhere_returns_none(self, monkeypatch):
        for env in ("TELOS_REPLAY_FIXTURE", "TELOS_SOURCE_DIR", "TELOS_WORK_DIR"):
            monkeypatch.delenv(env, raising=False)
        assert fixture_path(2025) is None


class TestSourceWriteGuard:
    def test_write_under_source_dir_refused(self, monkeypatch, tmp_path):
        monkeypatch.setenv("TELOS_SOURCE_DIR", str(tmp_path))
        with (
            source_write_guard(),
            pytest.raises(PermissionError, match="write-guard"),
            open(tmp_path / "evil.txt", "w"),
        ):
            pass  # never reached — the open itself raises

    def test_reads_pass_and_writes_elsewhere_pass(self, monkeypatch, tmp_path):
        src = tmp_path / "src"
        src.mkdir()
        (src / "doc.txt").write_text("hi")
        monkeypatch.setenv("TELOS_SOURCE_DIR", str(src))
        with source_write_guard():
            with open(src / "doc.txt") as f:
                assert f.read() == "hi"
            (tmp_path / "work.txt").write_text("ok")  # outside source root

    def test_guard_restores_open(self, monkeypatch, tmp_path):
        import builtins

        monkeypatch.setenv("TELOS_SOURCE_DIR", str(tmp_path))
        original = builtins.open
        with source_write_guard():
            pass
        assert builtins.open is original
