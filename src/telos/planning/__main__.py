"""CLI: ``python -m telos.planning <scenario.yaml> [--pack PATH] [--out PATH]``.

I/O lives HERE (the engine stays pure): read the scenario YAML (typically
from ``TELOS_DATA_DIR`` — personal data, never in a repo), load the target
year's parameter pack, print the report, and write the ``TaxProjection``
artifact JSON.

Artifact destination resolution:
1. ``--out`` — explicit path;
2. ``$TELOS_WORK_DIR/planning/tax_projection_ty{year}.json``;
3. neither set -> report-only (printed), no file written.

Writes NEVER target ``TELOS_SOURCE_DIR`` (read-only by contract, plan §5.5).
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

import yaml

from telos.params import load_pack
from telos.planning.projection import project
from telos.planning.report import render_report
from telos.planning.scenario import PlanningScenario

WORK_DIR_ENV = "TELOS_WORK_DIR"


def _default_pack_path(tax_year: int) -> Path:
    candidate = Path("params") / f"ty{tax_year}.yaml"
    if candidate.exists():
        return candidate
    raise SystemExit(
        f"no --pack given and {candidate} not found relative to the current "
        f"directory — pass --pack /path/to/ty{tax_year}.yaml"
    )


def _default_out_path(tax_year: int) -> Path | None:
    work_dir = os.environ.get(WORK_DIR_ENV)
    if not work_dir:
        return None
    return Path(work_dir) / "planning" / f"tax_projection_ty{tax_year}.json"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m telos.planning",
        description="Project full-year tax from an income-expectations scenario "
        "and flag 1040-ES payments.",
    )
    parser.add_argument("scenario", type=Path, help="scenario YAML (see PlanningScenario)")
    parser.add_argument("--pack", type=Path, default=None,
                        help="parameter pack YAML (default: params/ty{year}.yaml)")
    parser.add_argument("--out", type=Path, default=None,
                        help="artifact JSON destination (default: "
                        "$TELOS_WORK_DIR/planning/tax_projection_ty{year}.json)")
    args = parser.parse_args(argv)

    scenario = PlanningScenario.model_validate(
        yaml.safe_load(args.scenario.read_text())
    )
    pack_path = args.pack if args.pack is not None else _default_pack_path(scenario.tax_year)
    pack = load_pack(pack_path)

    outcome = project(scenario, pack)
    print(render_report(outcome))

    out_path = args.out if args.out is not None else _default_out_path(scenario.tax_year)
    if out_path is not None:
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(outcome.artifact.model_dump_json(indent=2) + "\n")
        print(f"\nartifact written: {out_path}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
