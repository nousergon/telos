"""FormProfile loading, validation, and the verified-gate."""

from __future__ import annotations

import pytest

from telos.forms.profile import (
    FormProfile,
    UnverifiedProfileError,
    load_profile,
    profile_from_dict,
)


def test_load_committed_f1040_profile() -> None:
    profile = load_profile("f1040")
    assert profile.form_id == "f1040"
    assert profile.template_filename == "f1040.pdf"
    assert profile.filing_order == 1
    # Shipped intentionally unverified with an empty map (see telos-ops#10).
    assert profile.verified is False
    assert profile.field_map == {}


def test_committed_profile_gate_raises() -> None:
    with pytest.raises(UnverifiedProfileError):
        load_profile("f1040").require_verified()


def test_verified_profile_gate_passes() -> None:
    profile = FormProfile(
        form_id="x", title="X", template_filename="x.pdf", filing_order=1, verified=True
    )
    profile.require_verified()  # no raise


def test_unknown_profile_raises() -> None:
    with pytest.raises(FileNotFoundError):
        load_profile("f9999_nope")


def test_profile_from_dict_strips_schema_version() -> None:
    profile = profile_from_dict(
        {
            "schema_version": "1.0.0",
            "form_id": "f1040",
            "title": "T",
            "template_filename": "f1040.pdf",
            "filing_order": 1,
        }
    )
    assert profile.form_id == "f1040"


def test_profile_rejects_unknown_field() -> None:
    with pytest.raises(ValueError):
        profile_from_dict(
            {
                "form_id": "x",
                "title": "T",
                "template_filename": "x.pdf",
                "filing_order": 1,
                "surprise": 1,
            }
        )


def test_profile_is_frozen() -> None:
    profile = FormProfile(
        form_id="x", title="X", template_filename="x.pdf", filing_order=1
    )
    with pytest.raises(Exception):  # noqa: B017 - pydantic frozen raises ValidationError/TypeError
        profile.verified = True  # type: ignore[misc]
