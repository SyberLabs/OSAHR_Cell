import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REPO = ROOT.parent
EXP05 = REPO / "liquid-osahr-experiment-05"
for path in (ROOT, REPO, EXP05):
    text = str(path)
    if text not in sys.path:
        sys.path.insert(0, text)
