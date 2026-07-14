"""Introspect an AcroForm to build and *verify* a field map.

IRS forms carry no ``/TU`` field tooltips, so a field's semantic meaning cannot
be read from the PDF metadata (verified against ``f1040.pdf``: 229 fields, zero
tooltips). This module extracts, per field, the printed text nearest to its
widget rectangle — the line number/label the IRS prints beside the box — so a
human (or a future geometric auto-mapper) can associate ``f1_11[0]`` with, say,
line ``"1a"`` and confirm the map against the rendered form.

It emits *candidates*, never assertions: the nearest-text heuristic is a mapping
*aid*, not a source of truth. Correctness still requires human confirmation,
which is exactly why ``FormProfile.verified`` defaults to ``False``.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from pypdf import PdfReader


@dataclass(frozen=True)
class FieldInfo:
    """One AcroForm field and the printed text nearest its widget."""

    name: str
    field_type: str
    page_index: int
    rect: tuple[float, float, float, float]
    nearest_text: str


def _qualified_name(widget) -> str | None:
    """Fully-qualified field name (``parent.child…``), matching ``get_fields`` keys.

    A widget's ``/T`` is only its partial name; the name the fill layer needs is
    the parent chain joined by ``.`` (``topmostSubform[0].Page1[0].f1_01[0]``).
    A widget with no ``/T`` of its own (the field object *is* the widget) inherits
    from its parent chain.
    """
    parts: list[str] = []
    node = widget
    depth = 0
    while node is not None and depth < 32:
        obj = node.get_object()
        t = obj.get("/T")
        if t is not None:
            parts.append(str(t))
        node = obj.get("/Parent")
        depth += 1
    if not parts:
        return None
    return ".".join(reversed(parts))


def _rect_tuple(obj) -> tuple[float, float, float, float]:
    r = obj.get("/Rect")
    if not r or len(r) != 4:
        return (0.0, 0.0, 0.0, 0.0)
    return tuple(float(x) for x in r)  # type: ignore[return-value]


def _nearest_label(page, rect: tuple[float, float, float, float]) -> str:
    """The visible text whose extraction position is closest to ``rect``'s left edge.

    Uses pypdf's ``extract_text`` visitor to collect (text, x, y) tuples, then
    picks the fragment nearest the field's mid-left — where IRS line labels sit.
    """
    fx, fy = rect[0], (rect[1] + rect[3]) / 2.0
    fragments: list[tuple[str, float, float]] = []

    def visitor(text: str, cm, tm, font_dict, font_size) -> None:
        stripped = text.strip()
        if stripped:
            fragments.append((stripped, float(tm[4]), float(tm[5])))

    try:
        page.extract_text(visitor_text=visitor)
    except Exception:  # pragma: no cover - defensive: a page with no text stream
        return ""
    best = ""
    best_d = float("inf")
    for txt, x, y in fragments:
        if x > fx + 2:  # labels sit to the left of / at the box, not to its right
            continue
        d = abs(x - fx) + abs(y - fy)
        if d < best_d:
            best_d, best = d, txt
    return best


def describe_fields(template: Path) -> list[FieldInfo]:
    """Enumerate every AcroForm field with page, rect, type and nearest printed label."""
    reader = PdfReader(str(template))
    fields = reader.get_fields() or {}
    type_by_name = {name: str(f.get("/FT", "")) for name, f in fields.items()}

    infos: list[FieldInfo] = []
    seen: set[str] = set()
    for page_index, page in enumerate(reader.pages):
        annots = page.get("/Annots")
        if not annots:
            continue
        for annot in annots:
            obj = annot.get_object()
            if obj.get("/Subtype") != "/Widget":
                continue
            name = _qualified_name(obj)
            if name is None:
                continue
            if name in seen:
                continue
            seen.add(name)
            rect = _rect_tuple(obj)
            infos.append(
                FieldInfo(
                    name=name,
                    field_type=type_by_name.get(name, ""),
                    page_index=page_index,
                    rect=rect,
                    nearest_text=_nearest_label(page, rect),
                )
            )
    return infos
