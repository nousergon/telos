"""Tax Table / Tax Computation Worksheet fidelity.

The printed-cell fixtures below are transcribed verbatim from the 2025 Tax
Table (2025 Instructions for Form 1040, fetched 2026-07-02): the emulation
must reproduce the IRS's own printed cells, not merely plausible values.
"""

from decimal import Decimal
from itertools import pairwise
from pathlib import Path

import pytest

from telos.engine import line16_tax, line16_tax_amount, tax_from_brackets, tax_from_table
from telos.params import load_pack

D = Decimal
PACK = load_pack(Path(__file__).parent.parent / "params" / "ty2025.yaml")
SINGLE = PACK.brackets("ordinary_brackets.single")
MFJ = PACK.brackets("ordinary_brackets.married_filing_jointly")
HOH = PACK.brackets("ordinary_brackets.head_of_household")


class TestPrintedTableCells:
    """Cells quoted from the printed 2025 Tax Table."""

    @pytest.mark.parametrize(
        ("taxable", "schedule", "printed"),
        [
            # "50,000 50,050 5,920 5,526 5,920 5,663" (p. 74)
            (D(50_000), SINGLE, "5920"),
            (D(50_000), MFJ, "5526"),
            (D(50_000), HOH, "5663"),
            (D(50_049), SINGLE, "5920"),  # same bin, same cell
            # "49,950 50,000 5,909 5,520 5,909 5,657"
            (D(49_975), SINGLE, "5909"),
            # small bins (p. 68): "0 5 0...", "5 15 1...", "15 25 2...",
            # "25 50 4...", "75 100 9...", "3,000 3,050 303..."
            (D(3), SINGLE, "0"),
            (D(10), SINGLE, "1"),
            (D(24), SINGLE, "2"),
            (D(30), SINGLE, "4"),
            (D(80), SINGLE, "9"),
            (D(3_025), SINGLE, "303"),
        ],
    )
    def test_cell(self, taxable, schedule, printed):
        assert tax_from_table(taxable, schedule) == D(printed)

    def test_table_rejects_100k_and_above(self):
        with pytest.raises(ValueError, match="Tax Table"):
            tax_from_table(D(100_000), SINGLE)


class TestTaxComputationWorksheet:
    """The printed TCW rows (Section A, single) are rate*x - subtraction;
    they must be algebraically identical to the bracket formula."""

    @pytest.mark.parametrize(
        ("rate", "subtraction", "lo", "hi"),
        [
            ("0.22", "5086.00", 100_000, 103_350),
            ("0.24", "7153.00", 103_350, 197_300),
            ("0.32", "22937.00", 197_300, 250_525),
            ("0.35", "30452.75", 250_525, 626_350),
            ("0.37", "42979.75", 626_350, 900_000),
        ],
    )
    def test_printed_subtraction_amounts_match_bracket_formula(self, rate, subtraction, lo, hi):
        for x in (D(lo), D((lo + hi) // 2), D(hi)):
            assert D(rate) * x - D(subtraction) == tax_from_brackets(x, SINGLE)


class TestLine16Dispatch:
    def test_below_100k_uses_table(self):
        # table value differs from exact formula whenever income != bin midpoint
        exact = tax_from_brackets(D(99_990), SINGLE)
        assert line16_tax_amount(D(99_990), SINGLE) != exact.quantize(D("0.01"))

    def test_at_100k_uses_tcw_exact(self):
        assert line16_tax_amount(D(100_000), SINGLE) == D("0.22") * D(100_000) - D("5086.00")

    def test_traced_citation_names_method(self):
        from telos.engine.trace import Traced

        below = line16_tax("t", Traced(label="x", value=D(50_000)), SINGLE)
        above = line16_tax("t", Traced(label="x", value=D(200_000)), SINGLE)
        assert "Tax Table" in below.sources[0]
        assert "Tax Computation Worksheet" in above.sources[0]

    def test_monotonic_across_dispatch_boundary(self):
        taxes = [line16_tax_amount(D(x), SINGLE) for x in range(99_000, 101_001, 50)]
        assert all(b >= a for a, b in pairwise(taxes))
