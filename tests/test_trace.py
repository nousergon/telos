from dataclasses import FrozenInstanceError
from decimal import Decimal

import pytest

from telos.engine import Traced, traced_sum

D = Decimal


class TestTraced:
    def test_requires_label(self):
        with pytest.raises(ValueError, match="label"):
            Traced(label="", value=D(1))

    def test_value_coerced_to_decimal(self):
        t = Traced(label="x", value=100)
        assert isinstance(t.value, Decimal)
        assert t.value == D(100)

    def test_immutable(self):
        t = Traced(label="x", value=D(1))
        with pytest.raises(FrozenInstanceError):
            t.value = D(2)  # type: ignore[misc]

    def test_derive_links_provenance(self):
        wages = Traced(label="w2:acme.wages", value=D(50_000), sources=("doc:w2-acme",))
        cite = "Form 1040 instructions, line 1a"
        rounded = wages.derive("1040:line1a", D(50_000), sources=(cite,))
        assert rounded.inputs == (wages,)
        assert "doc:w2-acme" in rounded.all_sources()
        assert cite in rounded.all_sources()

    def test_all_sources_deduplicates_and_orders(self):
        a = Traced(label="a", value=D(1), sources=("s1",))
        b = Traced(label="b", value=D(2), sources=("s1", "s2"))
        total = traced_sum("total", [a, b], sources=("s3",))
        assert total.all_sources() == ("s3", "s1", "s2")

    def test_explain_renders_tree_with_citations(self):
        a = Traced(label="w2:acme.wages", value=D(50_000), sources=("doc:w2-acme",))
        b = Traced(label="w2:block.wages", value=D(30_000), sources=("doc:w2-block",))
        total = traced_sum("1040:line1a", [a, b])
        text = total.explain()
        assert "1040:line1a = 80000" in text
        assert "  w2:acme.wages = 50000  [doc:w2-acme]" in text
        assert "  w2:block.wages = 30000  [doc:w2-block]" in text


class TestTracedSum:
    def test_sums_values(self):
        items = [Traced(label=f"i{i}", value=D(i)) for i in (1, 2, 3)]
        assert traced_sum("total", items).value == D(6)

    def test_empty_sum_is_zero(self):
        assert traced_sum("total", []).value == D(0)

    def test_inputs_are_the_addends(self):
        items = [Traced(label="a", value=D(1)), Traced(label="b", value=D(2))]
        assert traced_sum("total", items).inputs == tuple(items)
