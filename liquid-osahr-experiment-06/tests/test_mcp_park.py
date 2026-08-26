from __future__ import annotations

from osahr_cell.brain import BrainAction, assert_no_llm_import, decide
from osahr_cell.mcp_tools import TOOL_SCHEMAS, ToolRegistry, mcp_manifest, request_rewrite
from osahr_cell.protocol import JUNCTION_RULE_ID
from osahr_cell.twin import build_stub_runtime
from osahr_cell.vault import SemanticVault


def test_mcp_tool_names():
    assert set(TOOL_SCHEMAS) == {
        "vault.query",
        "anlf.load",
        "anlf.outage",
        "twin.inspect",
        "claims.score",
        "park.request_rewrite",
    }
    manifest = mcp_manifest()
    assert manifest["schema_version"]
    assert len(manifest["tools"]) == 6


def test_admit_path_never_needs_brain():
    vault = SemanticVault.load()
    runtime = build_stub_runtime(vault)
    decision = decide("admit", runtime.enabled_occurrences(), vault, outage=False)
    assert decision.action is BrainAction.KERNEL
    park = request_rewrite(
        status="admit",
        match_id="unused",
        rule_id=JUNCTION_RULE_ID,
        vault=vault,
        runtime=runtime,
        outage=False,
    )
    assert park.decision == "refused"


def test_unknown_and_reject_cannot_commit():
    vault = SemanticVault.load()
    runtime = build_stub_runtime(vault)
    tools = ToolRegistry(vault, runtime=runtime)
    enabled = [
        item
        for item in runtime.enabled_occurrences()
        if item.rule.rule_id == JUNCTION_RULE_ID
    ]
    assert enabled
    match_id = enabled[0].match.match_id
    for status in ("outcome_unknown", "reject"):
        payload = tools.call(
            "park.request_rewrite",
            {"status": status, "match_id": match_id, "rule_id": JUNCTION_RULE_ID},
        )
        assert payload["decision"] == "refused"
        assert payload["bypasses_dpo"] is False
        decision = decide(status, runtime.enabled_occurrences(), vault, outage=False)
        assert decision.action is BrainAction.WITHHOLD


def test_hold_accepted_only_when_matched_and_vault_legal():
    vault = SemanticVault.load()
    runtime = build_stub_runtime(vault)
    before = runtime.graph.state_hash
    enabled = [
        item
        for item in runtime.enabled_occurrences()
        if item.rule.rule_id == JUNCTION_RULE_ID
    ]
    match_id = enabled[0].match.match_id
    tools = ToolRegistry(vault, runtime=runtime)
    accepted = tools.call(
        "park.request_rewrite",
        {
            "status": "hold_unresolved",
            "match_id": match_id,
            "rule_id": JUNCTION_RULE_ID,
            "outage": False,
        },
    )
    assert accepted["decision"] == "accepted"
    assert runtime.graph.state_hash == before
    missing = tools.call(
        "park.request_rewrite",
        {"status": "hold_unresolved", "match_id": "no-such-match"},
    )
    assert missing["decision"] == "refused"


def test_hold_selects_lowest_load_penalty():
    vault = SemanticVault.load()
    runtime = build_stub_runtime(vault)
    decision = decide(
        "hold_unresolved", runtime.enabled_occurrences(), vault, outage=False
    )
    assert decision.action is BrainAction.SELECT
    assert decision.match_id is not None


def test_brain_v1_has_no_llm_import():
    from pathlib import Path

    source = (Path(__file__).resolve().parents[1] / "osahr_cell" / "brain.py").read_text(
        encoding="utf-8"
    )
    assert_no_llm_import(source)


def test_claims_score_tool_is_recon():
    vault = SemanticVault.load()
    tools = ToolRegistry(vault)
    payload = tools.call(
        "claims.score",
        {
            "oracle_effect": 0.2,
            "effects_by_alpha": {"0": 0.18, "0.25": 0.21, "0.5": 0.19, "1": 0.22},
            "scenario": 1,
            "regime": "id",
            "horizon": 60.0,
            "activation": {"events": 2, "outages": 0, "handovers": 1, "reroutes": 0},
        },
    )
    assert payload["status"] == "admit"
    inspect = tools.call("vault.query", {"concept_id": "critical"})
    assert inspect["requires_fidelity"] is True
