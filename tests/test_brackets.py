from decimal import Decimal
from itertools import pairwise
from typing import ClassVar

import pytest

from telos.engine import Bracket, marginal_rate, tax_from_brackets
from telos.engine.brackets import BracketScheduleError, validate_brackets

D = Decimal

SCHEDULE = [
    Bracket(upto=D(10_000), rate=D("0.10")),
    Bracket(upto=D(40_000), rate=D("0.20")),
    Bracket(upto=None, rate=D("0.30")),
]


class TestTaxFromBrackets:
    def test_zero_income(self):
        assert tax_from_brackets(D(0), SCHEDULE) == D(0)

    def test_within_first_bracket(self):
        assert tax_from_brackets(D(5_000), SCHEDULE) == D(500)

    def test_exactly_at_first_boundary(self):
        assert tax_from_brackets(D(10_000), SCHEDULE) == D(1_000)

    def test_spanning_two_brackets(self):
        # 10k @ 10% + 20k @ 20% = 1,000 + 4,000
        assert tax_from_brackets(D(30_000), SCHEDULE) == D(5_000)

    def test_into_open_ended_top(self):
        # 10k @ 10% + 30k @ 20% + 60k @ 30% = 1,000 + 6,000 + 18,000
        assert tax_from_brackets(D(100_000), SCHEDULE) == D(25_000)

    def test_negative_income_rejected(self):
        with pytest.raises(ValueError, match=">= 0"):
            tax_from_brackets(D(-1), SCHEDULE)

    def test_result_is_exact_not_rounded(self):
        assert tax_from_brackets(D("10000.50"), SCHEDULE) == D("1000.10")


class TestTaxProperties:
    """Property-style sweeps: cheap invariants that catch transposed constants."""

    SWEEP: ClassVar[list[Decimal]] = [D(x) for x in range(0, 120_001, 1_000)]

    def test_monotonic_nondecreasing(self):
        taxes = [tax_from_brackets(x, SCHEDULE) for x in self.SWEEP]
        assert all(b >= a for a, b in pairwise(taxes))

    def test_continuous_at_boundaries(self):
        cent = D("0.01")
        for boundary in (D(10_000), D(40_000)):
            below = tax_from_brackets(boundary - cent, SCHEDULE)
            at = tax_from_brackets(boundary, SCHEDULE)
            # the step across a boundary is bounded by rate * one cent
            assert at - below <= D("0.30") * cent + D("1e-9")

    def test_average_rate_never_exceeds_marginal(self):
        for x in self.SWEEP:
            if x == 0:
                continue
            avg = tax_from_brackets(x, SCHEDULE) / x
            assert avg <= marginal_rate(x, SCHEDULE)

    def test_tax_bounded_by_top_rate(self):
        for x in self.SWEEP:
            assert tax_from_brackets(x, SCHEDULE) <= x * D("0.30")


class TestMarginalRate:
    @pytest.mark.parametrize(
        ("income", "rate"),
        [
            (D(0), "0.10"),
            (D(9_999), "0.10"),
            (D(10_000), "0.20"),
            (D(40_000), "0.30"),
            (D(1_000_000), "0.30"),
        ],
    )
    def test_rate_at(self, income, rate):
        assert marginal_rate(income, SCHEDULE) == D(rate)


class TestValidation:
    def test_empty_schedule(self):
        with pytest.raises(BracketScheduleError, match="empty"):
            validate_brackets([])

    def test_last_must_be_open_ended(self):
        with pytest.raises(BracketScheduleError, match="open-ended"):
            validate_brackets([Bracket(upto=D(10), rate=D("0.1"))])

    def test_open_ended_row_before_last_rejected(self):
        with pytest.raises(BracketScheduleError, match="before the last"):
            validate_brackets(
                [Bracket(upto=None, rate=D("0.1")), Bracket(upto=None, rate=D("0.2"))]
            )

    def test_descending_bounds_rejected(self):
        with pytest.raises(BracketScheduleError, match="strictly greater"):
            validate_brackets(
                [
                    Bracket(upto=D(40_000), rate=D("0.1")),
                    Bracket(upto=D(10_000), rate=D("0.2")),
                    Bracket(upto=None, rate=D("0.3")),
                ]
            )

    def test_rate_above_one_rejected(self):
        with pytest.raises(BracketScheduleError, match="outside"):
            validate_brackets([Bracket(upto=None, rate=D("1.5"))])

    def test_negative_rate_rejected(self):
        with pytest.raises(BracketScheduleError, match="outside"):
            validate_brackets([Bracket(upto=None, rate=D("-0.1"))])
