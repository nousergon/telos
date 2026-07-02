"""The M1 replay gate — runs ONLY on the operator's machine, never in CI.

Reads the personal fixture per the resolution order in ``telos.replay``
(``$TELOS_REPLAY_FIXTURE`` -> ``$TELOS_SOURCE_DIR/telos/ty2025_replay.json``
-> ``$TELOS_WORK_DIR/fixtures/ty2025_replay.json``), arms the read-only
source guard, and requires EVERY golden transcribed from the filed TY2025
return to reproduce exactly. This passing is the plan's P0 exit criterion.
"""

from pathlib import Path

import pytest

from telos.params import load_pack
from telos.replay import fixture_path, load_fixture, run_replay, source_write_guard

ROOT = Path(__file__).parent.parent
PERSONAL = fixture_path(2025)

pytestmark = pytest.mark.personal


@pytest.mark.skipif(
    PERSONAL is None,
    reason="no personal TY2025 replay fixture found (TELOS_REPLAY_FIXTURE / "
    "TELOS_SOURCE_DIR / TELOS_WORK_DIR) — CI stays green without personal data",
)
def test_ty2025_replay_gate():
    fixture = load_fixture(PERSONAL)
    pack = load_pack(ROOT / "params" / "ty2025.yaml")
    ohio_pack = load_pack(ROOT / "params" / "ty2025_oh.yaml")
    with source_write_guard():
        report = run_replay(fixture, pack, ohio_pack=ohio_pack)
    assert report.is_clean, (
        "\nTY2025 REPLAY GATE FAILED — every line must reproduce the filed "
        "return to the dollar:\n" + report.render()
    )
