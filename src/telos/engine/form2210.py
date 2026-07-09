"""Form 2210 Part III — the §6654 underpayment penalty (interest) computation.

The penalty is interest on each installment's underpayment for the days it
stays unpaid, at the §6621 quarterly federal underpayment rate in force during
each rate period:

    penalty = underpayment * (days outstanding in period / 365) * §6621 rate

summed over the rate periods an underpayment spans (Form 2210 Part III + the
Penalty Worksheet in the 2025 Instructions for Form 2210). Interest runs from
each installment due date to the earlier of the date paid or the return due
date (Apr 15 following the tax year).

Determinism: pure ``datetime.date`` arithmetic — no clock is read; every date
is caller-supplied. The §6621 rates are injected as a ``ParamPack`` (the
``params/federal_underpayment_rates.yaml`` rates file), so every rate rides the
audit trail with its Revenue-Ruling citation, exactly like every other engine
constant. Nothing here reaches the network or an LLM.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from telos.engine.rounding import round_whole_dollar, to_decimal
from telos.engine.trace import Traced, traced_sum
from telos.params import ParamPack

FORM_CITE = "2025 Instructions for Form 2210, Part III + Penalty Worksheet"
_ZERO = Decimal(0)
_DAYS_IN_YEAR = Decimal(365)  # Form 2210 penalty worksheet divides by 365


class RateNotAvailableError(KeyError):
    """No §6621 rate is on file for a calendar quarter the penalty period spans."""


def _quarter_key(d: date) -> str:
    return f"{d.year}Q{(d.month - 1) // 3 + 1}"


def _quarter_bounds(year: int, quarter: int) -> tuple[date, date]:
    """[start, end_exclusive) for a calendar quarter."""
    start_month = (quarter - 1) * 3 + 1
    start = date(year, start_month, 1)
    end = date(year + 1, 1, 1) if quarter == 4 else date(year, start_month + 3, 1)
    return start, end


def _resolve_rate(pack: ParamPack, d: date, return_due_date: date) -> Traced:
    """The §6621 underpayment rate governing day ``d``.

    The §6654 special rule (IRC §6621(b)(2)(B)) freezes the rate for the first
    15 days of the 4th month following the tax year to the prior quarter's
    rate; the rates file carries that frozen value under the ``<Q2>-6654`` key.
    Any day at or after the tax-year-Q1 due-date window that falls in the
    filing-month quarter uses it.
    """
    key = _quarter_key(d)
    # The return due date (Apr 15 following the tax year) sits in Q2 of the
    # following year, but §6654 uses the frozen Q1 rate through it.
    if d.year == return_due_date.year and d.month in (4, 5, 6) and d <= return_due_date:
        special = f"{d.year}Q2-6654"
        try:
            return pack.get(f"underpayment_rate.{special}")
        except KeyError:
            pass
    try:
        return pack.get(f"underpayment_rate.{key}")
    except KeyError as exc:
        raise RateNotAvailableError(
            f"no §6621 underpayment rate on file for {key} — the rates pack "
            f"(params/federal_underpayment_rates.yaml) must cover every quarter "
            f"the penalty period touches"
        ) from exc


@dataclass(frozen=True)
class InstallmentUnderpayment:
    """One §6654(c)(2) installment as an underpayment to be penalized."""

    quarter: int  # 1-4
    due_date: date  # statutory installment due date (or business-day-shifted, caller's choice)
    underpayment: Decimal  # required installment less payments credited, floored at 0
    paid_date: date | None  # when the underpayment was cured; None = still unpaid at return due


@dataclass(frozen=True)
class InstallmentPenalty:
    quarter: int
    underpayment: Traced
    penalty: Traced  # summed interest across the rate periods this installment spanned
    segments: tuple[Traced, ...]  # one Traced per (rate-period) segment, for the audit trail


@dataclass(frozen=True)
class Form2210Result:
    installment_penalties: tuple[InstallmentPenalty, ...]
    total_penalty: Traced  # Form 2210 line 19

    def explain(self) -> str:
        return self.total_penalty.explain()


def _segment_penalty(
    *,
    quarter: int,
    underpayment: Traced,
    seg_start: date,
    seg_end: date,
    rate: Traced,
) -> Traced:
    """Interest for one rate-period segment: underpayment * days/365 * rate.

    ``seg_end`` is EXCLUSIVE; days = (seg_end - seg_start). Zero-length segments
    contribute nothing (return a 0 Traced so the tree still records the period).
    """
    days = (seg_end - seg_start).days
    days_dec = to_decimal(days)
    value = underpayment.value * (days_dec / _DAYS_IN_YEAR) * rate.value
    return Traced(
        label=f"2210:penalty_q{quarter}_{seg_start.isoformat()}",
        value=value,
        sources=(
            f"{FORM_CITE}: underpayment * {days} days / 365 * §6621 rate "
            f"({seg_start.isoformat()}-{seg_end.isoformat()} excl.)",
        ),
        inputs=(underpayment, rate),
    )


def compute_installment_penalty(
    item: InstallmentUnderpayment,
    pack: ParamPack,
    *,
    return_due_date: date,
) -> InstallmentPenalty:
    """Penalty for a single installment underpayment, split across rate periods.

    Interest accrues from ``item.due_date`` to the earlier of ``item.paid_date``
    and ``return_due_date``, split at calendar-quarter boundaries so each slice
    uses its own §6621 rate.
    """
    underpayment = Traced(
        label=f"2210:underpayment_q{item.quarter}",
        value=max(item.underpayment, _ZERO),
        sources=(f"{FORM_CITE}, Part III line 1a (required installment less payments, floor 0)",),
    )
    end = return_due_date if item.paid_date is None else min(item.paid_date, return_due_date)
    segments: list[Traced] = []
    if underpayment.value > _ZERO and end > item.due_date:
        cursor = item.due_date
        while cursor < end:
            rate = _resolve_rate(pack, cursor, return_due_date)
            q_year, q_num = cursor.year, (cursor.month - 1) // 3 + 1
            _, q_end = _quarter_bounds(q_year, q_num)
            seg_end = min(q_end, end)
            segments.append(
                _segment_penalty(
                    quarter=item.quarter,
                    underpayment=underpayment,
                    seg_start=cursor,
                    seg_end=seg_end,
                    rate=rate,
                )
            )
            cursor = seg_end
    penalty = traced_sum(
        f"2210:penalty_q{item.quarter}",
        segments,
        sources=(f"{FORM_CITE}, Part III line {item.quarter} (installment penalty)",),
    )
    # Rounding is a form-level concern; Form 2210 rounds the *total* (line 19).
    return InstallmentPenalty(
        quarter=item.quarter,
        underpayment=underpayment,
        penalty=penalty,
        segments=tuple(segments),
    )


def compute_form2210_penalty(
    installments: Sequence[InstallmentUnderpayment],
    pack: ParamPack,
    *,
    return_due_date: date,
) -> Form2210Result:
    """Form 2210 Part III total underpayment penalty (line 19).

    Sum the per-installment penalties, each itself summed across the rate
    periods its underpayment spans, then round the total to whole dollars per
    the Form 2210 instruction to enter a whole-dollar penalty.
    """
    penalties = tuple(
        compute_installment_penalty(item, pack, return_due_date=return_due_date)
        for item in installments
    )
    total = traced_sum(
        "2210:total_penalty",
        [p.penalty for p in penalties],
        sources=(f"{FORM_CITE}, line 19 (total penalty, sum of installment penalties)",),
    )
    total_rounded = total.derive(
        "2210:total_penalty_rounded",
        round_whole_dollar(total.value),
        sources=(f"{FORM_CITE}, line 19 rounded to whole dollars",),
    )
    return Form2210Result(installment_penalties=penalties, total_penalty=total_rounded)
