"""Frozen GrokCell surface constants. Not confirmatory science."""
from __future__ import annotations

from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = PROJECT_ROOT.parent
CONCEPTS_DIR = PROJECT_ROOT / "vault" / "concepts"
CLAIMS_NOTES_DIR = PROJECT_ROOT / "vault" / "claims"

MOUTH_OWNER = "MOUTH"
SURFACE_VERSION = "grokcell_surface_v6"
MCP_SCHEMA_VERSION = "grokcell_mcp_v6"
CONSTRUCTION_RULE_ID = "assemble-component"
ROOT_SEED = 260904
ASSEMBLE_RATE = 1.0
FIDELITY_DIR = PROJECT_ROOT / "vault" / "fidelity"
STATE_DIR = PROJECT_ROOT / "vault" / "state"
SUITE_BY_COMPONENT = {
    "core.api": Path("world") / "suites" / "core_api",
    "app.ui": Path("world") / "suites" / "app_ui",
    "failing.example": Path("world") / "suites" / "failing",
}
