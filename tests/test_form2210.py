"""Form 2210 Part III underpayment penalty — §6621 rate periods (telos-ops#20)."""

from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest

from telos.engine.form2210 import (
    InstallmentUnderpayment,
    RateNotAvailableError,
    compute_form2210_penalty,
    compute_installment_penalty,
)
from telos.params import ParamPack, load_pack

D = Decimal
ROOT = Path(__file__).parent.parent
RATES = load_pack(ROOT / "params" / "federal_underpayment_rates.yaml")
RETURN_DUE = date(2026, 4, 15)  # filing due date for TY2025


class TestRatesPack:
    def test_loads_and_is_final(self):
        assert RATES.status == "final"

    def test_all_2025_quarters_and_q1_2026_present_at_7pct(self):
        for key in ("2025Q1", "2025Q2", "2025Q3", "2025Q4", "2026Q1", "2026Q2-6654"):
            assert RATES.get(f"underpayment_rate.{key}").value == D("0.07")

    def test_every_rate_cites_a_revenue_ruling(self):
        for key in ("2025Q1", "2025Q2", "2025Q3", "2025Q4", "2026Q1"):
            src = RATES.get(f"underpayment_rate.{key}").sources[0]
            assert "Rev. Rul." in src and "I.R.B." in src

    def test_special_6654_window_cites_the_freeze_rule(self):
        src = RATES.get("underpayment_rate.2026Q2-6654").sources[0]
        assert "6621(b)(2)(B)" in src


class TestSingleInstallmentPenalty:
    def test_full_year_underpayment_at_flat_7pct(self):
        """A $1,000 Q1 underpayment outstanding the whole 365 days from
        2025-04-15 to 2026-04-15 at a flat 7% = exactly $70."""
        item = InstallmentUnderpayment(
            quarter=1, due_date=date(2025, 4, 15), underpayment=D(1_000), paid_date=None
        )
        r = compute_form2210_penalty([item], RATES, return_due_date=RETURN_DUE)
        assert r.total_penalty.value == D(70)

    def test_days_split_across_rate_periods_sum_to_365(self):
        item = InstallmentUnderpayment(
            quarter=1, due_date=date(2025, 4, 15), underpayment=D(1_000), paid_date=None
        )
        p = compute_installment_penalty(item, RATES, return_due_date=RETURN_DUE)
        # segments cover 2025-04-15 -> 2026-04-15 exclusive = 365 days
        total_days = sum(
            int(s.sources[0].split(" days")[0].split("* ")[-1]) for s in p.segments
        )
        assert total_days == 365

    def test_paid_early_stops_the_clock(self):
        """Paid the very next day -> 1 day of interest, rounds to $0."""
        item = InstallmentUnderpayment(
            quarter=1, due_date=date(2025, 4, 15), underpayment=D(1_000),
            paid_date=date(2025, 4, 16),
        )
        r = compute_form2210_penalty([item], RATES, return_due_date=RETURN_DUE)
        # 1000 * 1/365 * 0.07 = 0.19 -> rounds to 0
        assert r.total_penalty.value == D(0)
        assert r.installment_penalties[0].penalty.value < D(1)

    def test_zero_underpayment_yields_no_penalty_and_no_segments(self):
        item = InstallmentUnderpayment(
            quarter=2, due_date=date(2025, 6, 15), underpayment=D(0), paid_date=None
        )
        p = compute_installment_penalty(item, RATES, return_due_date=RETURN_DUE)
        assert p.penalty.value == D(0)
        assert p.segments == ()

    def test_negative_underpayment_floored_to_zero(self):
        item = InstallmentUnderpayment(
            quarter=1, due_date=date(2025, 4, 15), underpayment=D(-500), paid_date=None
        )
        p = compute_installment_penalty(item, RATES, return_due_date=RETURN_DUE)
        assert p.underpayment.value == D(0)
        assert p.penalty.value == D(0)

    def test_paid_date_after_return_due_is_clamped_to_return_due(self):
        far = InstallmentUnderpayment(
            quarter=1, due_date=date(2025, 4, 15), underpayment=D(1_000),
            paid_date=date(2027, 1, 1),
        )
        never = InstallmentUnderpayment(
            quarter=1, due_date=date(2025, 4, 15), underpayment=D(1_000), paid_date=None
        )
        assert (
            compute_form2210_penalty([far], RATES, return_due_date=RETURN_DUE).total_penalty.value
            == compute_form2210_penalty(
                [never], RATES, return_due_date=RETURN_DUE
            ).total_penalty.value
        )

    def test_april_1_to_15_window_uses_frozen_6654_rate(self):
        """A Q4 underpayment outstanding only across the filing-month window
        (2026-04-01 -> 2026-04-15) must resolve the §6654 frozen rate, not the
        general Q2-2026 rate — proven by its citation in the trace."""
        item = InstallmentUnderpayment(
            quarter=4, due_date=date(2026, 4, 1), underpayment=D(10_000), paid_date=None
        )
        p = compute_installment_penalty(item, RATES, return_due_date=RETURN_DUE)
        assert len(p.segments) == 1
        assert "6621(b)(2)(B)" in p.segments[0].all_sources()[-1]


