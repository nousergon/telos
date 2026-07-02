"""Form 8995-A — the three regimes, guards, and the 1040 line-13 seam."""

from decimal import Decimal
from pathlib import Path

import pytest

from telos.engine import Form1040Inputs, assemble_1040
from telos.engine.form8995a import Form8995AInputs, QbiBusiness, form8995a
from telos.engine.guard import CoverageError
from telos.models import FilingStatus
from telos.params import load_pack

D = Decimal
PACK = load_pack(Path(__file__).parent.parent / "params" / "ty2025.yaml")


def run(businesses, ti, ncg_qd=0, **kw):
    return form8995a(
        Form8995AInputs(
            filing_status=kw.pop("filing_status", FilingStatus.SINGLE),
            businesses=tuple(businesses),
            taxable_income_before_qbi=D(ti),
            net_capital_gain_plus_qualified_dividends=D(ncg_qd),
            **kw,
        ),
        PACK,
    )


def rental(name="wadsworth", qbi=10_000, wages=0, ubia=300_000):
    return QbiBusiness(name=name, qbi=D(qbi), w2_wages=D(wages), ubia=D(ubia))


class TestAboveRange:
    def test_ubia_leg_keeps_rental_deduction_alive(self):
        """TI 310,000 (> 247,300, fully limited). QBI 10,000, wages 0,
        UBIA 300,000: L3 = 2,000; L5 = 0; L9 = 0 + 7,500 = 7,500; L10 =
        7,500; L11 = min(2,000, 7,500) = 2,000 -> deduction 2,000 (income
        limitation slack)."""
        r = run([rental()], ti=310_000, ncg_qd=50_000)
        biz = r.per_business["wadsworth"]
        assert biz[8].value == D(7_500)
        assert biz[11].value == D(2_000)
        assert r.deduction.value == D(2_000)

    def test_wage_ubia_limit_binds_with_small_ubia(self):
        """UBIA 20,000: L9 = 500; L11 = min(2,000, 500) = 500."""
        r = run([rental(ubia=20_000)], ti=310_000)
        assert r.deduction.value == D(500)

    def test_zero_wages_zero_ubia_kills_deduction_above_range(self):
        r = run([rental(ubia=0)], ti=310_000)
        assert r.deduction.value == D(0)


class TestAtOrBelowThreshold:
    def test_line3_taken_directly(self):
        """TI 150,000 <= 197,300: line 13 = line 3 = 2,000 even with zero
        wages and zero UBIA."""
        r = run([rental(ubia=0)], ti=150_000)
        assert r.deduction.value == D(2_000)


class TestPhaseInRange:
    def test_half_way_through_range_hand_computed(self):
        """TI 222,300 (midpoint): QBI 50,000, wages 0, UBIA 0. L3 = 10,000;
        L10 = 0 < L3 -> Part III: L19 = 10,000; pct = 25,000/50,000 = 50%;
        L25 = 5,000; L26 = 5,000; L13 = max(0, 5,000) = 5,000."""
        r = run([rental(qbi=50_000, ubia=0)], ti=222_300)
        biz = r.per_business["wadsworth"]
        assert biz[25].value == D(5_000)
        assert r.deduction.value == D(5_000)

    def test_no_reduction_when_limit_not_binding_in_range(self):
        """In range but L10 >= L3: no Part III (line 13 = line 11 = line 3)."""
        r = run([rental(qbi=10_000, ubia=300_000)], ti=222_300)
        assert r.deduction.value == D(2_000)

    def test_mfj_range_from_pack(self):
        """MFJ: threshold 394,600 / range top 494,600. TI 444,600 midpoint;
        QBI 50,000, no wage/UBIA: L25 = 5,000 -> deduction 5,000."""
        r = run([rental(qbi=50_000, ubia=0)], ti=444_600,
                filing_status=FilingStatus.MARRIED_FILING_JOINTLY)
        assert r.deduction.value == D(5_000)


class TestPartIV:
    def test_income_limitation_binds(self):
        """QBI 200,000 at TI 45,000 (below threshold): line 3 = 40,000 but
        line 36 = 20% * 45,000 = 9,000 binds."""
        r = run([rental(qbi=200_000)], ti=45_000)
        assert r.lines[36].value == D(9_000)
        assert r.deduction.value == D(9_000)

    def test_capital_gains_reduce_the_income_limitation(self):
        """Line 34 subtracts net capital gain + QD: TI 45,000 with 30,000
        preferential -> line 35 = 15,000 -> limit 3,000."""
        r = run([rental(qbi=200_000)], ti=45_000, ncg_qd=30_000)
        assert r.deduction.value == D(3_000)

    def test_reit_ptp_component(self):
        """REIT dividends 5,000 (below threshold, QBI 10,000, TI 150,000):
        line 31 = 1,000; line 32 = 3,000."""
        r = run([rental()], ti=150_000, reit_ptp_income=D(5_000))
        assert r.lines[31].value == D(1_000)
        assert r.deduction.value == D(3_000)


class TestGuardsAndEdges:
    def test_all_negative_qbi_zero_deduction_with_carryforward(self):
        r = run([rental(qbi=-4_000), rental(name="ballard", qbi=-1_000)], ti=310_000)
        assert r.deduction.value == D(0)
        assert r.negative_qbi_carryforward == D(-5_000)

    def test_mixed_sign_qbi_fails_loud(self):
        with pytest.raises(CoverageError, match="mixed-sign"):
            run([rental(qbi=-4_000), rental(name="ballard", qbi=9_000)], ti=310_000)

    def test_sstb_above_threshold_fails_loud(self):
        sstb = QbiBusiness(name="consulting", qbi=D(50_000), is_sstb=True)
        with pytest.raises(CoverageError, match="SSTB"):
            run([sstb], ti=310_000)

    def test_sstb_below_threshold_allowed(self):
        sstb = QbiBusiness(name="consulting", qbi=D(50_000), is_sstb=True)
        assert run([sstb], ti=150_000).deduction.value == D(10_000)

    def test_dpad_guard(self):
        with pytest.raises(CoverageError, match="DPAD"):
            run([rental()], ti=150_000, dpad_199ag=D(1))

    def test_provenance_reaches_pack(self):
        r = run([rental(qbi=50_000, ubia=0)], ti=222_300)
        assert any("Rev. Proc. 2024-40" in s for s in r.deduction.all_sources())


class TestFeeds1040Line13:
    def test_qbi_deduction_reduces_taxable_income(self):
        from telos.models import W2

        result = assemble_1040(
            Form1040Inputs(
                filing_status=FilingStatus.SINGLE,
                w2s=(W2(employer="Acme", wages=D(200_000)),),
                qbi_deduction=D(2_000),
            ),
            PACK,
        )
        # 200,000 - 15,750 (std) - 2,000 (QBI) = 182,250
        assert result.lines["13"].value == D(2_000)
        assert result.lines["15"].value == D(182_250)
