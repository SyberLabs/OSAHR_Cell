"""GrokCell public exports, loaded only when their subsystem is requested."""
from importlib import import_module

__all__ = [
    "ConstraintVault", "GrokCellSurface", "MCP_SCHEMA_VERSION",
    "SURFACE_VERSION", "ToolRegistry", "mcp_manifest",
]
_EXPORTS = {
    "ConstraintVault": ".vault", "GrokCellSurface": ".surface",
    "MCP_SCHEMA_VERSION": ".protocol", "SURFACE_VERSION": ".protocol",
    "ToolRegistry": ".tools", "mcp_manifest": ".tools",
}


def __getattr__(name: str):
    if name not in _EXPORTS:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    value = getattr(import_module(_EXPORTS[name], __name__), name)
    globals()[name] = value
    return value


def __dir__():
    return sorted(set(globals()) | set(__all__))
