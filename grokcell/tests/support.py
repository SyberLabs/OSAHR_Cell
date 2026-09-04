from __future__ import annotations

from pathlib import Path

from grokcell.fidelity import FidelityStore
from grokcell.runner import run_component
from grokcell.surface import GrokCellSurface


def scored_surface(*names: str, root: Path) -> GrokCellSurface:
    store = FidelityStore(root)
    for name in names:
        record = run_component(name, store=store)
        if not record.passed:
            raise AssertionError(f"runner failed for {name}: exit {record.exit_code}")
    return GrokCellSurface.open(fidelity=store, state=root / "state")
