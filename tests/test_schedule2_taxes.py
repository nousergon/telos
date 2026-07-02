"""Forms 8959 + 8960 — hand-computed cases against the TY2025 pack."""

from decimal import Decimal
from pathlib import Path

import pytest

from telos.engine import Form1040Inputs, assemble_1040
from telos.engine.form8959 import MissingMedicareWagesError, form8959
from telos.engine.form8960 import Form8960Inputs, form8960
from telos.models import W2, FilingStatus
from telos.params import load_pack

D = Decimal
PACK = load_pack(Path(__file__).parent.parent / "params" / "ty2025.yaml")


def w2(employer="Acme", box1=250_000, box2=50_000, box5=260_000, box6=None):
    if box6 is None:
        # typical employer behavior: 1.45% + 0.9% on the excess over 200k
        box6 = round(box5 * 0.0145 + max(box5 - 200_000, 0) * 0.009, 2)
    return W2(
        employer=employer,
        wages=D(box1),
        federal_income_tax_withheld=D(box2),
        medicare_wages=D(box5),
        medicare_tax_withheld=D(str(box6)),
    )


class TestForm8959:
    def test_above_threshold_hand_computed(self):
        """Box 5 = 260,000 single: L6 = 60,000; L7 = 540. Employer withheld
        box 6 = 1.45%*260,000 + 0.9%*60,000 = 3,770 + 540 = 4,310; L21 =
        1.45%*260,000 = 3,770; L22 = 540; L24 = 540 (credit matches tax)."""
        r = form8959(w2s=[w2()], filing_status=FilingStatus.SINGLE, pack=PACK)
        assert r.lines[6].value == D(60_000)
        assert r.additional_medicare_tax.value == D(540)
        assert r.lines[21].value == D(3_770)
        assert r.additional_withholding.value == D(540)

    def test_below_threshold_zero(self):
        r = form8959(
            w2s=[w2(box5=150_000, box6=2_175)], filing_status=FilingStatus.SINGLE, pack=PACK
        )
        assert r.additional_medicare_tax.value == D(0)
        assert r.additional_withholding.value == D(0)

    def test_multiple_w2s_aggregate_box5(self):
        """Two W-2s 120k + 130k = 250k box 5: neither employer withholds the
        additional tax (each below 200k) but the RETURN owes 0.9% * 50,000 =
        450 with zero line-24 credit — the classic two-job surprise."""
        r = form8959(
            w2s=[w2("A", box5=120_000, box6=1_740), w2("B", box5=130_000, box6=1_885)],
            filing_status=FilingStatus.SINGLE,
            pack=PACK,
        )
        assert r.additional_medicare_tax.value == D(450)
        assert r.additional_withholding.value == D(0)

    def test_mfj_threshold_from_pack(self):
        r = form8959(
            w2s=[w2(box5=260_000)], filing_status=FilingStatus.MARRIED_FILING_JOINTLY, pack=PACK
        )
        assert r.lines[5].value == D(250_000)
        assert r.additional_medicare_tax.value == D(90)

    def test_missing_box5_fails_loud(self):
        bare = W2(employer="NoBox5", wages=D(250_000))
        with pytest.raises(MissingMedicareWagesError, match="NoBox5"):
            form8959(w2s=[bare], filing_status=FilingStatus.SINGLE, pack=PACK)

    def test_provenance_cites_form_and_statute(self):
        r = form8959(w2s=[w2()], filing_status=FilingStatus.SINGLE, pack=PACK)
        srcs = " | ".join(r.additional_medicare_tax.all_sources())
        assert "2025 Form 8959" in srcs
        assert "3101(b)(2)" in srcs  # threshold citation rides in from the pack


class TestForm8960:
    def test_niit_binds_on_magi_excess(self):
        """Interest 5,000 + dividends 20,000 + net gain 30,000 = NII 55,000;
        MAGI 210,000 single -> excess 10,000; smaller = 10,000; tax = 380."""
        r = form8960(
            Form8960Inputs(
                filing_status=FilingStatus.SINGLE,
                taxable_interest=D(5_000),
                ordinary_dividends=D(20_000),
                net_gain=D(30_000),
                magi=D(210_000),
            ),
            PACK,
        )
        assert r.lines["8"].value == D(55_000)
        assert r.lines["15"].value == D(10_000)
        assert r.niit.value == D(380)

    def test_niit_binds_on_nii_when_smaller(self):
        """NII 8,000, MAGI 400,000 -> excess 200,000; smaller = 8,000;
        tax = 304."""
        r = form8960(
            Form8960Inputs(
                filing_status=FilingStatus.SINGLE,
                ordinary_dividends=D(8_000),
                magi=D(400_000),
            ),
            PACK,
        )
        assert r.niit.value == D(304)

    def test_below_threshold_zero(self):
        r = form8960(
            Form8960Inputs(
                filing_status=FilingStatus.SINGLE,
                ordinary_dividends=D(50_000),
                magi=D(150_000),
            ),
            PACK,
        )
        assert r.niit.value == D(0)

    def test_rental_loss_reduces_nii(self):
        """Line 4a may be negative (rental loss): NII floors at 0 via line 12."""
        r = form8960(
            Form8960Inputs(
                filing_status=FilingStatus.SINGLE,
                taxable_interest=D(2_000),
                rental_and_passthrough=D(-10_000),
                magi=D(300_000),
            ),
            PACK,
        )
        assert r.lines["12"].value == D(0)
        assert r.niit.value == D(0)

    def test_expenses_reduce_nii(self):
        r = form8960(
            Form8960Inputs(
                filing_status=FilingStatus.SINGLE,
                ordinary_dividends=D(30_000),
                investment_expenses=D(4_000),
                magi=D(500_000),
            ),
            PACK,
        )
        assert r.lines["12"].value == D(26_000)
        assert r.niit.value == round(D(26_000) * D("0.038"))


class TestWiredIntoAssembly:
    def test_schedule2_taxes_flow_through_other_taxes_seam(self):
        """The two modules' outputs enter the 1040 via other_taxes, and the
        8959 line-24 credit belongs in withholding — modeled here explicitly
        until the assembly grows a line 25c (documented seam)."""
        the_w2 = w2(box1=250_000, box2=55_000, box5=260_000)
        r59 = form8959(w2s=[the_w2], filing_status=FilingStatus.SINGLE, pack=PACK)
        r60 = form8960(
            Form8960Inputs(
                filing_status=FilingStatus.SINGLE,
                ordinary_dividends=D(10_000),
                magi=D(260_000),
            ),
            PACK,
        )
        result = assemble_1040(
            Form1040Inputs(
                filing_status=FilingStatus.SINGLE,
                w2s=(the_w2,),
                other_taxes=(
                    ("form8959:additional_medicare", r59.additional_medicare_tax.value),
                    ("form8960:niit", r60.niit.value),
                ),
            ),
            PACK,
        )
        assert result.total_tax.value == result.lines["16"].value + D(540) + D(380)
