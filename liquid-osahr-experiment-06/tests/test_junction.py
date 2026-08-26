from __future__ import annotations

from osahr.matcher import Matcher

from osahr_cell.junction import compiled_route_guard, applicable_matches
from osahr_cell.protocol import JUNCTION_RULE_ID
from osahr_cell.twin import build_stub_runtime, junction_rule_matches
from osahr_cell.vault import SemanticVault


def test_illegal_vault_pair_is_not_applicable():
    vault = SemanticVault.load()
    runtime = build_stub_runtime(vault)
    matches = junction_rule_matches(runtime, vault)
    edges = {match.bindings["edge_name"] for match in matches}
    kinds = {match.bindings["task_kind"] for match in matches}
    assert "critical" in kinds
    assert "MEC-fast" not in edges
    assert "MEC-robust" in edges


def test_prefilter_agrees_with_guard_and_does_not_mutate_graph():
    vault = SemanticVault.load()
    runtime = build_stub_runtime(vault)
    before = runtime.graph.state_hash
    rule = runtime.rules[JUNCTION_RULE_ID]
    unguarded = Matcher().find_pattern_matches(
        runtime.graph, rule.left, rule_id=rule.rule_id
    )
    illegal = [
        match
        for match in unguarded
        if match.bindings.get("task_kind") == "critical"
        and match.bindings.get("edge_name") == "MEC-fast"
    ]
    assert illegal, "stub should contain a structural critical/MEC-fast pair"
    filtered = applicable_matches(unguarded, vault, outage=False, rule_id=JUNCTION_RULE_ID)
    assert all(
        not (
            match.bindings.get("task_kind") == "critical"
            and match.bindings.get("edge_name") == "MEC-fast"
        )
        for match in filtered
    )
    assert runtime.graph.state_hash == before


def test_other_rules_still_match():
    vault = SemanticVault.load()
    runtime = build_stub_runtime(vault)
    matcher = Matcher()
    generated = matcher.find_rule_matches(
        runtime.graph,
        runtime.rules["generate-critical"],
        parameters=runtime.parameters,
        memory=runtime.memory,
        time=runtime.time,
    )
    completed = matcher.find_rule_matches(
        runtime.graph,
        runtime.rules["complete-task"],
        parameters=runtime.parameters,
        memory=runtime.memory,
        time=runtime.time,
    )
    assert generated
    assert completed
    assert compiled_route_guard(vault).source.startswith("load < capacity")
