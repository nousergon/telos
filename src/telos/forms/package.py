"""Assemble filled forms into one print-and-mail package.

Concatenates the individual filled PDFs in IRS filing order (Form 1040 first,
then its schedules and attachments by ``filing_order``) into a single document
the owner can print, sign, and mail. Output lands under ``TELOS_DATA_DIR`` like
every other artifact carrying personal figures.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

from pypdf import PdfReader, PdfWriter

from telos.forms.profile import FormProfile


@dataclass(frozen=True)
class FilledForm:
    """One filled form ready to go into the package."""

    profile: FormProfile
    pdf_bytes: bytes


def assemble_package(filled: Sequence[FilledForm], output_path: Path) -> Path:
    """Concatenate ``filled`` forms in ``filing_order`` and write the package.

    Raises on an empty package (nothing to mail is a caller bug, not a valid
    empty PDF).
    """
    if not filled:
        raise ValueError("cannot assemble an empty print package")
    ordered = sorted(filled, key=lambda f: (f.profile.filing_order, f.profile.form_id))
    writer = PdfWriter()
    for item in ordered:
        writer.append(PdfReader(_as_stream(item.pdf_bytes)))
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("wb") as handle:
        writer.write(handle)
    return output_path


def package_order(filled: Sequence[FilledForm]) -> list[str]:
    """The form-id order the package would use — handy for tests and manifests."""
    ordered = sorted(filled, key=lambda f: (f.profile.filing_order, f.profile.form_id))
    return [f.profile.form_id for f in ordered]


def _as_stream(data: bytes):
    import io

    return io.BytesIO(data)
