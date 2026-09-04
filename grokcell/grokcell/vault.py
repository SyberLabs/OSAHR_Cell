"""File-backed constraint notes. Dual projection; not a second kernel."""
from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .protocol import CONCEPTS_DIR, VAULT_DIR

_MESSAGE_ID = re.compile(r"m-[0-9]{4,}")
_CLAIM_STATUSES = {"hold_unresolved", "outcome_unknown", "reject"}


def _parse_scalar(text: str) -> Any:
    raw = text.strip()
    if raw in {"true", "True"}:
        return True
    if raw in {"false", "False"}:
        return False
    if raw.startswith("[") and raw.endswith("]"):
        inner = raw[1:-1].strip()
        if not inner:
            return []
        return [item.strip().strip("'\"") for item in inner.split(",")]
    return raw.strip("'\"")


def parse_note(path: Path) -> "Concept":
    text = path.read_text(encoding="utf-8")
    if not text.startswith("---"):
        raise ValueError(f"vault note {path} lacks YAML frontmatter")
    parts = text.split("---", 2)
    if len(parts) < 3:
        raise ValueError(f"vault note {path} is not closed frontmatter")
    meta: dict[str, Any] = {}
    current_list: str | None = None
    for line in parts[1].splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        if stripped.startswith("- ") and current_list is not None:
            meta[current_list].append(stripped[2:].strip())
            continue
        if ":" not in stripped:
            continue
        key, _, rest = stripped.partition(":")
        key = key.strip()
        rest = rest.strip()
        if rest == "":
            meta[key] = []
            current_list = key
        else:
            meta[key] = _parse_scalar(rest)
            current_list = None
    body = parts[2].lstrip("\n")
    excludes = tuple(str(item) for item in (meta.get("excludes") or ()))
    return Concept(
        concept_id=str(meta["concept_id"]),
        excludes=excludes,
        requires_fidelity=bool(meta.get("requires_fidelity", False)),
        body=body,
        path=str(path),
    )


@dataclass(frozen=True)
class Concept:
    concept_id: str
    excludes: tuple[str, ...]
    requires_fidelity: bool
    body: str
    path: str

    def to_query(self) -> dict[str, Any]:
        return {
            "concept_id": self.concept_id,
            "excludes": list(self.excludes),
            "requires_fidelity": self.requires_fidelity,
            "path": self.path,
        }


class ConstraintVault:
    def __init__(self, concepts: dict[str, Concept], *, root: Path) -> None:
        self.concepts = dict(concepts)
        self.root = Path(root)

    @classmethod
    def load(cls, root: Path | None = None) -> "ConstraintVault":
        concepts_dir = Path(root) if root is not None else CONCEPTS_DIR
        writable_root = concepts_dir.parent if root is not None else VAULT_DIR
        if concepts_dir.name != "concepts":
            candidate = concepts_dir / "concepts"
            if candidate.is_dir():
                concepts_dir = candidate
                if root is not None:
                    writable_root = concepts_dir.parent
        notes = sorted(concepts_dir.glob("*.md"))
        if not notes:
            raise FileNotFoundError(f"no vault notes in {concepts_dir}")
        concepts = {}
        for note in notes:
            concept = parse_note(note)
            if concept.concept_id in concepts:
                raise ValueError(f"duplicate concept_id {concept.concept_id!r}")
            concepts[concept.concept_id] = concept
        return cls(concepts, root=writable_root)

    def query(self, concept_id: str) -> dict[str, Any]:
        if concept_id not in self.concepts:
            raise KeyError(concept_id)
        return self.concepts[concept_id].to_query()

    def record_note(self, *, status: str, reason: str, message_id: str) -> Path:
        if _MESSAGE_ID.fullmatch(message_id) is None or status not in _CLAIM_STATUSES:
            raise ValueError("invalid claim note identity")
        directory = self.root / "claims"
        directory.mkdir(parents=True, exist_ok=True)
        path = directory / f"{message_id}-{status}.md"
        temporary = path.with_suffix(path.suffix + ".tmp")
        temporary.write_text(
            f"---\nconcept_id: {message_id}-{status}\nclaim_status: {status}\n"
            f"excludes: []\nrequires_fidelity: false\n---\n\n{reason}\n",
            encoding="utf-8",
        )
        temporary.replace(path)
        return path
