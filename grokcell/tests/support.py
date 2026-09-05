from __future__ import annotations

import hashlib
from pathlib import Path

from grokcell.fidelity import FidelityStore
from grokcell.runner import run_component
from grokcell.surface import GrokCellSurface


PING_ACCEPTANCE = "from service import ping\n\ndef test_operator_contract():\n    assert ping() == 'pong'\n"


def register_acceptance(root: Path, name: str, tests: str = PING_ACCEPTANCE) -> Path:
    directory = root / "acceptance" / name
    directory.mkdir(parents=True, exist_ok=True)
    raw = tests.encode("utf-8")
    (directory / "test_acceptance.py").write_bytes(raw)
    (directory / "test_acceptance.sha256").write_text(
        hashlib.sha256(raw).hexdigest() + "\n", encoding="ascii",
    )
    return directory


def scored_surface(*names: str, root: Path) -> GrokCellSurface:
    store = FidelityStore(root)
    for name in names:
        record = run_component(name, store=store)
        if not record.passed:
            raise AssertionError(f"runner failed for {name}: exit {record.exit_code}")
    return GrokCellSurface.open(fidelity=store, state=root / "state")
