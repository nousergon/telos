"""Form profiles: the data that maps engine line values onto AcroForm fields.

A ``FormProfile`` is committed YAML (public, no personal data) describing one
official form:

- ``template_filename`` — the blank PDF in ``forms/templates/``.
- ``field_map`` — ``{semantic_key: acroform_field_name}``. The semantic keys are
  the engine's own line labels (``Form1040Result.lines`` is keyed ``"1a"``,
  ``"2b"``, ``"16"`` …); the values are the opaque AcroForm field names in the
  PDF (``topmostSubform[0].Page1[0].f1_11[0]`` …).
- ``checkbox_map`` — ``{semantic_key: acroform_field_name}`` for on/off fields
  (filing status, boxes) kept separate because they set ``/V`` to the widget's
  on-state, not a value string.
- ``verified`` — **load-bearing.** ``field_map`` correctness cannot be proved
  from the PDF (IRS forms carry no ``/TU`` field tooltips — see
  ``forms/README.md``); a mechanical read-back test proves a value *lands* in a
  named field, never that the field is the semantically-correct box. Until the
  map is confirmed against the rendered form, ``verified`` stays ``false`` and
  callers must refuse to emit a form-for-filing from it.

The unverified-by-default posture mirrors the params contract's refusal of
uncited tax constants: a plausible-but-wrong field map is a silent, high-stakes
defect on a document mailed to the IRS, so it is never asserted without proof.
"""

from __future__ import annotations

from collections.abc import Mapping

import yaml
from pydantic import BaseModel, ConfigDict, Field

try:  # Python 3.11+: stdlib importlib.resources
    from importlib.resources import files as _pkg_files
except ImportError:  # pragma: no cover - all supported interpreters have it
    _pkg_files = None  # type: ignore[assignment]

PROFILE_SCHEMA_VERSION = "1.0.0"
_PROFILES_PACKAGE = "telos.forms.profiles"


class FormProfile(BaseModel):
    """Declarative description of one official form's fill mapping."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    form_id: str = Field(description="stable id, e.g. 'f1040' (matches the YAML stem)")
    title: str = Field(description="human name, e.g. 'Form 1040 (2024)'")
    template_filename: str = Field(description="blank PDF under forms/templates/")
    filing_order: int = Field(
        description="assembly order in the print package (1040 first, then schedules)"
    )
    field_map: Mapping[str, str] = Field(
        default_factory=dict,
        description="{engine line key: AcroForm text-field name}",
    )
    checkbox_map: Mapping[str, str] = Field(
        default_factory=dict,
        description="{semantic key: AcroForm checkbox/radio field name}",
    )
    verified: bool = Field(
        default=False,
        description="True only once field_map is confirmed against the rendered form",
    )
    provenance: str = Field(
        default="",
        description="how the map was established / verified (or why it is not yet)",
    )

    def require_verified(self) -> None:
        """Raise unless the map has been confirmed — the guard before filing output."""
        if not self.verified:
            raise UnverifiedProfileError(
                f"form profile {self.form_id!r} is not verified: {self.provenance or 'no map yet'}"
            )


class UnverifiedProfileError(RuntimeError):
    """Raised when an unverified profile is used where a filing-grade fill is required."""


def profile_from_dict(data: Mapping[str, object]) -> FormProfile:
    """Build a profile from an already-parsed mapping (schema-version tolerant)."""
    payload = dict(data)
    payload.pop("schema_version", None)  # advisory; not part of the model
    return FormProfile.model_validate(payload)


def load_profile(form_id: str) -> FormProfile:
    """Load a committed profile by id from the ``telos.forms.profiles`` package."""
    if _pkg_files is None:  # pragma: no cover
        raise RuntimeError("importlib.resources.files unavailable")
    resource = _pkg_files(_PROFILES_PACKAGE).joinpath(f"{form_id}.yaml")
    if not resource.is_file():
        raise FileNotFoundError(f"no form profile named {form_id!r}")
    data = yaml.safe_load(resource.read_text(encoding="utf-8")) or {}
    profile = profile_from_dict(data)
    if profile.form_id != form_id:
        raise ValueError(
            f"profile form_id {profile.form_id!r} does not match filename {form_id!r}"
        )
    return profile
