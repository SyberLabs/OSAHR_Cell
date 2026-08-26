from __future__ import annotations

from osahr_cell.protocol import CONCEPTS_DIR
from osahr_cell.vault import SemanticVault, admissible, parse_note


def test_notes_exist_on_disk():
    names = {path.stem for path in CONCEPTS_DIR.glob("*.md")}
    assert names == {"critical", "background", "outage", "load"}


def test_dual_projection_yaml_and_wikilinks():
    vault = SemanticVault.load()
    critical = vault.concepts["critical"]
    assert critical.requires_fidelity is True
    assert "outage" in critical.excludes
    assert "outage" in critical.wikilinks
    assert "background" in critical.wikilinks
    load = vault.concepts["load"]
    assert "MEC-fast" in load.degraded_fidelity_edges
    assert "critical" in load.wikilinks or "outage" in load.wikilinks


def test_critical_cannot_use_degraded_fidelity_edge():
    vault = SemanticVault.load()
    assert vault.admissible("critical", "MEC-fast", False) is False
    assert vault.admissible("critical", "MEC-fast", True) is False
    assert admissible(vault, "critical", "MEC-robust", False) is True
    assert vault.admissible("critical", "MEC-robust", True) is True


def test_background_may_use_degraded_fidelity_edge():
    vault = SemanticVault.load()
    assert vault.admissible("background", "MEC-fast", False) is True
    assert vault.admissible("background", "MEC-fast", True) is True
    assert vault.admissible("background", "MEC-robust", False) is True


def test_query_is_inspectable():
    vault = SemanticVault.load()
    payload = vault.query("critical")
    assert payload["concept_id"] == "critical"
    assert payload["requires_fidelity"] is True
    assert "MEC-fast" in payload["degraded_fidelity_edges_union"]
