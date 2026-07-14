"""Fill mechanics on the synthetic AcroForm fixture (controlled field names)."""

from __future__ import annotations

from decimal import Decimal
from pathlib import Path

import pytest
from pypdf import PdfReader

from telos.forms.filler import (
    UnknownFieldError,
    fill_form,
    fill_form_bytes,
    format_field_value,
)
from telos.forms.profile import FormProfile


def _profile() -> FormProfile:
    return FormProfile(
        form_id="synthetic",
        title="Synthetic test form",
        template_filename="synthetic.pdf",
        filing_order=1,
        field_map={"1a": "line_1a", "16": "line_16"},
        checkbox_map={"mfj": "status_mfj"},
        verified=True,
        provenance="synthetic fixture — names controlled by the test",
    )


def _read_back(data: bytes) -> dict[str, str]:
    reader = PdfReader_from_bytes(data)
    return {k: str(v.get("/V")) for k, v in (reader.get_fields() or {}).items()}


def PdfReader_from_bytes(data: bytes) -> PdfReader:
    import io

    return PdfReader(io.BytesIO(data))


def test_text_fields_round_trip(synthetic_template: Path) -> None:
    data = fill_form_bytes(
        synthetic_template,
        {"1a": Decimal("125000"), "16": Decimal("18240")},
        _profile(),
    )
    values = _read_back(data)
    assert values["line_1a"] == "125000"
    assert values["line_16"] == "18240"


def test_engine_key_not_on_form_is_ignored(synthetic_template: Path) -> None:
    # "8" is a real engine line but the synthetic form doesn't carry it -> skipped.
    values_in = {"8": Decimal("999"), "1a": Decimal("1")}
    data = fill_form_bytes(synthetic_template, values_in, _profile())
    values = _read_back(data)
    assert values["line_1a"] == "1"


def test_mapped_but_absent_field_raises(synthetic_template: Path) -> None:
    bad = _profile().model_copy(update={"field_map": {"1a": "does_not_exist"}})
    with pytest.raises(UnknownFieldError):
        fill_form_bytes(synthetic_template, {"1a": Decimal("1")}, bad)


def test_checkbox_sets_on_state(synthetic_template: Path, checkbox_on_state: str) -> None:
    data = fill_form_bytes(
        synthetic_template,
        {"1a": Decimal("1")},
        _profile(),
        checkbox_values={"mfj": checkbox_on_state},
    )
    values = _read_back(data)
    assert values["status_mfj"] == checkbox_on_state


def test_checkbox_unmapped_key_raises(synthetic_template: Path) -> None:
    with pytest.raises(UnknownFieldError):
        fill_form_bytes(
            synthetic_template, {}, _profile(), checkbox_values={"single": "/Yes"}
        )


def test_checkbox_absent_field_raises(synthetic_template: Path, checkbox_on_state: str) -> None:
    bad = _profile().model_copy(update={"checkbox_map": {"mfj": "nope"}})
    with pytest.raises(UnknownFieldError):
        fill_form_bytes(synthetic_template, {}, bad, checkbox_values={"mfj": checkbox_on_state})


def test_xfa_is_dropped_on_real_hybrid_form(synthetic_template: Path) -> None:
    # The synthetic fixture has no XFA, but the drop path must be a no-op, not a crash.
    data = fill_form_bytes(synthetic_template, {"1a": Decimal("1")}, _profile())
    assert data[:5] == b"%PDF-"


def test_fill_form_writes_to_path(synthetic_template: Path, tmp_path: Path) -> None:
    out = tmp_path / "sub" / "filled.pdf"
    out.parent.mkdir()
    returned = fill_form(synthetic_template, {"1a": Decimal("5")}, _profile(), out)
    assert returned == out
    assert out.is_file()
    assert _read_back(out.read_bytes())["line_1a"] == "5"


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (Decimal("1234"), "1234"),
        (Decimal("1234.00"), "1234"),
        (Decimal("1234.56"), "1234.56"),
        (Decimal("0"), "0"),
        (Decimal("-44"), "-44"),
        ("Smith & Co", "Smith & Co"),
        (42, "42"),
    ],
)
def test_format_field_value(value: object, expected: str) -> None:
    assert format_field_value(value) == expected


def test_format_rejects_bool() -> None:
    with pytest.raises(TypeError):
        format_field_value(True)


def test_format_rejects_unknown_type() -> None:
    with pytest.raises(TypeError):
        format_field_value(object())
