"""Tests that v1 Brain is a deterministic park controller."""
from __future__ import annotations

from pathlib import Path

from osahr_cell.brain import assert_no_llm_import
from osahr_cell.protocol import BRAIN_VERSION


def test_brain_version_is_deterministic_v1():
    assert BRAIN_VERSION == "osahr06_brain_v1_deterministic"
    source = (Path(__file__).resolve().parents[1] / "osahr_cell" / "brain.py").read_text(
        encoding="utf-8"
    )
    assert_no_llm_import(source)
    assert "def decide(" in source
