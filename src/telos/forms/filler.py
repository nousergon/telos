"""Fill an official IRS AcroForm PDF from engine line values.

Pure output-layer plumbing — it lives outside ``src/telos/engine/`` on purpose
and imports nothing from it: the engine computes traced line values; this layer
only transcribes already-computed numbers into the official boxes.

Three robustness properties that make it correct on *real* IRS forms rather than
just on toy fixtures:

1. **Unknown-field guard.** Every AcroForm name a profile maps to must exist in
   the template; otherwise the fill silently no-ops and a value never reaches the
   IRS. A mapped-but-absent field raises instead.
2. **XFA drop.** IRS 1040-family PDFs are *hybrid* AcroForm+XFA forms; Adobe
   renders the XFA layer and can ignore AcroForm ``/V`` values, so a naive fill
   looks blank when opened. Dropping ``/XFA`` makes every viewer fall back to the
   AcroForm values we set (this is the standard fix for gov hybrid forms).
3. **NeedAppearances.** Set so viewers regenerate the value appearance streams.

Formatting is deliberately thin: the engine already rounds (``engine/rounding``),
so a ``Decimal`` is rendered exactly (whole dollars with no point, cents with
two places) and any ``str`` passes through untouched.
"""

from __future__ import annotations

import io
from collections.abc import Mapping
from decimal import Decimal
from pathlib import Path

from pypdf import PdfReader, PdfWriter
from pypdf.generic import NameObject

from telos.forms.profile import FormProfile


class UnknownFieldError(KeyError):
    """A profile maps a semantic key to an AcroForm field absent from the template."""


def format_field_value(value: object) -> str:
    """Render a line value for an AcroForm text field without lossy reformatting."""
    if isinstance(value, str):
        return value
    if isinstance(value, Decimal):
        # Whole dollars -> "1234"; fractional -> "1234.56". No thousands
        # separators (IRS boxes are plain numeric) and no exponent form.
        if value == value.to_integral_value():
            return str(value.quantize(Decimal(1)))
        return f"{value:.2f}"
    if isinstance(value, bool):  # guard: bools are ints, keep them out of numeric path
        raise TypeError("use checkbox_map for boolean fields, not a text value")
    if isinstance(value, int):
        return str(value)
    raise TypeError(f"unsupported field value type: {type(value).__name__}")


def _acroform_field_names(reader: PdfReader) -> set[str]:
    fields = reader.get_fields()
    return set(fields.keys()) if fields else set()


def fill_form_bytes(
    template: Path,
    field_values: Mapping[str, object],
    profile: FormProfile,
    checkbox_values: Mapping[str, str] | None = None,
) -> bytes:
    """Fill ``template`` per ``profile`` and return the filled PDF as bytes.

    ``field_values`` is keyed by the engine's semantic line keys; only keys the
    profile knows about (present in ``field_map``) are written. ``checkbox_values``
    maps a semantic key to the AcroForm on-state name for that widget.
    """
    reader = PdfReader(str(template))
    available = _acroform_field_names(reader)

    text_targets: dict[str, str] = {}
    for key, value in field_values.items():
        acro = profile.field_map.get(key)
        if acro is None:
            continue  # value the engine produced but this form doesn't carry
        if acro not in available:
            raise UnknownFieldError(
                f"profile {profile.form_id!r} maps {key!r} -> {acro!r}, absent from "
                f"{template.name}"
            )
        text_targets[acro] = format_field_value(value)

    checkbox_targets: dict[str, str] = {}
    for key, on_state in (checkbox_values or {}).items():
        acro = profile.checkbox_map.get(key)
        if acro is None:
            raise UnknownFieldError(
                f"profile {profile.form_id!r} has no checkbox mapping for {key!r}"
            )
        if acro not in available:
            raise UnknownFieldError(
                f"profile {profile.form_id!r} maps checkbox {key!r} -> {acro!r}, absent "
                f"from {template.name}"
            )
        checkbox_targets[acro] = on_state

    writer = PdfWriter()
    writer.append(reader)
    _drop_xfa(writer)

    updates: dict[str, object] = dict(text_targets)
    for acro, on_state in checkbox_targets.items():
        updates[acro] = NameObject(on_state if on_state.startswith("/") else f"/{on_state}")
    if updates:
        for page in writer.pages:
            writer.update_page_form_field_values(page, updates, auto_regenerate=False)
    _set_need_appearances(writer)

    buffer = io.BytesIO()
    writer.write(buffer)
    return buffer.getvalue()


def fill_form(
    template: Path,
    field_values: Mapping[str, object],
    profile: FormProfile,
    output_path: Path,
    checkbox_values: Mapping[str, str] | None = None,
) -> Path:
    """Fill and write to ``output_path`` (caller resolves it under TELOS_DATA_DIR)."""
    data = fill_form_bytes(template, field_values, profile, checkbox_values)
    output_path.write_bytes(data)
    return output_path


def _drop_xfa(writer: PdfWriter) -> None:
    """Remove the XFA layer so viewers render the AcroForm values we set."""
    root = writer._root_object
    acro = root.get("/AcroForm")
    if acro is None:
        return
    acro = acro.get_object()
    if "/XFA" in acro:
        del acro[NameObject("/XFA")]


def _set_need_appearances(writer: PdfWriter) -> None:
    try:
        writer.set_need_appearances_writer(True)
    except AttributeError:  # pragma: no cover - older pypdf fallback
        from pypdf.generic import BooleanObject

        root = writer._root_object
        acro = root.get("/AcroForm")
        if acro is not None:
            acro.get_object()[NameObject("/NeedAppearances")] = BooleanObject(True)
