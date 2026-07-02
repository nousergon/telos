from decimal import Decimal
from pathlib import Path

import pytest

from telos.engine import tax_from_brackets
from telos.params import ParamPack, ParamPackError, load_pack

D = Decimal
EXAMPLE_PACK = Path(__file__).parent.parent / "params" / "example_pack.yaml"


@pytest.fixture()
def pack() -> ParamPack:
    return load_pack(EXAMPLE_PACK)


class TestLoadExamplePack:
    def test_loads(self, pack):
        assert pack.tax_year == 1999
        assert pack.status == "example"

    def test_scalar_get_returns_traced_with_citation(self, pack):
        sd = pack.get("standard_deduction.single")
        assert sd.value == D(10_000)
        assert sd.label == "param:ty1999.standard_deduction.single"
        assert any("SYNTHETIC" in s for s in sd.sources)

    def test_brackets_parse_and_validate(self, pack):
        schedule = pack.brackets("ordinary_brackets.single")
        assert len(schedule) == 3
        assert schedule[-1].upto is None

    def test_engine_integration(self, pack):
        schedule = pack.brackets("ordinary_brackets.single")
        # 10k @ 10% + 20k @ 20% = 5,000 on 30k
        assert tax_from_brackets(D(30_000), schedule) == D(5_000)

    def test_missing_path_raises(self, pack):
        with pytest.raises(KeyError, match=r"standard_deduction\.widow"):
            pack.get("standard_deduction.widow")

    def test_get_on_subtree_rejected(self, pack):
        with pytest.raises(ParamPackError, match="not a scalar"):
            pack.get("standard_deduction")

    def test_brackets_on_scalar_rejected(self, pack):
        with pytest.raises(ParamPackError, match="not a bracket"):
            pack.brackets("standard_deduction.single")


def _pack(**overrides):
    base = {
        "tax_year": 1999,
        "status": "example",
        "values": {"x": {"value": 1, "source": "SYNTHETIC test"}},
    }
    base.update(overrides)
    return base


class TestContractEnforcement:
    def test_leaf_without_source_rejected(self):
        with pytest.raises((ParamPackError, ValueError), match="no source citation"):
            ParamPack(**_pack(values={"x": {"value": 1}}))

    def test_bracket_row_without_source_rejected(self):
        with pytest.raises((ParamPackError, ValueError), match="no source citation"):
            ParamPack(**_pack(values={"b": [{"upto": None, "rate": "0.1"}]}))

    def test_unknown_top_level_key_rejected(self):
        with pytest.raises(ValueError, match="extra"):
            ParamPack(**_pack(notes="hello"))

    def test_unexpected_leaf_keys_rejected(self):
        with pytest.raises((ParamPackError, ValueError), match="unexpected keys"):
            ParamPack(**_pack(values={"x": {"value": 1, "source": "s", "comment": "hm"}}))

    def test_bare_scalar_leaf_rejected(self):
        with pytest.raises((ParamPackError, ValueError), match="unsupported node shape"):
            ParamPack(**_pack(values={"x": 5}))

    def test_empty_values_rejected(self):
        with pytest.raises((ParamPackError, ValueError), match="no values"):
            ParamPack(**_pack(values={}))

    def test_final_with_synthetic_marker_refused(self):
        with pytest.raises((ParamPackError, ValueError), match="final"):
            ParamPack(**_pack(status="final"))

    def test_final_with_verified_citation_loads(self):
        p = ParamPack(
            **_pack(status="final", values={"x": {"value": 1, "source": "Rev. Proc. 1998-99 §1"}})
        )
        assert p.get("x").value == D(1)

    def test_provisional_with_unverified_marker_allowed(self):
        p = ParamPack(
            **_pack(status="provisional", values={"x": {"value": 1, "source": "UNVERIFIED draft"}})
        )
        assert p.status == "provisional"

    def test_non_mapping_yaml_rejected(self, tmp_path):
        f = tmp_path / "bad.yaml"
        f.write_text("- just\n- a\n- list\n")
        with pytest.raises(ParamPackError, match="must be a mapping"):
            load_pack(f)
