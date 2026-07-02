"""The audit trail: every computed value knows where it came from.

A ``Traced`` wraps a Decimal with a label, the citations that justify it
(parameter sources, source-document ids, worksheet names), and the upstream
``Traced`` values it was derived from. Rendering the tree answers "why is
line 16 $X?" — the load-bearing feature commercial software omits.

Traced values are immutable. Derivations create new nodes; nothing mutates.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from decimal import Decimal

from telos.engine.rounding import to_decimal


@dataclass(frozen=True)
class Traced:
    """An immutable value with provenance."""

    label: str
    value: Decimal
    sources: tuple[str, ...] = field(default_factory=tuple)
    inputs: tuple[Traced, ...] = field(default_factory=tuple)

    def __post_init__(self) -> None:
        if not self.label:
            raise ValueError("Traced requires a non-empty label")
        object.__setattr__(self, "value", to_decimal(self.value))
        object.__setattr__(self, "sources", tuple(self.sources))
        object.__setattr__(self, "inputs", tuple(self.inputs))

    def derive(
        self,
        label: str,
        value: int | float | str | Decimal,
        *,
        sources: Sequence[str] = (),
    ) -> Traced:
        """A new value computed from this one (e.g. after rounding or a cap)."""
        return Traced(label=label, value=to_decimal(value), sources=tuple(sources), inputs=(self,))

    def all_sources(self) -> tuple[str, ...]:
        """Every citation in the provenance tree, deduplicated, depth-first."""
        seen: dict[str, None] = {}
        for src in self.sources:
            seen.setdefault(src)
        for inp in self.inputs:
            for src in inp.all_sources():
                seen.setdefault(src)
        return tuple(seen)

    def explain(self, indent: int = 0) -> str:
        """Render the provenance tree as indented text."""
        pad = "  " * indent
        cite = f"  [{'; '.join(self.sources)}]" if self.sources else ""
        lines = [f"{pad}{self.label} = {self.value}{cite}"]
        lines.extend(inp.explain(indent + 1) for inp in self.inputs)
        return "\n".join(lines)


def traced_sum(label: str, items: Iterable[Traced], *, sources: Sequence[str] = ()) -> Traced:
    """Sum Traced values into a new Traced whose inputs are the addends."""
    addends = tuple(items)
    total = sum((item.value for item in addends), start=Decimal(0))
    return Traced(label=label, value=total, sources=tuple(sources), inputs=addends)
