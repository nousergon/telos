"""Validation against the REAL committed blank f1040 template.

Satisfies the telos-ops#10 closes-when: a synthetic return fills the real
f1040.pdf AcroForm via the now-verified field_map, and a test asserts values
read back from the output PDF land in the semantically correct boxes (not just
*some* named field — see ``test_end_to_end_synthetic_return_fills_real_1040``).
"""

from __future__ import annotations

import io
from decimal import Decimal
from pathlib import Path

from pypdf import PdfReader

from telos.engine import Form1040Inputs, assemble_1040
from telos.forms import paths
from telos.forms.filler import fill_form_bytes
from telos.forms.introspect import describe_fields
from telos.forms.profile import FormProfile, load_profile
from telos.models import W2, FilingStatus, Form1099Div, Form1099Int
from telos.params import load_pack

D = Decimal
_PACK = load_pack(Path(__file__).parent.parent.parent / "params" / "ty2025.yaml")

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


def test_committed_f1040_profile_field_map_targets_real_fields() -> None:
    # Guardrail (telos-ops#10 Option A, ratified by Brian 2026-07-13): every
    # mapped field name must exist on the real template, and the map must
    # never silently regress back to an empty, unverified stub.
    profile = load_profile("f1040")
    assert profile.verified is True
    assert profile.field_map  # non-empty
    template = paths.template_path("f1040.pdf")
    reader = PdfReader(str(template))
    available = set((reader.get_fields() or {}).keys())
    for engine_key, acro_name in profile.field_map.items():
        assert acro_name in available, f"{engine_key!r} -> {acro_name!r} not on f1040.pdf"


def test_committed_f1040_profile_no_duplicate_field_targets() -> None:
    # Two engine keys must never silently write into the same box. "34"/"37"
    # are the deliberate exception: refund vs. amount-owed are the same
    # signed balance_due, mutually exclusive by sign — a caller populates
    # exactly one of the two, never both.
    profile = load_profile("f1040")
    targets = [v for k, v in profile.field_map.items() if k not in ("34", "37")]
    assert len(targets) == len(set(targets))


def _mini_return() -> Form1040Inputs:
    # Same synthetic scenario as tests/test_form1040.py::mini_return — hand-
    # computed there: total income 92,500, taxable income 76,750, tax 11,700,
    # total_payments 11,000, balance_due +700 (amount owed, not a refund).
    return Form1040Inputs(
        filing_status=FilingStatus.SINGLE,
        w2s=(W2(employer="Acme", wages=D(90_000), federal_income_tax_withheld=D(10_000)),),
        forms_1099_int=(Form1099Int(payer="Bank", interest_income=D(500)),),
        forms_1099_div=(
            Form1099Div(
                payer="Broker",
                ordinary_dividends=D(2_000),
                qualified_dividends=D(1_500),
            ),
        ),
        estimated_payments=D(1_000),
    )


def test_end_to_end_synthetic_return_fills_real_1040() -> None:
    """telos-ops#10 closes-when: a synthetic return, filled into the real
    f1040.pdf via the verified field_map, reads back correct values from the
    semantically correct boxes (not merely *some* field — see the per-field
    assertions below, each pinned to the AcroForm name the map targets)."""
    result = assemble_1040(_mini_return(), _PACK)
    profile = load_profile("f1040")
    profile.require_verified()  # the filing-grade gate this whole map exists for

    field_values = {k: v.value for k, v in result.lines.items()}
    field_values["24"] = result.total_tax.value
    field_values["33"] = result.total_payments.value
    # balance_due > 0 => amount owed (line 37); this scenario owes, not refunds.
    assert result.balance_due.value > 0
    field_values["37"] = result.balance_due.value

    template = paths.template_path("f1040.pdf")
    data = fill_form_bytes(template, field_values, profile)
    out_fields = PdfReader(io.BytesIO(data)).get_fields() or {}

    expected = {
        "1a": "90000",
        "2b": "500",
        "3a": "1500",
        "3b": "2000",
        "9": "92500",
        "11": "92500",
        "12": "15750",
        "15": "76750",
        "16": "11700",
        "24": "11700",
        "25": "10000",
        "26": "1000",
        "33": "11000",
        "37": "700",
    }
    for engine_key, expected_value in expected.items():
        acro_name = profile.field_map[engine_key]
        assert str(out_fields[acro_name].get("/V")) == expected_value, engine_key
    # The mutually-exclusive refund box must stay untouched (this is an owed year).
    assert out_fields[profile.field_map["34"]].get("/V") is None
