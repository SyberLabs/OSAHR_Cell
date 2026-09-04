from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REPO = ROOT.parent
for path in (ROOT, REPO):
    text = str(path)
    if text not in sys.path:
        sys.path.insert(0, text)
