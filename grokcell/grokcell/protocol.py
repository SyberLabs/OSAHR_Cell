"""Frozen GrokCell surface constants. Not confirmatory science."""
from __future__ import annotations

from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = PROJECT_ROOT.parent
CONCEPTS_DIR = PROJECT_ROOT / "vault" / "concepts"
CLAIMS_NOTES_DIR = PROJECT_ROOT / "vault" / "claims"

MOUTH_OWNER = "MOUTH"
SURFACE_VERSION = "grokcell_surface_v1"
MCP_SCHEMA_VERSION = "grokcell_mcp_v1"
CONSTRUCTION_RULE_ID = "assemble-component"
ROOT_SEED = 260904
ASSEMBLE_RATE = 1.0
