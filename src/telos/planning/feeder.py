"""The actuals feeder: pre-fill the ACTUALS half of a ``PlanningScenario``.

telos-ops#19 — "replace hand-typed YAML sections". A ``PlanningScenario`` is
the human's income *expectations* for the year (``telos.planning.scenario``);
building it by hand means re-typing the same realized-to-date numbers every
quarter. This module is a convenience layer over that chore: it reads a
:class:`MetronActualsExport` (realized capital lots, in the existing
``telos.contracts.RealizedLots`` shape — the same feed the Form 8949 module
consumes — plus YTD dividends/interest in the existing ``telos.models``
per-payer shapes) and nets/passes it straight through into scenario fields,
leaving every full-year EXPECTATION for the human.

Deterministic transformation only — no LLM anywhere in this module (the
arithmetic-path invariant ``telos.engine`` holds; this feeder inherits the
same posture even though it sits in ``telos.planning``, not ``telos.engine``).
It never infers the expected remainder of a year-in-progress number: fields
it cannot know are written as an explicit ``"0"`` with a ``# TODO
expectations`` comment, never silently omitted, and fields it partially knows
(realized-to-date capital gains, YTD dividends/interest) are written at their
known value with a comment flagging that the full-year expectation still
needs the human's remainder.

W-2 wages/withholding-to-date: deliberately NOT sourced here (manual entry is
fine for year 1, per telos-ops#19) — the feeder emits a single placeholder
W-2 entry, all zeros, flagged ``# TODO expectations``, rather than omitting
the section (a silently-missing W-2 looks like "no wage income", which is
worse than an explicit placeholder).

I/O lives at the CLI edge (``python -m telos.planning.feeder``), matching
``telos.planning.__main__``: this module's functions take/return in-memory
data only. The scenario YAML this module renders is meant for
``TELOS_WORK_DIR`` — NEVER ``TELOS_SOURCE_DIR`` (read-only by contract, plan
§5.5); this module has no opinion on paths, the CLI resolves the destination.
"""

from __future__ import annotations

import argparse
import os
import sys
from datetime import date
from decimal import Decimal
from pathlib import Path

import yaml
from pydantic import BaseModel, ConfigDict, Field, field_validator

from telos.contracts import RealizedLots, Term
from telos.models import FilingStatus, Form1099Div, Form1099Int
from telos.planning.scenario import PlanningScenario

_ZERO = Decimal(0)


def _validate_iso_date(value: str, field_name: str) -> str:
    try:
        date.fromisoformat(value)
    except ValueError as exc:
        raise ValueError(f"{field_name} must be an ISO date (YYYY-MM-DD): {value!r}") from exc
    return value


