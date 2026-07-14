"""Path seams: templates in-tree, filled output only under TELOS_DATA_DIR."""

from __future__ import annotations

from pathlib import Path

import pytest

from telos.forms import paths


def test_output_dir_requires_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("TELOS_DATA_DIR", raising=False)
    with pytest.raises(RuntimeError):
        paths.output_dir()


def test_resolve_output_path_under_data_dir(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("TELOS_DATA_DIR", str(tmp_path))
    out = paths.resolve_output_path("returns/2024/f1040.pdf")
    assert out == (tmp_path / "returns/2024/f1040.pdf").resolve()
    assert out.parent.is_dir()  # parents created


def test_resolve_output_rejects_absolute(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("TELOS_DATA_DIR", str(tmp_path))
    with pytest.raises(ValueError):
        paths.resolve_output_path("/etc/passwd")


def test_resolve_output_rejects_escape(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("TELOS_DATA_DIR", str(tmp_path))
    with pytest.raises(ValueError):
        paths.resolve_output_path("../../../etc/passwd")


def test_templates_dir_env_override(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("TELOS_FORMS_DIR", str(tmp_path))
    assert paths.templates_dir() == tmp_path / "templates"


def test_template_path_finds_committed_f1040() -> None:
    # No env override -> project-root forms/templates/f1040.pdf must resolve.
    path = paths.template_path("f1040.pdf")
    assert path.is_file()
    assert path.name == "f1040.pdf"


def test_template_path_missing_raises(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    (tmp_path / "templates").mkdir()
    monkeypatch.setenv("TELOS_FORMS_DIR", str(tmp_path))
    with pytest.raises(FileNotFoundError):
        paths.template_path("nope.pdf")


def test_template_path_rejects_escape(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    (tmp_path / "templates").mkdir()
    monkeypatch.setenv("TELOS_FORMS_DIR", str(tmp_path))
    with pytest.raises(ValueError):
        paths.template_path("../secret.pdf")
