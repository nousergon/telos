"""Parameter packs: tax-year constants as cited data, never code.

Every bracket, threshold, and deduction amount lives in a per-tax-year YAML
pack. Two rules are enforced structurally, not by convention:

1. **Every leaf value carries a ``source`` citation** (Revenue Procedure /
   form-instruction reference). A pack with an uncited value does not load.
2. **A pack declares its ``status``** — ``example`` (synthetic, for tests),
   ``provisional`` (real values, pre-final-forms), or ``final``. A ``final``
   pack refuses to load if any citation still carries an unverified marker
   (``SYNTHETIC``, ``UNVERIFIED``, ``TODO``, ``FIXME``).

Values come out of a pack as ``Traced`` (``telos.engine.trace``), so the
citation rides the audit trail all the way to the output line.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, ConfigDict, field_validator

# NOTE: engine imports happen at CALL time, not import time — telos.params is
# imported by engine modules (amt_guard, form1040, ...), and importing any
# telos.engine submodule executes the engine package __init__, which would
# close a circular import back into this module during interpreter startup.
if False:  # pragma: no cover — typing aid only
    from telos.engine.brackets import Bracket
    from telos.engine.trace import Traced

_UNVERIFIED_MARKERS = ("SYNTHETIC", "UNVERIFIED", "TODO", "FIXME")


class ParamPackError(ValueError):
    """The pack violates the params contract (uncited value, bad shape, ...)."""


def _is_scalar_leaf(node: Any) -> bool:
    return isinstance(node, dict) and "value" in node


def _is_bracket_leaf(node: Any) -> bool:
    return isinstance(node, list) and bool(node) and all(isinstance(row, dict) for row in node)


def _walk_validate(node: Any, path: str) -> None:
    """Enforce leaf shape + citation on every leaf, recursively."""
    if _is_scalar_leaf(node):
        extra = set(node) - {"value", "source"}
        if extra:
            raise ParamPackError(f"{path}: unexpected keys {sorted(extra)} on scalar leaf")
        if not str(node.get("source") or "").strip():
            raise ParamPackError(f"{path}: leaf value has no source citation")
        return
    if _is_bracket_leaf(node):
        for i, row in enumerate(node):
            extra = set(row) - {"upto", "rate", "source"}
            if extra:
                raise ParamPackError(f"{path}[{i}]: unexpected keys {sorted(extra)} on bracket row")
            if "rate" not in row:
                raise ParamPackError(f"{path}[{i}]: bracket row missing 'rate'")
            if not str(row.get("source") or "").strip():
                raise ParamPackError(f"{path}[{i}]: bracket row has no source citation")
        return
    if isinstance(node, dict):
        if not node:
            raise ParamPackError(f"{path}: empty mapping")
        for key, child in node.items():
            _walk_validate(child, f"{path}.{key}")
        return
    raise ParamPackError(
        f"{path}: unsupported node shape {type(node).__name__} — leaves must be "
        f"{{value, source}} mappings or lists of bracket rows"
    )


def _collect_sources(node: Any) -> list[str]:
    if _is_scalar_leaf(node):
        return [node["source"]]
    if _is_bracket_leaf(node):
        return [row["source"] for row in node]
    if isinstance(node, dict):
        return [s for child in node.values() for s in _collect_sources(child)]
    return []


class ParamPack(BaseModel):
    """A validated tax-year parameter pack."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    tax_year: int
    status: Literal["example", "provisional", "final"]
    values: dict[str, Any]

    @field_validator("values")
    @classmethod
    def _validate_values(cls, values: dict[str, Any]) -> dict[str, Any]:
        if not values:
            raise ParamPackError("pack has no values")
        _walk_validate(values, "values")
        return values

    def model_post_init(self, __context: Any) -> None:
        if self.status == "final":
            for src in _collect_sources(self.values):
                for marker in _UNVERIFIED_MARKERS:
                    if marker in src:
                        raise ParamPackError(
                            f"status is 'final' but a citation carries the unverified "
                            f"marker {marker!r}: {src!r}"
                        )

    def _resolve(self, path: str) -> Any:
        node: Any = self.values
        for part in path.split("."):
            if not isinstance(node, dict) or part not in node:
                raise KeyError(f"parameter path not found in TY{self.tax_year} pack: {path!r}")
            node = node[part]
        return node

    def get(self, path: str) -> Traced:
        """A scalar parameter as a Traced value — the citation rides along."""
        from telos.engine.rounding import to_decimal
        from telos.engine.trace import Traced

        node = self._resolve(path)
        if not _is_scalar_leaf(node):
            raise ParamPackError(f"{path!r} is not a scalar parameter")
        return Traced(
            label=f"param:ty{self.tax_year}.{path}",
            value=to_decimal(node["value"]),
            sources=(node["source"],),
        )

    def brackets(self, path: str) -> list[Bracket]:
        """A bracket schedule, validated before it is handed to the engine."""
        from telos.engine.brackets import Bracket, validate_brackets
        from telos.engine.rounding import to_decimal

        node = self._resolve(path)
        if not _is_bracket_leaf(node):
            raise ParamPackError(f"{path!r} is not a bracket schedule")
        schedule = [
            Bracket(
                upto=None if row.get("upto") is None else to_decimal(row["upto"]),
                rate=to_decimal(row["rate"]),
            )
            for row in node
        ]
        validate_brackets(schedule)
        return schedule


def load_pack(path: str | Path) -> ParamPack:
    """Load and validate a parameter pack from YAML."""
    raw = yaml.safe_load(Path(path).read_text())
    if not isinstance(raw, dict):
        raise ParamPackError(f"{path}: pack must be a mapping, got {type(raw).__name__}")
    return ParamPack(**raw)