class MetronActualsExport(BaseModel):
    """The feeder's input: realized-to-date brokerage actuals for one tax year.

    ``realized_lots`` is the existing ``RealizedLots`` contract (produced by
    Metron's lot export or a broker extraction — same shape the Form 8949
    module consumes). ``forms_1099_int_ytd``/``forms_1099_div_ytd`` reuse the
    existing per-payer document models at YTD scope (not full-year — the
    feeder does not relabel or rescale them). Everything here is realized/
    received *to date*, never a full-year expectation.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    tax_year: int
    as_of: str = Field(description="ISO date the export reflects — no clock, ever")
    filing_status: FilingStatus
    prior_year_agi: Decimal = Field(ge=0)
    prior_year_tax: Decimal = Field(ge=0)
    prior_year_return_covered_12_months: bool = True
    realized_lots: RealizedLots = Field(default_factory=RealizedLots)
    forms_1099_int_ytd: tuple[Form1099Int, ...] = ()
    forms_1099_div_ytd: tuple[Form1099Div, ...] = ()

    @field_validator("as_of")
    @classmethod
    def _as_of_iso(cls, v: str) -> str:
        return _validate_iso_date(v, "as_of")


def net_realized_gains(lots: RealizedLots) -> tuple[Decimal, Decimal]:
    """Sum each lot's ``gain`` (8949 column (h), wash-sale already folded in)
    by term. Pure aggregation over the exact property the Form 8949 module
    traces — there is no second netting rule here to drift from it."""
    st = _ZERO
    lt = _ZERO
    for lot in lots.lots:
        if lot.term is Term.SHORT:
            st += lot.gain
        else:
            lt += lot.gain
    return st, lt


def _yaml_str(value: Decimal) -> str:
    """Money as a quoted YAML string — the convention every scenario field
    uses so amounts enter the engine as exact ``Decimal``s, never floats."""
    return f'"{value}"'


def build_actuals_scenario_yaml(export: MetronActualsExport) -> str:
    """Render a ``PlanningScenario`` YAML pre-filled with realized-to-date
    actuals, human-editable TODOs for everything the feeder cannot know.

    Self-validating: the rendered text is parsed back through
    ``PlanningScenario`` before being returned, so this function can never
    hand back YAML that ``python -m telos.planning`` would reject — a bug
    here fails loud in the feeder, not silently downstream.
    """
    st_to_date, lt_to_date = net_realized_gains(export.realized_lots)

    lines: list[str] = [
        'schema_version: "1.0.0"',
        f"tax_year: {export.tax_year}",
        f'as_of: "{export.as_of}"',
        f"filing_status: {export.filing_status.value}",
        "",
        "# W-2 wages/withholding-to-date: NOT sourced by the feeder (manual entry",
        "# is fine for year 1, telos-ops#19) — replace this placeholder with the",
        "# actual employer/wages/withholding, then add the expected full-year",
        "# remainder on top of whatever's been paid to date.",
        "w2s:",
        '  - employer: "TODO"  # TODO expectations',
        '    wages: "0"  # TODO expectations — wages to date + expected full-year remainder',
        '    federal_income_tax_withheld: "0"  # TODO expectations',
        "",
        "# Realized capital gains, netted by term from the Metron realized-lots",
        f"# export as of {export.as_of} (Form 8949 gain: proceeds - cost_basis +",
        "# wash_sale_disallowed). These are REALIZED-TO-DATE, not full-year: the",
        "# value below still needs the expected remainder added on top (this",
        "# field is the FULL-YEAR expected net, per",
        "# PlanningScenario.st_net_gain/lt_net_gain).",
        f"st_net_gain: {_yaml_str(st_to_date)}"
        f"  # realized-to-date {st_to_date}; # TODO expectations — add expected ST remainder",
        f"lt_net_gain: {_yaml_str(lt_to_date)}"
        f"  # realized-to-date {lt_to_date}; # TODO expectations — add expected LT remainder",
    ]

    if export.forms_1099_div_ytd:
        lines.append("")
        lines.append(
            "# Dividends YTD from the same brokerage data — full-year expected"
        )
        lines.append(
            "# remainder still needs adding; # TODO expectations."
        )
        lines.append("forms_1099_div:")
        for div in export.forms_1099_div_ytd:
            lines.append(f'  - payer: "{div.payer}"')
            lines.append(
                f'    ordinary_dividends: {_yaml_str(div.ordinary_dividends)}'
                "  # YTD actual; # TODO expectations — add expected remainder"
            )
            lines.append(
                f'    qualified_dividends: {_yaml_str(div.qualified_dividends)}'
                "  # YTD actual; # TODO expectations — add expected remainder"
            )
            if div.federal_income_tax_withheld:
                lines.append(
                    "    federal_income_tax_withheld: "
                    f"{_yaml_str(div.federal_income_tax_withheld)}"
                )

    if export.forms_1099_int_ytd:
        lines.append("")
        lines.append(
            "# Interest YTD from the same brokerage data — full-year expected"
        )
        lines.append(
            "# remainder still needs adding; # TODO expectations."
        )
        lines.append("forms_1099_int:")
        for interest in export.forms_1099_int_ytd:
            lines.append(f'  - payer: "{interest.payer}"')
            lines.append(
                f'    interest_income: {_yaml_str(interest.interest_income)}'
                "  # YTD actual; # TODO expectations — add expected remainder"
            )
            if interest.federal_income_tax_withheld:
                lines.append(
                    "    federal_income_tax_withheld: "
                    f"{_yaml_str(interest.federal_income_tax_withheld)}"
                )

    lines += [
        "",
        f'prior_year_agi: {_yaml_str(export.prior_year_agi)}',
        f'prior_year_tax: {_yaml_str(export.prior_year_tax)}',
        f"prior_year_return_covered_12_months: "
        f"{str(export.prior_year_return_covered_12_months).lower()}",
    ]

    rendered = "\n".join(lines) + "\n"

    # Fail loud here, not downstream: the feeder must never hand back YAML
    # `python -m telos.planning` would reject.
    PlanningScenario.model_validate(yaml.safe_load(rendered))
    return rendered


WORK_DIR_ENV = "TELOS_WORK_DIR"


def _default_out_path(tax_year: int) -> Path | None:
    work_dir = os.environ.get(WORK_DIR_ENV)
    if not work_dir:
        return None
    return Path(work_dir) / "planning" / f"scenario_ty{tax_year}.yaml"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m telos.planning.feeder",
        description="Build the actuals-to-date half of a PlanningScenario from a "
        "Metron realized-lots export + YTD dividends/interest — leaving the "
        "expectations half for the human to fill in.",
    )
    parser.add_argument(
        "export", type=Path, help="actuals export YAML/JSON (see MetronActualsExport)"
    )
    parser.add_argument(
        "--out",
        type=Path,
        default=None,
        help="scenario YAML destination (default: "
        "$TELOS_WORK_DIR/planning/scenario_ty{year}.yaml; neither set -> stdout only)",
    )
    args = parser.parse_args(argv)

    export = MetronActualsExport.model_validate(yaml.safe_load(args.export.read_text()))
    scenario_yaml = build_actuals_scenario_yaml(export)

    out_path = args.out if args.out is not None else _default_out_path(export.tax_year)
    if out_path is not None:
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(scenario_yaml)
        print(f"scenario written: {out_path}", file=sys.stderr)
    else:
        print(scenario_yaml)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = [
    "MetronActualsExport",
    "build_actuals_scenario_yaml",
    "net_realized_gains",
]
