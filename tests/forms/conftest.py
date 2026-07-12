"""Shared fixtures for the forms-layer tests.

The synthetic AcroForm fixture lets the fill/package/introspect machinery be
validated end-to-end without a guessed real-1040 field map: we generate a tiny
PDF whose field names WE control, so a read-back assertion is meaningful.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from pypdf import PdfReader
from reportlab.pdfgen import canvas


def _build_acroform(path: Path) -> dict[str, str]:
    """Create a 1-page PDF with two text fields and a checkbox; return field names."""
    c = canvas.Canvas(str(path), pagesize=(612, 792))
    form = c.acroForm
    c.drawString(60, 700, "1a")
    form.textfield(name="line_1a", x=110, y=695, width=120, height=16, borderStyle="inset")
    c.drawString(60, 660, "16")
    form.textfield(name="line_16", x=110, y=655, width=120, height=16, borderStyle="inset")
    c.drawString(60, 620, "MFJ")
    form.checkbox(name="status_mfj", x=110, y=615, size=16, buttonStyle="check")
    c.save()
    return {"line_1a": "line_1a", "line_16": "line_16", "status_mfj": "status_mfj"}


@pytest.fixture
def synthetic_template(tmp_path: Path) -> Path:
    """Path to a freshly-generated synthetic AcroForm PDF."""
    path = tmp_path / "synthetic.pdf"
    _build_acroform(path)
    return path


@pytest.fixture
def checkbox_on_state(synthetic_template: Path) -> str:
    """The reportlab checkbox's on-state name (e.g. '/Yes'), read from the fixture."""
    reader = PdfReader(str(synthetic_template))
    for page in reader.pages:
        for annot in page.get("/Annots") or []:
            obj = annot.get_object()
            if obj.get("/T") == "status_mfj":
                ap = obj.get("/AP", {}).get("/N", {})
                states = [str(k) for k in ap if str(k) != "/Off"]
                if states:
                    return states[0]
    return "/Yes"
