"""MCP tool ports: recon, not routing. park.request_rewrite never bypasses DPO."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

from osahr.runtime import Runtime

from .anlf import AbnormalBehavior, LoadLevel, load_handle, outage_handle
from .claims_bridge import ClaimStatus, InterventionClaim, score_semantic_contrast
from .junction import is_junction, match_vault_legal
from .protocol import MCP_SCHEMA_VERSION
from .vault import SemanticVault

TOOL_SCHEMAS: dict[str, dict[str, Any]] = {
    "vault.query": {
        "name": "vault.query",
        "description": "Read a PKG concept. Dual projection; no SPARQL.",
        "inputSchema": {
            "type": "object",
            "properties": {"concept_id": {"type": "string"}},
            "required": ["concept_id"],
        },
    },
    "anlf.load": {
        "name": "anlf.load",
        "description": "LoadLevel AnLF over a KPM series. Boundary payload only.",
        "inputSchema": {
            "type": "object",
            "properties": {"series": {"type": "array", "items": {"type": "number"}}},
            "required": ["series"],
        },
    },
    "anlf.outage": {
        "name": "anlf.outage",
        "description": "AbnormalBehavior AnLF. Boundary payload only.",
        "inputSchema": {
            "type": "object",
            "properties": {"series": {"type": "array", "items": {"type": "number"}}},
            "required": ["series"],
        },
    },
    "twin.inspect": {
        "name": "twin.inspect",
        "description": "Read-only twin snapshot: time, hash, enabled junction matches.",
        "inputSchema": {"type": "object", "properties": {}},
    },
    "claims.score": {
        "name": "claims.score",
        "description": "Experiment 05 claim grammar. Recon only; does not elect alpha.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "oracle_effect": {"type": "number"},
                "effects_by_alpha": {"type": "object"},
                "scenario": {"type": "integer"},
                "regime": {"type": "string"},
                "horizon": {"type": "number"},
                "eps": {"type": "number"},
                "activation": {
                    "type": "object",
                    "properties": {
                        "events": {"type": "number"},
                        "outages": {"type": "number"},
                        "handovers": {"type": "number"},
                        "reroutes": {"type": "number"},
                    },
                    "required": ["events", "outages", "handovers", "reroutes"],
                },
            },
            "required": [
                "oracle_effect",
                "effects_by_alpha",
                "scenario",
                "regime",
                "horizon",
                "activation",
            ],
        },
    },
    "park.request_rewrite": {
        "name": "park.request_rewrite",
        "description": (
            "Request a legal route-task rewrite. Refused unless claim status is "
            "hold_unresolved, the occurrence is currently matched, and the pair "
            "is vault-legal. The kernel still validates DPO; this tool does not "
            "call RewriteEngine."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "status": {
                    "type": "string",
                    "enum": ["admit", "hold_unresolved", "reject", "outcome_unknown"],
                },
                "match_id": {"type": "string"},
                "rule_id": {"type": "string"},
                "outage": {"type": "boolean"},
            },
            "required": ["status", "match_id"],
        },
    },
}


@dataclass(frozen=True)
class ParkResult:
    decision: str
    reason: str
    match_id: str | None = None
    rule_id: str | None = None

    def to_json(self) -> dict[str, Any]:
        return {
            "decision": self.decision,
            "reason": self.reason,
            "match_id": self.match_id,
            "rule_id": self.rule_id,
            "bypasses_dpo": False,
        }


class ToolRegistry:
    def __init__(
        self,
        vault: SemanticVault,
        *,
        runtime: Runtime | None = None,
        load_model: LoadLevel | None = None,
        outage_model: AbnormalBehavior | None = None,
    ) -> None:
        self.vault = vault
        self.runtime = runtime
        self.load_model = load_model or LoadLevel()
        self.outage_model = outage_model or AbnormalBehavior()
        self.handlers: dict[str, Callable[[dict[str, Any]], dict[str, Any]]] = {
            "vault.query": self._vault_query,
            "anlf.load": self._anlf_load,
            "anlf.outage": self._anlf_outage,
            "twin.inspect": self._twin_inspect,
            "claims.score": self._claims_score,
            "park.request_rewrite": self._park_request,
        }

    @property
    def schemas(self) -> list[dict[str, Any]]:
        return [TOOL_SCHEMAS[name] for name in sorted(TOOL_SCHEMAS)]

    def call(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        if name not in self.handlers:
            raise KeyError(name)
        return self.handlers[name](arguments)

    def _vault_query(self, arguments: dict[str, Any]) -> dict[str, Any]:
        return self.vault.query(str(arguments["concept_id"]))

    def _anlf_load(self, arguments: dict[str, Any]) -> dict[str, Any]:
        payload = self.load_model.infer(arguments["series"])
        self.load_model.validate(load_handle(), payload)
        return {"payload": payload, "version": self.load_model.version}

    def _anlf_outage(self, arguments: dict[str, Any]) -> dict[str, Any]:
        payload = self.outage_model.infer(arguments["series"])
        self.outage_model.validate(outage_handle(), payload)
        return {"payload": payload, "version": self.outage_model.version}

    def _twin_inspect(self, arguments: dict[str, Any]) -> dict[str, Any]:
        if self.runtime is None:
            return {"available": False}
        junctions = [
            {
                "rule_id": item.rule.rule_id,
                "match_id": item.match.match_id,
                "bindings": {
                    key: item.match.bindings[key]
                    for key in ("task_kind", "edge_name", "load", "capacity")
                    if key in item.match.bindings
                },
            }
            for item in self.runtime.enabled_occurrences()
            if is_junction(item.rule.rule_id)
        ]
        return {
            "available": True,
            "time": self.runtime.time,
            "state_hash": self.runtime.state_hash,
            "junctions": junctions,
        }

    def _claims_score(self, arguments: dict[str, Any]) -> dict[str, Any]:
        from .claims_bridge import ActivationCounts

        raw = arguments["effects_by_alpha"]
        effects = {float(k): float(v) for k, v in raw.items()}
        act = arguments["activation"]
        claim: InterventionClaim = score_semantic_contrast(
            oracle_effect=float(arguments["oracle_effect"]),
            effects_by_alpha=effects,
            activation=ActivationCounts(
                act["events"], act["outages"], act["handovers"], act["reroutes"]
            ),
            scenario=int(arguments["scenario"]),
            regime=str(arguments["regime"]),
            horizon=float(arguments["horizon"]),
            eps=float(arguments.get("eps", 0.0)),
        )
        return claim.to_json()

    def _park_request(self, arguments: dict[str, Any]) -> dict[str, Any]:
        status: ClaimStatus = arguments["status"]
        match_id = str(arguments["match_id"])
        rule_id = str(arguments.get("rule_id") or "route-task")
        outage = bool(arguments.get("outage", False))
        result = request_rewrite(
            status=status,
            match_id=match_id,
            rule_id=rule_id,
            vault=self.vault,
            runtime=self.runtime,
            outage=outage,
        )
        return result.to_json()


def request_rewrite(
    *,
    status: ClaimStatus,
    match_id: str,
    rule_id: str,
    vault: SemanticVault,
    runtime: Runtime | None,
    outage: bool,
) -> ParkResult:
    if status != "hold_unresolved":
        return ParkResult(
            "refused",
            f"claim status {status!r} does not license Brain rewrite",
            match_id=match_id,
            rule_id=rule_id,
        )
    if runtime is None:
        return ParkResult("refused", "no twin runtime bound", match_id=match_id, rule_id=rule_id)
    current = [
        item
        for item in runtime.enabled_occurrences()
        if item.rule.rule_id == rule_id and item.match.match_id == match_id
    ]
    if not current:
        return ParkResult(
            "refused",
            "occurrence is not currently matched",
            match_id=match_id,
            rule_id=rule_id,
        )
    occurrence = current[0]
    if not match_vault_legal(
        occurrence.match, vault, outage=outage, rule_id=occurrence.rule.rule_id
    ):
        return ParkResult(
            "refused",
            "requested occurrence is not vault-legal",
            match_id=match_id,
            rule_id=rule_id,
        )
    return ParkResult(
        "accepted",
        "request recorded; kernel must validate DPO before commit",
        match_id=match_id,
        rule_id=rule_id,
    )


def mcp_manifest() -> dict[str, Any]:
    return {
        "schema_version": MCP_SCHEMA_VERSION,
        "tools": list(TOOL_SCHEMAS.values()),
        "notes": "Tools are control-plane ports. They are not radio links and not occurrence types.",
    }
