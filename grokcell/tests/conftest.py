from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
REPO = ROOT.parent
for path in (ROOT, REPO):
    text = str(path)
    if text not in sys.path:
        sys.path.insert(0, text)


@pytest.fixture(autouse=True)
def isolate_grokcell_runtime_files(tmp_path, monkeypatch):
    monkeypatch.setattr("grokcell.protocol.STATE_DIR", tmp_path / "default-state")
    monkeypatch.setattr("grokcell.protocol.FIDELITY_DIR", tmp_path / "default-fidelity")
    monkeypatch.setenv("GROKCELL_ACCEPTANCE_DIR", str(tmp_path / "acceptance"))
