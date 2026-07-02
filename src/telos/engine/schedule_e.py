"""Schedule E consumption — place the worksheet contract, never recompute it.

The regime math (§280A caps, §469/8582 passive limitation, §183) is the
PRODUCER's job — ktema's allocation engine, or the manual path transcribing a
filed return. This module validates the contract, totals the arrangements
onto Schedule 1 (Form 1040 line 8's seam), preserves every contested flag in
the audit trail, and surfaces the two facts downstream modules need:

- ``total_for_8960_line4a`` — rental net income is investment income for the
  NIIT module (Form 8960 line 4a);
- ``qbi_total`` — the 8995-A module's input, only when EVERY arrangement's
  producer determined QBI eligibility (a None anywhere fails loud rather
  than silently dropping a component);
- ``form_8582_expected`` — a §469 arrangement with a suspended loss means the
  filed return should carry Form 8582; the replay harness checks presence.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from telos.contracts import LossRegime, ScheduleEWorksheet
from telos.engine.guard import CoverageError
from telos.engine.trace import Traced, traced_sum

_ZERO = Decimal(0)


@dataclass(frozen=True)
class ScheduleEResult:
    total: Traced  # -> Schedule 1 (Form 1040 line 8 seam)
    total_for_8960_line4a: Traced
    qbi_total: Traced | None  # None => producer left QBI undetermined somewhere
    form_8582_expected: bool
    cpa_confirm_items: tuple[str, ...]


def schedule_e(worksheet: ScheduleEWorksheet, *, expected_tax_year: int) -> ScheduleEResult:
    if worksheet.tax_year != expected_tax_year:
        raise CoverageError(
            f"Schedule E worksheet is for TY{worksheet.tax_year}, "
            f"return is TY{expected_tax_year} — refusing to mix years"
        )
    if not worksheet.arrangements:
        raise CoverageError(
            "Schedule E worksheet has no arrangements — if there is genuinely no "
            "rental activity, omit the worksheet instead of passing an empty one"
        )

    per_arrangement = [
        Traced(
            label=f"schE:{a.arrangement_id} ({a.property_name}, {a.regime.value})",
            value=a.net_income_post_caps,
            sources=(
                f"Schedule E worksheet contract v{worksheet.schema_version} "
                f"[{a.source}] — post-{a.regime.value} cap",
                *(f"CPA-CONFIRM: {flag}" for flag in a.contested_flags),
            ),
        )
        for a in worksheet.arrangements
    ]
    total = traced_sum("schE:total to Schedule 1", per_arrangement)

    qbi_total: Traced | None
    if any(a.qbi_eligible_income is None for a in worksheet.arrangements):
        qbi_total = None
    else:
        qbi_total = traced_sum(
            "schE:QBI component (8995-A input)",
            [
                Traced(
                    label=f"schE:{a.arrangement_id}.qbi",
                    value=a.qbi_eligible_income,  # type: ignore[arg-type]
                    sources=(f"producer-determined QBI [{a.source}]",),
                )
                for a in worksheet.arrangements
            ],
        )

    form_8582_expected = any(
        a.regime is LossRegime.SECTION_469_PASSIVE and a.suspended_loss_carryforward > 0
        for a in worksheet.arrangements
    )
    cpa_items = tuple(
        f"{a.arrangement_id}: {flag}"
        for a in worksheet.arrangements
        for flag in a.contested_flags
    )
    return ScheduleEResult(
        total=total,
        total_for_8960_line4a=total.derive("8960:line4a rental input", total.value),
        qbi_total=qbi_total,
        form_8582_expected=form_8582_expected,
        cpa_confirm_items=cpa_items,
    )


def require_qbi_total(result: ScheduleEResult) -> Traced:
    """The 8995-A module's accessor: fails loud on undetermined QBI."""
    if result.qbi_total is None:
        raise CoverageError(
            "QBI eligibility undetermined for at least one rental arrangement — "
            "the producer (ktema or manual entry) must set qbi_eligible_income on "
            "every arrangement before the 8995-A module can run. Refusing to "
            "silently drop a QBI component."
        )
    return result.qbi_total
