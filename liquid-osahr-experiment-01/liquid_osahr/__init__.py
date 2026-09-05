"""Liquid-OSAHR Experiment 01: liquid neural point-process hazards for OSAHR."""

from __future__ import annotations

import sys
from pathlib import Path

_here = Path(__file__).resolve().parent
for _parent in (_here, *_here.parents):
    if (_parent / "osahr" / "__init__.py").exists():
        _root = str(_parent)
        if _root not in sys.path:
            sys.path.insert(0, _root)
        break

__version__ = "0.1.0-exp01"
