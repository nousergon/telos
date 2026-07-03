"""Runtime prompt loader — public stubs vs. private tuned prompts.

``telos`` is a PUBLIC AGPL repository. The tuned production extraction prompts
are proprietary and live in the private ``telos-ops`` repo; committing them
here would leak them at the AGPL flip. So this package ships only ``*.txt.example``
stub prompts (safe to publish) and gitignores the real ``*.txt`` files.

At runtime :func:`load_prompt` prefers the tuned ``<name>.txt`` if present and
falls back to the committed ``<name>.txt.example`` otherwise — never silently
running with *no* prompt. An override directory (``TELOS_PROMPT_DIR`` env var,
where the private prompts are deployed) takes precedence over the package dir.
"""

from __future__ import annotations

import os
from pathlib import Path

_PROMPT_DIR = Path(__file__).parent / "prompts"


class PromptNotFoundError(FileNotFoundError):
    """Neither a tuned ``<name>.txt`` nor a stub ``<name>.txt.example`` exists."""


def _candidate_dirs() -> list[Path]:
    dirs: list[Path] = []
    override = os.environ.get("TELOS_PROMPT_DIR")
    if override:
        dirs.append(Path(override))
    dirs.append(_PROMPT_DIR)
    return dirs


def load_prompt(name: str) -> str:
    """Return the tuned prompt ``<name>.txt`` if present, else the ``.example`` stub.

    Search order per directory (override dir first, then the package ``prompts/``
    dir): the tuned ``<name>.txt`` wins over the ``<name>.txt.example`` stub.

    Raises :class:`PromptNotFoundError` with an actionable message if nothing is
    found — a missing prompt is a hard failure, never a silent empty string.
    """
    tried: list[str] = []
    for directory in _candidate_dirs():
        tuned = directory / f"{name}.txt"
        stub = directory / f"{name}.txt.example"
        for path in (tuned, stub):
            tried.append(str(path))
            if path.is_file():
                return path.read_text(encoding="utf-8")
    raise PromptNotFoundError(
        f"no prompt for {name!r}; looked for (in order): {tried}. "
        "Deploy the tuned '<name>.txt' from telos-ops, or set TELOS_PROMPT_DIR."
    )
