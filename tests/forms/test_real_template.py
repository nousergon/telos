"""Validation against the REAL committed blank f1040 template.

Satisfies the telos-ops#10 closes-when at the mechanism level: a value is written
into the real IRS AcroForm and read back from the output PDF. It deliberately
does NOT assert a semantic line->field mapping — that map is unverified by design
(see forms/README.md); this proves only that pypdf can fill *this* real hybrid
(AcroForm+XFA) IRS PDF, which naive fillers get wrong.
"""

from __future__ import annotations

import io

from pypdf import PdfReader

from telos.forms import paths
from telos.forms.filler import fill_form_bytes
from telos.forms.introspect import describe_fields
from telos.forms.profile import FormProfile, load_profile

_EXPECTED_FIELD_COUNT = 229  # f1040.pdf AcroForm, verified at commit time


def _first_text_field(reader: PdfReader) -> str:
    for name, f in (reader.get_fields() or {}).items():
        if f.get("/FT") == "/Tx":
            return name
    raise AssertionError("real f1040 template has no text fields")


def test_real_template_is_present_and_shaped() -> None:
    template = paths.template_path("f1040.pdf")
    reader = PdfReader(str(template))
    fields = reader.get_fields() or {}
    assert len(fields) == _EXPECTED_FIELD_COUNT
    # The escalation's core observation: no /TU semantic tooltips anywhere.
    assert all(f.get("/TU") is None for f in fields.values())


def test_real_template_round_trip() -> None:
    template = paths.template_path("f1040.pdf")
    reader = PdfReader(str(template))
    field_name = _first_text_field(reader)

    # Ad-hoc verified profile mapping a synthetic key onto a REAL field by name.
    # This asserts round-trip fidelity, not semantic correctness.
    profile = FormProfile(
        form_id="f1040_roundtrip_probe",
        title="probe",
        template_filename="f1040.pdf",
        filing_order=1,
        field_map={"probe": field_name},
        verified=True,
        provenance="test probe — arbitrary real field, no semantic claim",
    )
    data = fill_form_bytes(template, {"probe": "424242"}, profile)
    out = PdfReader(io.BytesIO(data))
    assert str(out.get_fields()[field_name].get("/V")) == "424242"


def test_real_template_xfa_dropped_after_fill() -> None:
    template = paths.template_path("f1040.pdf")
    reader = PdfReader(str(template))
    field_name = _first_text_field(reader)
    profile = FormProfile(
        form_id="probe",
        title="probe",
        template_filename="f1040.pdf",
        filing_order=1,
        field_map={"probe": field_name},
        verified=True,
    )
    data = fill_form_bytes(template, {"probe": "1"}, profile)
    out = PdfReader(io.BytesIO(data))
    acro = out.trailer["/Root"].get("/AcroForm")
    assert acro is not None
    assert "/XFA" not in acro.get_object()


def test_real_template_introspection_finds_labels() -> None:
    template = paths.template_path("f1040.pdf")
    reader = PdfReader(str(template))
    field_names = set((reader.get_fields() or {}).keys())
    infos = describe_fields(template)

    # Names must be fully-qualified and usable in a field_map — i.e. a subset of
    # the canonical get_fields() names (radio-group widgets collapse to one name,
    # so describe_fields <= get_fields, never a disjoint/partial-name set).
    info_names = {i.name for i in infos}
    assert info_names <= field_names
    assert len(info_names) >= 190  # covers essentially every fillable box

    # The nearest-label heuristic should surface printed context for many fields
    # even though the PDF has no field tooltips — this is the mapping aid.
    with_context = [i for i in infos if i.nearest_text]
    assert len(with_context) >= 20


def test_committed_f1040_profile_stays_unverified() -> None:
    # Guardrail: the shipped profile must never silently gain a guessed map.
    profile = load_profile("f1040")
    assert profile.verified is False
    assert profile.field_map == {}
