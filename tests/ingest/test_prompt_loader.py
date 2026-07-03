"""Prompt loader tests — stub fallback, tuned override, missing-prompt error."""

from __future__ import annotations

import pytest

from telos.ingest.prompt_loader import PromptNotFoundError, load_prompt


def test_loads_example_stub_when_no_tuned_prompt():
    text = load_prompt("w2_extraction")
    assert "record_w2" in text or "transcription" in text.lower()


def test_missing_prompt_raises_actionable_error():
    with pytest.raises(PromptNotFoundError, match="TELOS_PROMPT_DIR"):
        load_prompt("does_not_exist")


def test_tuned_txt_overrides_stub(tmp_path, monkeypatch):
    (tmp_path / "w2_extraction.txt").write_text("TUNED PROMPT", encoding="utf-8")
    monkeypatch.setenv("TELOS_PROMPT_DIR", str(tmp_path))
    assert load_prompt("w2_extraction") == "TUNED PROMPT"


def test_override_dir_stub_used_when_no_tuned(tmp_path, monkeypatch):
    (tmp_path / "custom.txt.example").write_text("STUB", encoding="utf-8")
    monkeypatch.setenv("TELOS_PROMPT_DIR", str(tmp_path))
    assert load_prompt("custom") == "STUB"
