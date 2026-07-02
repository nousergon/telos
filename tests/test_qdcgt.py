"""QDCGT worksheet — hand-computed cases + invariants against the TY2025 pack.

Hand computations follow the printed worksheet line-by-line (2025 Form 1040
instructions p. 38); the expected values in each test are worked in the
docstring so a reviewer can re-derive them without running code.
"""

from decimal import Decimal
from pathlib import Path
from typing import ClassVar

import pytest

from telos.engine import line16_tax_amount, qdcgt_worksheet
from telos.engine.trace import Traced
from telos.models import FilingStatus
from telos.params import load_pack

D = Decimal
PACK = load_pack(Path(__file__).parent.parent / "params" / "ty2025.yaml")
SINGLE_SCHED = PACK.brackets("ordinary_brackets.single")


def run(taxable, qd, ncg, fs=FilingStatus.SINGLE):
    return qdcgt_worksheet(
        taxable_income=Traced(label="taxable", value=D(taxable)),
        qualified_dividends=Traced(label="qd", value=D(qd)),
        net_capital_gain=Traced(label="ncg", value=D(ncg)),
        filing_status=fs,
        pack=PACK,
    )


class TestHandComputedCases:
    def test_qualified_dividends_in_15pct_zone(self):
        """Single, taxable 100,000, QD 10,000, no cap gain.
        L5=90,000; L6=48,350; L7=48,350; L8=48,350; L9=0; L10=10,000;
        L12=10,000; L14=100,000; L15=90,000; L16=10,000; L17=10,000;
        L18=1,500; L19=10,000; L20=0; L21=0;
        L22=table(90,000)=round(5,578.50+.22*(90,025-48,475))=14,720;
        L23=16,220; L24=TCW(100,000)=.22*100,000-5,086=16,914;
        L25=min=16,220."""
        r = run(100_000, 10_000, 0)
        assert r.lines[9].value == D(0)
        assert r.lines[18].value == D(1_500)
        assert r.lines[22].value == D(14_720)
        assert r.lines[24].value == D(16_914)
        assert r.tax.value == D(16_220)

    def test_gains_entirely_in_zero_rate_zone(self):
        """Single, taxable 40,000, QD 5,000, no cap gain.
        L5=35,000; L7=min(40,000,48,350)=40,000; L8=35,000; L9=5,000 (0%);
        L10=5,000; L12=0; L17=0; L18=0; L20=5,000-(5,000+0)=0; L21=0;
        L22=table(35,000)=round(1,192.50+.12*(35,025-11,925))=3,965;
        L23=3,965; L24=table(40,000)=round(1,192.50+.12*(40,025-11,925))=4,565;
        L25=3,965 — the 5,000 of QD is taxed at exactly 0%."""
        r = run(40_000, 5_000, 0)
        assert r.lines[9].value == D(5_000)
        assert r.lines[18].value == D(0)
        assert r.lines[21].value == D(0)
        assert r.tax.value == D(3_965)

    def test_20pct_zone_engaged_above_15pct_max(self):
        """Single, taxable 600,000, QD 0, net capital gain 100,000.
        L5=500,000; L6=48,350; L7=48,350; L8=48,350; L9=0; L10=100,000;
        L12=100,000; L13=533,400; L14=533,400; L15=500,000; L16=33,400;
        L17=33,400; L18=5,010; L19=33,400; L20=66,600; L21=13,320;
        L22=TCW(500,000)=.35*500,000-30,452.75=144,547.25 -> 144,547;
        L23=5,010+13,320+144,547=162,877;
        L24=TCW(600,000)=.35*600,000-30,452.75=179,547.25 -> 179,547;
        L25=162,877."""
        r = run(600_000, 0, 100_000)
        assert r.lines[16].value == D(33_400)
        assert r.lines[18].value == D(5_010)
        assert r.lines[21].value == D(13_320)
        assert r.tax.value == D(162_877)

    def test_no_preferential_income_equals_plain_line16(self):
        r = run(80_000, 0, 0)
        assert r.tax.value == line16_tax_amount(D(80_000), SINGLE_SCHED)


class TestInvariants:
    GRID: ClassVar[list[tuple[int, int]]] = [
        (t, qd)
        for t in (0, 15_000, 48_350, 60_000, 99_975, 100_000, 250_525, 533_400, 700_000)
        for qd in (0, 1_000, 20_000, 60_000)
        if qd <= t
    ]

    def test_never_exceeds_ordinary_tax(self):
        for taxable, qd in self.GRID:
            r = run(taxable, qd, 0)
            assert r.tax.value <= r.lines[24].value, (taxable, qd)

    def test_worksheet_lines_all_present_and_traced(self):
        r = run(100_000, 10_000, 5_000)
        assert set(r.lines) == set(range(1, 26))
        assert all(r.lines[n].label == f"qdcgt:line{n}" for n in (1, 9, 25))

    def test_provenance_reaches_pack_citations(self):
        r = run(100_000, 10_000, 0)
        srcs = " | ".join(r.tax.all_sources())
        assert "Qualified Dividends and Capital Gain Tax Worksheet" in srcs
        assert "Rev. Proc. 2024-40" in srcs  # breakpoints ride in from the pack

    def test_negative_input_rejected(self):
        with pytest.raises(ValueError, match=">= 0"):
            run(100_000, -1, 0)

    def test_filing_status_breakpoints_respected(self):
        """MFJ zero-rate max (96,700) shelters more gain than single (48,350):
        same 60,000 taxable / 20,000 QD is fully 0%-rate for MFJ."""
        mfj = run(60_000, 20_000, 0, fs=FilingStatus.MARRIED_FILING_JOINTLY)
        assert mfj.lines[9].value == D(20_000)
