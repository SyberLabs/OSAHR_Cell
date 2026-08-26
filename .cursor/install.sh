#!/usr/bin/env bash
# Idempotent development-environment bootstrap for the OSAHR project.
#
# Layers:
#   1. system: ensure python venv support is available (the base image ships
#      python3.12 but not the ensurepip/venv module).
#   2. repository: create a shared virtualenv and install the dependency-free
#      core `osahr` kernel plus the scientific stack the research experiments
#      need (numpy/pandas/scipy and a CPU build of torch).
#
# Safe to run repeatedly: the venv is reused, apt is a no-op once installed,
# and pip installs converge.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

VENV_DIR="$REPO_ROOT/.venv"
PY=python3

# --- 1. system dependency: python venv support ---------------------------
if ! "$PY" -m venv --help >/dev/null 2>&1 || ! "$PY" -c "import ensurepip" >/dev/null 2>&1; then
  echo "[install] installing python venv support via apt"
  PY_VER="$("$PY" -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')"
  sudo apt-get update -qq
  sudo apt-get install -y --no-install-recommends "python${PY_VER}-venv"
fi

# --- 2. shared virtualenv ------------------------------------------------
if [ ! -x "$VENV_DIR/bin/python" ]; then
  echo "[install] creating virtualenv at $VENV_DIR"
  "$PY" -m venv "$VENV_DIR"
fi

# shellcheck disable=SC1091
source "$VENV_DIR/bin/activate"

python -m pip install --upgrade pip

# --- core kernel (editable, dependency-free) + test runner ---------------
echo "[install] installing core osahr kernel (editable) + pytest"
python -m pip install -e .
python -m pip install pytest

# --- scientific stack for the liquid-OSAHR / 6G experiments --------------
# torch is installed from the CPU wheel index to avoid pulling large CUDA
# packages; the experiments run on CPU in this environment.
echo "[install] installing scientific stack (numpy, pandas, scipy)"
python -m pip install "numpy>=2.0" "pandas>=2.0" "scipy>=1.12"

echo "[install] installing CPU build of torch"
python -m pip install torch --index-url https://download.pytorch.org/whl/cpu

echo "[install] done. Activate with: source .venv/bin/activate"
