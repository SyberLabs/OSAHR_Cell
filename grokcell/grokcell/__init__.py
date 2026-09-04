"""Autonomous GrokCell surface. Descendant of OSAHR 0.2. Not the kernel."""

from .protocol import MCP_SCHEMA_VERSION, SURFACE_VERSION
from .surface import GrokCellSurface
from .tools import ToolRegistry, mcp_manifest
from .vault import ConstraintVault

__all__ = [
    "ConstraintVault",
    "GrokCellSurface",
    "MCP_SCHEMA_VERSION",
    "SURFACE_VERSION",
    "ToolRegistry",
    "mcp_manifest",
]