class TestTotalPenalty:
    def test_four_installments_sum_and_round(self):
        items = [
            InstallmentUnderpayment(
                quarter=q, due_date=date(2025, m, 15) if q < 4 else date(2026, 1, 15),
                underpayment=D(2_000), paid_date=None,
            )
            for q, m in zip((1, 2, 3, 4), (4, 6, 9, 1), strict=False)
        ]
        r = compute_form2210_penalty(items, RATES, return_due_date=RETURN_DUE)
        assert len(r.installment_penalties) == 4
        # total is the whole-dollar rounding of the four segment sums
        raw = sum(p.penalty.value for p in r.installment_penalties)
        assert r.total_penalty.value == raw.quantize(D(1), rounding="ROUND_HALF_UP")

    def test_empty_installments_zero_penalty(self):
        r = compute_form2210_penalty([], RATES, return_due_date=RETURN_DUE)
        assert r.total_penalty.value == D(0)

    def test_explain_renders_provenance_tree(self):
        item = InstallmentUnderpayment(
            quarter=1, due_date=date(2025, 4, 15), underpayment=D(1_000), paid_date=None
        )
        text = compute_form2210_penalty(
            [item], RATES, return_due_date=RETURN_DUE
        ).explain()
        assert "2210:total_penalty" in text
        assert "Rev. Rul." in text


class TestSpecialWindowFallback:
    def test_falls_back_to_general_q2_when_6654_key_absent(self):
        """If a rates pack omits the §6654 frozen-window key, the April 1-15
        window degrades gracefully to the general published Q2 rate rather than
        failing — proven by the trace citing the plain 2026Q2 entry."""
        pack = ParamPack(
            tax_year=0,
            status="example",
            values={
                "underpayment_rate": {
                    "2026Q2": {"value": "0.06", "source": "SYNTHETIC test-only Q2-2026 rate"},
                }
            },
        )
        item = InstallmentUnderpayment(
            quarter=4, due_date=date(2026, 4, 1), underpayment=D(10_000), paid_date=None
        )
        p = compute_installment_penalty(item, pack, return_due_date=RETURN_DUE)
        # the general Q2-2026 rate (6%) was applied, proving the fallback path:
        # 10000 * 14/365 * 0.06
        assert p.penalty.value == D(10_000) * D(14) / D(365) * D("0.06")


class TestMissingRate:
    def test_period_without_a_rate_on_file_raises(self):
        """An underpayment reaching into a quarter the rates file does not cover
        fails loud rather than guessing a rate."""
        item = InstallmentUnderpayment(
            quarter=1, due_date=date(2025, 4, 15), underpayment=D(1_000), paid_date=None
        )
        with pytest.raises(RateNotAvailableError):
            # push the return due date far past the covered quarters
            compute_form2210_penalty([item], RATES, return_due_date=date(2027, 4, 15))
