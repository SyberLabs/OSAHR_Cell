"""Vault gate on declared route-task junctions only.

Uses an OSAHR Expr guard when the vault constraint is static. Outage is
time-varying and stays on the boundary (`available`); a pre-filter that never
mutates G covers `admissible(..., outage=)`.
"""
from __future__ import annotations

from collections.abc import Iterable, Sequence

from osahr.expr import Expr
from osahr.matcher import Match
from osahr.pattern import Rule
from osahr.runtime import EnabledOccurrence

from .protocol import JUNCTION_GRAMMAR_VERSION, JUNCTION_RULE_ID
from .vault import SemanticVault


def compiled_route_guard(vault: SemanticVault) -> Expr:
    """Static vault legality plus the original capacity guard."""
    parts = ["load < capacity"]
    degraded = sorted(vault.degraded_fidelity_edges())
    for concept in vault.concepts.values():
        if not concept.requires_fidelity:
            continue
        for edge in degraded:
            kind = concept.concept_id.replace("'", "")
            name = edge.replace("'", "")
            parts.append(f"(task_kind != '{kind}' or edge_name != '{name}')")
    return Expr(" and ".join(parts))


def is_junction(rule_id: str) -> bool:
    return rule_id == JUNCTION_RULE_ID


def match_vault_legal(
    match: Match,
    vault: SemanticVault,
    *,
    outage: bool,
    rule_id: str | None = None,
) -> bool:
    rid = rule_id or match.rule_id
    if not is_junction(rid):
        return True
    kind = match.bindings.get("task_kind")
    edge = match.bindings.get("edge_name")
    if kind is None or edge is None:
        return False
    return vault.admissible(str(kind), str(edge), outage)


def applicable_matches(
    matches: Sequence[Match],
    vault: SemanticVault,
    *,
    outage: bool,
    rule_id: str | None = None,
) -> list[Match]:
    """Pre-filter. Never mutates G. Query cost only at route-task."""
    return [
        match
        for match in matches
        if match_vault_legal(match, vault, outage=outage, rule_id=rule_id)
    ]


def vault_legal_occurrences(
    occurrences: Iterable[EnabledOccurrence],
    vault: SemanticVault,
    *,
    outage: bool,
) -> list[EnabledOccurrence]:
    legal: list[EnabledOccurrence] = []
    for item in occurrences:
        if not is_junction(item.rule.rule_id):
            continue
        if match_vault_legal(item.match, vault, outage=outage, rule_id=item.rule.rule_id):
            legal.append(item)
    return legal


def assert_unmodified_non_junction(rules: Sequence[Rule], originals: Sequence[Rule]) -> None:
    """Other occurrence types keep their original hashes."""
    original_by_id = {rule.rule_id: rule.hash for rule in originals}
    for rule in rules:
        if is_junction(rule.rule_id):
            continue
        if rule.rule_id in original_by_id and rule.hash != original_by_id[rule.rule_id]:
            raise AssertionError(f"non-junction rule mutated: {rule.rule_id}")


JUNCTION_META = {
    "grammar": JUNCTION_GRAMMAR_VERSION,
    "rule_id": JUNCTION_RULE_ID,
}
