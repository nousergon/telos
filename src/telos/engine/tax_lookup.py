"""Line-16 tax lookup: Tax Table below $100,000, Tax Computation Worksheet at or above.

The Form 1040 instructions' line-16 rule (and every worksheet that says
"figure the tax") is NOT a straight bracket formula below $100,000 — it is a
table lookup with binned income, and the table's cells are the bracket
formula evaluated at the **bin midpoint**, rounded half-up to whole dollars.
Reproducing the table's semantics (not just the algebra) is required to match
a commercially-prepared return to the dollar.

Structure verified against printed cells of the 2025 Tax Table (fetched from
the 2025 Instructions for Form 1040, pp. 66-77): bins are [0,5) -> tax $0,
[5,15) midpoint 10, [15,25) midpoint 20, $25 bins to $3,000, then $50 bins to
$100,000. Verified samples: 25-50 -> $4; 3,000-3,050 -> $303; 50,000-50,050 ->
$5,920 single / $5,526 MFJ / $5,663 HOH.

At or above $100,000 the Tax Computation Worksheet applies; its printed
"multiplication amount minus subtraction amount" rows are algebraically the
progressive bracket formula (e.g. Section A 22% row: 0.22x - $5,086.00 ==
$5,578.50 + 0.22(x - $48,475)), so ``tax_from_brackets`` is exact there.
"""

from __future__ import annotations

from decimal import Decimal

from telos.engine.brackets import Bracket, tax_from_brackets
from telos.engine.rounding import round_whole_dollar
from telos.engine.trace import Traced

TAX_TABLE_CITE = "2025 Form 1040 instructions, Tax Table"
TCW_CITE = "2025 Form 1040 instructions, Tax Computation Worksheet—Line 16"

TABLE_CEILING = Decimal(100_000)
_FIFTY_BINS_START = Decimal(3_000)


def _table_midpoint(taxable: Decimal) -> Decimal:
    """The Tax Table bin midpoint for an amount in [5, 100,000)."""
    if taxable < 15:
        return Decimal(10)
    if taxable < 25:
        return Decimal(20)
    if taxable < _FIFTY_BINS_START:
        lower = (taxable // 25) * 25
        return lower + Decimal("12.5")
    lower = (taxable // 50) * 50
    return lower + Decimal(25)


def tax_from_table(taxable: Decimal, brackets: list[Bracket]) -> Decimal:
    """Tax Table semantics for taxable income below $100,000."""
    if not Decimal(0) <= taxable < TABLE_CEILING:
        raise ValueError(f"Tax Table applies to [0, {TABLE_CEILING}), got {taxable}")
    if taxable < 5:
        return Decimal(0)
    return round_whole_dollar(tax_from_brackets(_table_midpoint(taxable), brackets))


def line16_tax_amount(taxable: Decimal, brackets: list[Bracket]) -> Decimal:
    """The line-16 rule: Table if less than $100,000, TCW at $100,000 or more."""
    if taxable < TABLE_CEILING:
        return tax_from_table(taxable, brackets)
    return round_whole_dollar(tax_from_brackets(taxable, brackets))


def line16_tax(label: str, taxable: Traced, brackets: list[Bracket]) -> Traced:
    """Traced line-16 lookup; the citation names which method applied."""
    cite = TAX_TABLE_CITE if taxable.value < TABLE_CEILING else TCW_CITE
    return Traced(
        label=label,
        value=line16_tax_amount(taxable.value, brackets),
        sources=(cite,),
        inputs=(taxable,),
    )
