from decimal import Decimal

import pytest

from telos.engine import round_whole_dollar, to_decimal


class TestToDecimal:
    def test_str_exact(self):
        assert to_decimal("0.1") == Decimal("0.1")

    def test_float_goes_via_str_not_binary(self):
        # Decimal(0.1) would be 0.1000000000000000055511151231257827
        assert to_decimal(0.1) == Decimal("0.1")

    def test_int(self):
        assert to_decimal(42) == Decimal(42)

    def test_decimal_passthrough(self):
        d = Decimal("1.23")
        assert to_decimal(d) is d


class TestRoundWholeDollar:
    @pytest.mark.parametrize(
        ("raw", "expected"),
        [
            ("1.49", "1"),
            ("1.50", "2"),  # half rounds UP, not to even
            ("2.50", "3"),  # banker's rounding would give 2 — must not
            ("0.50", "1"),
            ("0.49", "0"),
            ("1234.999", "1235"),
            ("0", "0"),
        ],
    )
    def test_half_up(self, raw, expected):
        assert round_whole_dollar(Decimal(raw)) == Decimal(expected)

    def test_negative_half_up_magnitude(self):
        # ROUND_HALF_UP rounds away from zero on the .50 boundary
        assert round_whole_dollar(Decimal("-1.50")) == Decimal("-2")
        assert round_whole_dollar(Decimal("-1.49")) == Decimal("-1")

    def test_idempotent(self):
        once = round_whole_dollar(Decimal("7.77"))
        assert round_whole_dollar(once) == once

    def test_accepts_float_input(self):
        assert round_whole_dollar(2.5) == Decimal("3")
