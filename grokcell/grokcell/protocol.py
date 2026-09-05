"""Frozen GrokCell surface constants. Not confirmatory science."""
from __future__ import annotations

from pathlib import Path

PACKAGE_ROOT = Path(__file__).resolve().parent
PROJECT_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = PROJECT_ROOT.parent
RESOURCE_ROOT = PACKAGE_ROOT / "resources"
CONCEPTS_DIR = RESOURCE_ROOT / "vault" / "concepts"
WORLD_DIR = RESOURCE_ROOT / "world"
_source_vault = PROJECT_ROOT / "vault"
VAULT_DIR = (
    _source_vault
    if _source_vault.is_dir() and (PROJECT_ROOT / "pyproject.toml").is_file()
    else Path.home() / ".grokcell" / "vault"
)
CLAIMS_NOTES_DIR = VAULT_DIR / "claims"

MOUTH_OWNER = "MOUTH"
SURFACE_VERSION = "grokcell_surface_v7"
MCP_SCHEMA_VERSION = "grokcell_mcp_v6"
CONSTRUCTION_RULE_ID = "assemble-component"
ROOT_SEED = 260904
ASSEMBLE_RATE = 1.0
FIDELITY_DIR = VAULT_DIR / "fidelity"
STATE_DIR = VAULT_DIR / "state"
SUITE_BY_COMPONENT = {
    "core.api": Path("suites") / "core_api",
    "app.ui": Path("suites") / "app_ui",
    "failing.example": Path("suites") / "failing",
}
