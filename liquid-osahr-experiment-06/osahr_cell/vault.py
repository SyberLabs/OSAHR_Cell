"""File-backed personal knowledge graph (markdown + YAML). Not a second kernel."""
from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from .protocol import CLAIMS_NOTES_DIR, CONCEPTS_DIR

FRONTMATTER = re.compile(r"^---\s*\n(.*?)\n---\s*\n?(.*)\Z", re.DOTALL)
WIKILINK = re.compile(r"\[\[([^\]]+)\]\]")


@dataclass(frozen=True)
class Concept:
    concept_id: str
    excludes: tuple[str, ...]
    requires_fidelity: bool
    degraded_fidelity_edges: tuple[str, ...]
    body: str
    wikilinks: tuple[str, ...]
    path: str

    def to_query(self) -> dict[str, Any]:
        return {
            "concept_id": self.concept_id,
            "excludes": list(self.excludes),
            "requires_fidelity": self.requires_fidelity,
            "degraded_fidelity_edges": list(self.degraded_fidelity_edges),
            "wikilinks": list(self.wikilinks),
            "path": self.path,
        }


def parse_note(path: Path) -> Concept:
    text = path.read_text(encoding="utf-8")
    match = FRONTMATTER.match(text)
    if match is None:
        raise ValueError(f"vault note {path} lacks YAML frontmatter")
    meta = yaml.safe_load(match.group(1)) or {}
    if not isinstance(meta, dict):
        raise ValueError(f"vault note {path} frontmatter is not a mapping")
    concept_id = str(meta["concept_id"])
    excludes = tuple(str(item) for item in (meta.get("excludes") or ()))
    requires_fidelity = bool(meta.get("requires_fidelity", False))
    degraded = tuple(str(item) for item in (meta.get("degraded_fidelity_edges") or ()))
    body = match.group(2)
    links = tuple(dict.fromkeys(WIKILINK.findall(body)))
    return Concept(
        concept_id=concept_id,
        excludes=excludes,
        requires_fidelity=requires_fidelity,
        degraded_fidelity_edges=degraded,
        body=body,
        wikilinks=links,
        path=str(path),
    )


class SemanticVault:
    """Dual projection: markdown for humans, typed concepts for the twin."""

    def __init__(self, concepts: dict[str, Concept], *, root: Path) -> None:
        self.concepts = dict(concepts)
        self.root = Path(root)

    @classmethod
    def load(cls, root: Path | None = None) -> "SemanticVault":
        concepts_dir = Path(root) if root is not None else CONCEPTS_DIR
        if concepts_dir.name != "concepts":
            concepts_dir = Path(concepts_dir) / "concepts"
            if not concepts_dir.is_dir():
                concepts_dir = Path(root)  # type: ignore[arg-type]
        notes = sorted(concepts_dir.glob("*.md"))
        if not notes:
            raise FileNotFoundError(f"no vault notes in {concepts_dir}")
        concepts = {}
        for note in notes:
            concept = parse_note(note)
            if concept.concept_id in concepts:
                raise ValueError(f"duplicate concept_id {concept.concept_id!r}")
            concepts[concept.concept_id] = concept
        return cls(concepts, root=concepts_dir.parent)

    def degraded_fidelity_edges(self) -> frozenset[str]:
        edges: set[str] = set()
        for concept in self.concepts.values():
            edges.update(concept.degraded_fidelity_edges)
        return frozenset(edges)

    def query(self, concept_id: str) -> dict[str, Any]:
        if concept_id not in self.concepts:
            raise KeyError(concept_id)
        payload = self.concepts[concept_id].to_query()
        payload["degraded_fidelity_edges_union"] = sorted(self.degraded_fidelity_edges())
        return payload

    def admissible(self, task_kind: str, edge_name: str, outage: bool) -> bool:
        return admissible(self, task_kind, edge_name, outage)

    def record_claim_note(
        self,
        *,
        scenario: int,
        status: str,
        reason: str,
        extra: dict[str, Any] | None = None,
        dest: Path | None = None,
    ) -> Path:
        """Park: chat is not the database. Withheld actions land as notes."""
        directory = Path(dest) if dest is not None else CLAIMS_NOTES_DIR
        directory.mkdir(parents=True, exist_ok=True)
        payload = {
            "concept_id": f"claim-{scenario}-{status}",
            "claim_status": status,
            "scenario": int(scenario),
            "excludes": [],
            "requires_fidelity": False,
        }
        if extra:
            payload["extra"] = extra
        body = (
            f"---\n{yaml.safe_dump(payload, sort_keys=False)}---\n\n"
            f"# Withheld / scored claim\n\n{reason}\n"
        )
        path = directory / f"scenario-{scenario}-{status}.md"
        path.write_text(body, encoding="utf-8")
        return path


def admissible(
    vault: SemanticVault, task_kind: str, edge_name: str, outage: bool
) -> bool:
    """Semantic legality at a declared route-task junction. No SPARQL."""
    if task_kind not in vault.concepts:
        raise KeyError(f"unknown task kind {task_kind!r}")
    concept = vault.concepts[task_kind]
    degraded = vault.degraded_fidelity_edges()
    if concept.requires_fidelity and edge_name in degraded:
        return False
    if outage and "outage" in concept.excludes and edge_name in degraded:
        return False
    return True
