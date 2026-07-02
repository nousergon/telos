"""The replay harness: reproduce a known-correct filed return to the dollar.

Fixture resolution (personal data NEVER in any repo — plan §5.5):
1. ``$TELOS_REPLAY_FIXTURE`` — explicit path;
2. ``$TELOS_SOURCE_DIR/telos/ty{year}_replay.json`` — alongside the source
   documents (the Drive mount; READ-ONLY by contract);
3. ``$TELOS_WORK_DIR/fixtures/ty{year}_replay.json`` — the local work dir.

Absent everywhere -> the personal test auto-skips and CI stays green on the
committed SYNTHETIC fixture only.

The fixture carries typed inputs (the same pydantic models the engine uses)
plus a ``golden`` mapping of named values transcribed from the filed return.
``run_replay`` computes the full federal return (and Ohio when present) and
diffs EVERY golden — an unknown golden name is a hard error, never ignored.
"""

from __future__ import annotations

import builtins
import json
import os
from collections.abc import Callable
from contextlib import contextmanager
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field

from telos.engine import OhioNonresidentInputs, OhioResult, ohio_nonresident
from telos.engine.guard import CoverageError
from telos.orchestrate import FederalReturn, FullReturnInputs, compute_federal_return
from telos.params import ParamPack

SOURCE_DIR_ENV = "TELOS_SOURCE_DIR"
WORK_DIR_ENV = "TELOS_WORK_DIR"
FIXTURE_ENV = "TELOS_REPLAY_FIXTURE"


class ReplayFixture(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    federal: FullReturnInputs
    ohio: Optional[OhioNonresidentInputs] = None  # noqa: UP045 — pydantic-friendly
    golden: dict[str, Decimal] = Field(min_length=1)


def fixture_path(year: int) -> Optional[Path]:  # noqa: UP045
    explicit = os.environ.get(FIXTURE_ENV)
    if explicit:
        return Path(explicit)
    for env, sub in ((SOURCE_DIR_ENV, f"telos/ty{year}_replay.json"),
                     (WORK_DIR_ENV, f"fixtures/ty{year}_replay.json")):
        root = os.environ.get(env)
        if root and (candidate := Path(root) / sub).exists():
            return candidate
    return None


def load_fixture(path: Path) -> ReplayFixture:
    return ReplayFixture.model_validate(json.loads(path.read_text()))


@dataclass(frozen=True)
class ReplayRow:
    name: str
    expected: Decimal
    computed: Decimal

    @property
    def match(self) -> bool:
        return self.expected == self.computed


@dataclass(frozen=True)
class ReplayReport:
    rows: tuple[ReplayRow, ...]

    @property
    def mismatches(self) -> tuple[ReplayRow, ...]:
        return tuple(r for r in self.rows if not r.match)

    @property
    def is_clean(self) -> bool:
        return not self.mismatches

    def render(self) -> str:
        lines = []
        for r in self.rows:
            mark = "OK " if r.match else "DIFF"
            delta = "" if r.match else f"  (delta {r.computed - r.expected})"
            lines.append(f"{mark}  {r.name}: expected {r.expected} computed {r.computed}{delta}")
        return "\n".join(lines)


def _golden_getters(
    fed: FederalReturn, oh: Optional[OhioResult]  # noqa: UP045
) -> dict[str, Callable[[], Decimal]]:
    g: dict[str, Callable[[], Decimal]] = {
        "agi": lambda: fed.result.lines["11"].value,
        "deduction": lambda: fed.result.lines["12"].value,
        "qbi_deduction": lambda: fed.result.lines["13"].value,
        "taxable_income": lambda: fed.result.lines["15"].value,
        "line16_tax": lambda: fed.result.lines["16"].value,
        "total_tax": lambda: fed.result.total_tax.value,
        "withholding": lambda: fed.result.lines["25"].value,
        "total_payments": lambda: fed.result.total_payments.value,
        "balance_due": lambda: fed.result.balance_due.value,
        "niit": lambda: fed.f8960.niit.value,
    }
    if fed.schedule_d is not None:
        schd = fed.schedule_d
        g["schedule_d_line16"] = lambda: schd.lines["16"].value
        g["capital_gain_line7"] = lambda: schd.line7a.value
    if fed.f8959 is not None:
        f59 = fed.f8959
        g["additional_medicare"] = lambda: f59.additional_medicare_tax.value
        g["additional_medicare_withholding"] = lambda: f59.additional_withholding.value
    if fed.schedule_a is not None:
        scha = fed.schedule_a
        g["itemized_total"] = lambda: scha.total_itemized.value
        g["salt_5e"] = lambda: scha.lines["5e"].value
    if fed.schedule_e is not None:
        sche = fed.schedule_e
        g["schedule_e_total"] = lambda: sche.total.value
    if oh is not None:
        g["ohio_net_tax"] = lambda: oh.net_tax.value
        g["ohio_tax_before_credits"] = lambda: oh.lines["8c"].value
        g["ohio_nrc"] = lambda: oh.lines["nrc"].value
    return g


def run_replay(
    fixture: ReplayFixture, pack: ParamPack,
    ohio_pack: Optional[ParamPack] = None,  # noqa: UP045
) -> ReplayReport:
    fed = compute_federal_return(fixture.federal, pack)
    oh: Optional[OhioResult] = None  # noqa: UP045
    if fixture.ohio is not None:
        if ohio_pack is None:
            raise CoverageError("fixture carries an Ohio return but no Ohio pack was provided")
        oh = ohio_nonresident(fixture.ohio, ohio_pack)

    getters = _golden_getters(fed, oh)
    unknown = set(fixture.golden) - set(getters)
    if unknown:
        raise CoverageError(
            f"unknown golden name(s) {sorted(unknown)} — the harness refuses to "
            f"silently skip a golden; known names: {sorted(getters)}"
        )
    rows = tuple(
        ReplayRow(name=name, expected=expected, computed=getters[name]())
        for name, expected in sorted(fixture.golden.items())
    )
    return ReplayReport(rows=rows)


@contextmanager
def source_write_guard():
    """Enforce the read-only-source contract: any write-mode ``open`` under
    ``$TELOS_SOURCE_DIR`` raises. Armed by the replay tests."""
    root = os.environ.get(SOURCE_DIR_ENV)
    if not root:
        yield
        return
    root_path = Path(root).resolve()
    real_open = builtins.open

    def guarded(file, mode="r", *args, **kwargs):
        if any(flag in str(mode) for flag in ("w", "a", "x", "+")):
            try:
                p = Path(file).resolve()
            except (TypeError, OSError):
                p = None
            if p is not None and p.is_relative_to(root_path):
                raise PermissionError(
                    f"telos write-guard: refusing write-mode open ({mode!r}) under "
                    f"TELOS_SOURCE_DIR: {p}"
                )
        return real_open(file, mode, *args, **kwargs)

    builtins.open = guarded
    try:
        yield
    finally:
        builtins.open = real_open
