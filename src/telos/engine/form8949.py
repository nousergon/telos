"""Form 8949 — per-box totals from realized lots, plus the wash-risk guard.

Grouping per the 2025 form: Part I (short) and Part II (long), one totals row
per checked box. Column (g) carries the broker-reported wash-sale
disallowance (code W) as a positive adjustment; column (h) = (d) - (e) + (g).

Wash-sale amounts are consumed as broker-reported, never recomputed (M1
scope). The guard closes the obvious hole that leaves: a LOSS lot with no
reported disallowance, where another provided lot shows the same description
acquired within 30 days after the sale, suggests an unreported wash sale
(likely cross-account or cross-broker, which brokers don't see) — that fails
loud for manual review instead of silently deducting a disallowed loss.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal

from telos.contracts import Form8949Box, RealizedLot, RealizedLots, Term
from telos.engine.guard import CoverageError
from telos.engine.trace import Traced, traced_sum

FORM_CITE = "2025 Form 8949"
_ZERO = Decimal(0)
_WASH_WINDOW_DAYS = 30


class WashSaleRiskError(CoverageError):
    """A loss lot looks wash-sale-adjacent with no broker adjustment — review."""


@dataclass(frozen=True)
class BoxTotals:
    box: Form8949Box
    term: Term
    proceeds: Traced
    cost_basis: Traced
    adjustments: Traced
    gain: Traced


def _parse(d: str) -> date | None:
    try:
        return date.fromisoformat(d)
    except ValueError:
        return None  # "VARIOUS" etc.


def check_wash_risk(lots: Iterable[RealizedLot]) -> None:
    """Fail loud on unreported-wash-sale patterns across the provided lots."""
    lots = list(lots)
    acquisitions = [
        (lot.description.strip().upper(), _parse(lot.date_acquired))
        for lot in lots
        if _parse(lot.date_acquired) is not None
    ]
    for lot in lots:
        if lot.gain >= 0 or lot.wash_sale_disallowed > 0:
            continue
        sold = _parse(lot.date_sold)
        if sold is None:
            continue
        name = lot.description.strip().upper()
        for other_name, acquired in acquisitions:
            if other_name == name and sold < acquired <= sold + timedelta(
                days=_WASH_WINDOW_DAYS
            ):
                raise WashSaleRiskError(
                    f"loss lot {lot.description!r} sold {lot.date_sold} with no "
                    f"broker wash-sale adjustment, but the same security was "
                    f"acquired {acquired.isoformat()} (within {_WASH_WINDOW_DAYS} "
                    f"days). Possible unreported (cross-account) wash sale — "
                    f"resolve manually; the engine does not recompute wash sales."
                )


def form8949_totals(realized: RealizedLots) -> list[BoxTotals]:
    """One totals row per (box), Schedule D-ready, provenance per lot."""
    check_wash_risk(realized.lots)
    groups: dict[Form8949Box, list[RealizedLot]] = {}
    for lot in realized.lots:
        groups.setdefault(lot.box, []).append(lot)

    rows: list[BoxTotals] = []
    for box in sorted(groups, key=lambda b: b.value):
        lots = groups[box]
        term = lots[0].term
        label = f"8949:box{box.value}"

        def lot_traced(lot: RealizedLot, field: str, value: Decimal) -> Traced:
            return Traced(
                label=f"lot:{lot.description}@{lot.date_sold}.{field}",
                value=value,
                sources=(lot.source,),
            )

        proceeds = traced_sum(
            f"{label}.proceeds(d)",
            [lot_traced(lot, "proceeds", lot.proceeds) for lot in lots],
            sources=(f"{FORM_CITE}, column (d)",),
        )
        basis = traced_sum(
            f"{label}.basis(e)",
            [lot_traced(lot, "basis", lot.cost_basis) for lot in lots],
            sources=(f"{FORM_CITE}, column (e)",),
        )
        adjustments = traced_sum(
            f"{label}.adjustments(g)",
            [
                lot_traced(lot, "washW", lot.wash_sale_disallowed)
                for lot in lots
                if lot.wash_sale_disallowed > 0
            ],
            sources=(f"{FORM_CITE}, column (g), code W (broker-reported)",),
        )
        gain = Traced(
            label=f"{label}.gain(h)",
            value=proceeds.value - basis.value + adjustments.value,
            sources=(f"{FORM_CITE}, column (h) = (d) - (e) + (g)",),
            inputs=(proceeds, basis, adjustments),
        )
        rows.append(BoxTotals(box=box, term=term, proceeds=proceeds,
                              cost_basis=basis, adjustments=adjustments, gain=gain))
    return rows
