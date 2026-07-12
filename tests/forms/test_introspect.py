"""Field introspection on the synthetic fixture (nearest-label heuristic)."""

from __future__ import annotations

from pathlib import Path

from telos.forms.introspect import describe_fields


def test_describe_fields_enumerates_all(synthetic_template: Path) -> None:
    infos = describe_fields(synthetic_template)
    names = {i.name for i in infos}
    assert names == {"line_1a", "line_16", "status_mfj"}


def test_field_types_and_pages(synthetic_template: Path) -> None:
    by_name = {i.name: i for i in describe_fields(synthetic_template)}
    assert by_name["line_1a"].field_type == "/Tx"
    assert by_name["status_mfj"].field_type == "/Btn"
    assert all(i.page_index == 0 for i in by_name.values())
    assert all(i.rect != (0.0, 0.0, 0.0, 0.0) for i in by_name.values())


def test_nearest_label_picks_left_printed_text(synthetic_template: Path) -> None:
    by_name = {i.name: i for i in describe_fields(synthetic_template)}
    # The "1a" / "16" labels are drawn just left of their boxes.
    assert by_name["line_1a"].nearest_text == "1a"
    assert by_name["line_16"].nearest_text == "16"
