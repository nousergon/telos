"""Metron-vs-broker lot reconciliation (plan §7.3): surface, never average.

Two ``RealizedLots`` sets — Metron's export and the broker-1099 extraction —
are matched per-lot on (normalized description, date acquired, date sold).
Every discrepancy is itemized: field-level mismatches on matched lots, and
lots present on only one side. Each is either a Metron bug (file it on
metron), a broker basis quirk (document it), or an extraction error (fix it)
— never something to smooth over.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal

from telos.contracts import RealizedLot, RealizedLots

_COMPARED_FIELDS = ("proceeds", "cost_basis", "wash_sale_disallowed")


def _key(lot: RealizedLot) -> tuple[str, str, str]:
    return (lot.description.strip().upper(), lot.date_acquired, lot.date_sold)


@dataclass(frozen=True)
class FieldMismatch:
    key: tuple[str, str, str]
    field_name: str
    metron_value: Decimal
    broker_value: Decimal

    def __str__(self) -> str:
        desc, acq, sold = self.key
        return (
            f"{desc} ({acq} -> {sold}): {self.field_name} metron={self.metron_value} "
            f"broker={self.broker_value} (delta {self.metron_value - self.broker_value})"
        )


@dataclass(frozen=True)
class LotReconciliation:
    matched_clean: int
    mismatches: tuple[FieldMismatch, ...] = field(default_factory=tuple)
    only_in_metron: tuple[tuple[str, str, str], ...] = field(default_factory=tuple)
    only_in_broker: tuple[tuple[str, str, str], ...] = field(default_factory=tuple)

    @property
    def is_clean(self) -> bool:
        return not (self.mismatches or self.only_in_metron or self.only_in_broker)

    def report(self) -> str:
        lines = [f"matched clean: {self.matched_clean}"]
        lines += [f"MISMATCH  {m}" for m in self.mismatches]
        lines += [f"METRON-ONLY  {d} ({a} -> {s})" for d, a, s in self.only_in_metron]
        lines += [f"BROKER-ONLY  {d} ({a} -> {s})" for d, a, s in self.only_in_broker]
        return "\n".join(lines)


def reconcile_lots(metron: RealizedLots, broker: RealizedLots) -> LotReconciliation:
    m_by_key = {_key(lot): lot for lot in metron.lots}
    b_by_key = {_key(lot): lot for lot in broker.lots}
    if len(m_by_key) != len(metron.lots) or len(b_by_key) != len(broker.lots):
        raise ValueError(
            "duplicate lot keys within one side — reconciliation requires unique "
            "(description, acquired, sold) per side; split or disambiguate the export"
        )

    mismatches: list[FieldMismatch] = []
    clean = 0
    for key in sorted(m_by_key.keys() & b_by_key.keys()):
        m_lot, b_lot = m_by_key[key], b_by_key[key]
        lot_mismatches = [
            FieldMismatch(key, f, getattr(m_lot, f), getattr(b_lot, f))
            for f in _COMPARED_FIELDS
            if getattr(m_lot, f) != getattr(b_lot, f)
        ]
        if lot_mismatches:
            mismatches.extend(lot_mismatches)
        else:
            clean += 1

    return LotReconciliation(
        matched_clean=clean,
        mismatches=tuple(mismatches),
        only_in_metron=tuple(sorted(m_by_key.keys() - b_by_key.keys())),
        only_in_broker=tuple(sorted(b_by_key.keys() - m_by_key.keys())),
    )
