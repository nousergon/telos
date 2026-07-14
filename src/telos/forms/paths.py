"""Filesystem seams for the form-fill output layer.

Two roots, deliberately distinct:

- **Templates** (``forms/templates/``, at the project root) are *public-domain
  blank IRS PDFs* committed to the repo (the ``.gitignore`` excepts them). They
  are read-only inputs.
- **Filled output** goes ONLY under ``TELOS_DATA_DIR`` — it embeds personal tax
  figures and must never land in any repo (the same rule the planning scenarios
  follow). ``resolve_output_path`` refuses to write anywhere else.

No clock, no network — pure path resolution, so the output layer inherits the
engine's replay property.
"""

from __future__ import annotations

import os
from pathlib import Path

_TEMPLATES_ENV = "TELOS_FORMS_DIR"
_DATA_ENV = "TELOS_DATA_DIR"


def _project_root() -> Path:
    """Walk up from this file to the repo/checkout root (the dir with ``pyproject.toml``)."""
    here = Path(__file__).resolve()
    for parent in here.parents:
        if (parent / "pyproject.toml").is_file():
            return parent
    # Installed as a wheel with no source tree: no project root to find.
    raise FileNotFoundError(
        "could not locate the telos project root (no pyproject.toml above "
        f"{here}); set {_TEMPLATES_ENV} to the directory holding the blank "
        "IRS templates"
    )


def templates_dir() -> Path:
    """Directory holding the blank IRS template PDFs.

    ``TELOS_FORMS_DIR`` overrides (points at ``forms/``); otherwise the
    project-root ``forms/`` directory is used. Blank templates live in the
    ``templates/`` subdirectory of whichever root is chosen.
    """
    override = os.environ.get(_TEMPLATES_ENV)
    root = Path(override).expanduser() if override else _project_root() / "forms"
    return root / "templates"


def template_path(filename: str) -> Path:
    """Absolute path to a committed blank template, validated to exist and stay in-tree."""
    base = templates_dir().resolve()
    candidate = (base / filename).resolve()
    if base not in candidate.parents:
        raise ValueError(f"template filename escapes the templates dir: {filename!r}")
    if not candidate.is_file():
        raise FileNotFoundError(f"blank template not found: {candidate}")
    return candidate


def output_dir() -> Path:
    """The ``TELOS_DATA_DIR`` root for filled (personal) output. Must be configured."""
    raw = os.environ.get(_DATA_ENV)
    if not raw:
        raise RuntimeError(
            f"{_DATA_ENV} is not set — filled forms carry personal tax data and "
            "must be written there, never inside a repo"
        )
    return Path(raw).expanduser()


def resolve_output_path(relative: str) -> Path:
    """Resolve a filled-output path under ``TELOS_DATA_DIR``, creating parent dirs.

    ``relative`` must stay inside ``TELOS_DATA_DIR`` (no ``..`` escape) and must
    be a filename or sub-path, not absolute.
    """
    rel = Path(relative)
    if rel.is_absolute():
        raise ValueError(f"output path must be relative to TELOS_DATA_DIR, got {relative!r}")
    base = output_dir().resolve()
    target = (base / rel).resolve()
    if base != target and base not in target.parents:
        raise ValueError(f"output path escapes TELOS_DATA_DIR: {relative!r}")
    target.parent.mkdir(parents=True, exist_ok=True)
    return target
