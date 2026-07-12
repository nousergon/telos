"""Print-package assembly: ordering and concatenation."""

from __future__ import annotations

from decimal import Decimal
from pathlib import Path

import pytest
from pypdf import PdfReader

from telos.forms.filler import fill_form_bytes
from telos.forms.package import FilledForm, assemble_package, package_order
from telos.forms.profile import FormProfile


def _profile(form_id: str, order: int) -> FormProfile:
    return FormProfile(
        form_id=form_id,
        title=form_id,
        template_filename="synthetic.pdf",
        filing_order=order,
        field_map={"1a": "line_1a"},
        verified=True,
    )


def _filled(synthetic_template: Path, form_id: str, order: int) -> FilledForm:
    data = fill_form_bytes(synthetic_template, {"1a": Decimal("1")}, _profile(form_id, order))
    return FilledForm(profile=_profile(form_id, order), pdf_bytes=data)


def test_package_orders_by_filing_order(synthetic_template: Path, tmp_path: Path) -> None:
    forms = [
        _filled(synthetic_template, "sched_e", 3),
        _filled(synthetic_template, "f1040", 1),
        _filled(synthetic_template, "sched_a", 2),
    ]
    assert package_order(forms) == ["f1040", "sched_a", "sched_e"]
    out = assemble_package(forms, tmp_path / "package.pdf")
    assert out.is_file()
    assert len(PdfReader(str(out)).pages) == 3  # one page each


def test_tie_break_is_stable_by_form_id(synthetic_template: Path) -> None:
    forms = [
        _filled(synthetic_template, "b_form", 1),
        _filled(synthetic_template, "a_form", 1),
    ]
    assert package_order(forms) == ["a_form", "b_form"]


def test_empty_package_raises(tmp_path: Path) -> None:
    with pytest.raises(ValueError):
        assemble_package([], tmp_path / "empty.pdf")
