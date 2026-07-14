"""telos.forms — the official-form output layer.

Takes already-computed engine line values and transcribes them into the official
IRS AcroForm PDFs, then assembles a print-and-mail package. Lives entirely
outside ``telos.engine`` (deterministic arithmetic only) and writes filled
output solely under ``TELOS_DATA_DIR``.

The one thing this layer cannot self-certify is the *semantic* field map (which
opaque AcroForm field is which line); see ``forms/README.md`` and telos-ops#10.
``FormProfile.verified`` gates any filing-grade use on that confirmation.
"""

from __future__ import annotations

from telos.forms.filler import (
    UnknownFieldError,
    fill_form,
    fill_form_bytes,
    format_field_value,
)
from telos.forms.introspect import FieldInfo, describe_fields
from telos.forms.package import FilledForm, assemble_package, package_order
from telos.forms.profile import (
    FormProfile,
    UnverifiedProfileError,
    load_profile,
    profile_from_dict,
)

__all__ = [
    "FieldInfo",
    "FilledForm",
    "FormProfile",
    "UnknownFieldError",
    "UnverifiedProfileError",
    "assemble_package",
    "describe_fields",
    "fill_form",
    "fill_form_bytes",
    "format_field_value",
    "load_profile",
    "package_order",
    "profile_from_dict",
]
