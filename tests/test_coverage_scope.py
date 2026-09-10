"""The coverage gate's *scope* is asserted here, not only its number.

repository-baseline-policy.md §4.2 C5: the way a coverage gate stops being
honest is by narrowing what it measures rather than by lowering the number —
which reads as an improvement in every report. Measured on symposion, removing
one flag moved the reported figure from 34.76% to 92.36% with no new test
code.

So these tests assert what a passing suite cannot otherwise notice:

* the measured source is the WHOLE ``telos`` package (C1), never a path or
  submodule narrower than that;
* the floor is enforced by a non-zero exit (C2) and is a ratchet that may be
  raised and never lowered (C3);
* no coverage `omit` beyond a pinned, empty, justified list — telos currently
  omits nothing;
* every source module under ``src/telos`` is inside the measured package.
"""

from __future__ import annotations

import tomllib
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
PYPROJECT = REPO_ROOT / "pyproject.toml"
PACKAGE_ROOT = REPO_ROOT / "src" / "telos"

#: The floor may be RAISED here as coverage improves. Lowering it is a policy
#: amendment (repository-baseline-policy.md §4.2 C3), not a code change.
MINIMUM_FLOOR = 98

#: No source is currently omitted from measurement. Widening this set is a
#: scope decision, not a drive-by coverage bump — update this list alongside
#: an [tool.coverage.run] comment justifying each entry if it ever grows.
EXPECTED_OMIT: set[str] = set()


def _pyproject() -> dict:
    return tomllib.loads(PYPROJECT.read_text(encoding="utf-8"))


def test_coverage_source_is_the_whole_package() -> None:
    """C1 — ``source`` names the package root, so unimported modules still count."""
    sources = _pyproject()["tool"]["coverage"]["run"]["source"]
    assert sources == ["telos"], (
        f"coverage source must be exactly the telos package, got {sources!r}. "
        "Narrowing it to a submodule or a path measures the tested subset and "
        "reports it as the repository."
    )


def test_coverage_floor_is_enforced_and_never_lowered() -> None:
    """C2 + C3 — the gate exits non-zero below a floor that only ratchets up."""
    fail_under = _pyproject()["tool"]["coverage"]["report"]["fail_under"]
    assert isinstance(fail_under, int), (
        f"fail_under must be a single integer floor, got {fail_under!r}"
    )
    assert fail_under >= MINIMUM_FLOOR, (
        f"coverage floor {fail_under} is below the ratchet {MINIMUM_FLOOR}. "
        "A floor is raised as coverage improves and never lowered to make a "
        "change pass (repository-baseline-policy.md §4.2 C3)."
    )


def test_coverage_omit_matches_the_pinned_justified_set() -> None:
    """A shrunk denominator is a narrowing this test forces into review."""
    omit = set(_pyproject()["tool"]["coverage"]["run"].get("omit", []))
    added = omit - EXPECTED_OMIT
    assert not added, (
        f"coverage omit gained unreviewed entries: {sorted(added)}. "
        "Each omitted path removes files from the denominator, raising the "
        "reported figure without adding a test — update EXPECTED_OMIT here "
        "alongside a justification comment in pyproject.toml if this is "
        "deliberate."
    )


def test_every_source_module_is_inside_the_measured_package() -> None:
    """No source file lives outside what ``--cov=telos`` measures."""
    src = REPO_ROOT / "src"
    stray = sorted(
        p.relative_to(REPO_ROOT).as_posix()
        for p in src.rglob("*.py")
        if PACKAGE_ROOT not in p.parents and p != PACKAGE_ROOT
    )
    assert not stray, (
        f"source modules outside the measured package are invisible to the "
        f"coverage gate: {stray}"
    )


def test_no_cov_fail_under_flag_shadows_the_pyproject_gate() -> None:
    """A CI-passed --cov-fail-under could silently override pyproject.toml's."""
    import re

    for workflow in (REPO_ROOT / ".github" / "workflows").glob("*.yml"):
        text = workflow.read_text(encoding="utf-8")
        for match in re.findall(r"--cov-fail-under=(\d+)", text):
            assert int(match) >= MINIMUM_FLOOR, (
                f"{workflow.name} passes --cov-fail-under={match} directly, "
                "bypassing the pyproject.toml ratchet this test protects."
            )
