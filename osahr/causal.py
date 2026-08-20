"""Conservative causal dependency reconstruction from committed event records."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Iterable

from .events import EventKind, EventRecord
from .ids import EntityId


def _flatten_changed_paths(before: Any, after: Any, prefix: str) -> set[str]:
    if isinstance(before, dict) and isinstance(after, dict):
        result: set[str] = set()
        for key in set(before) | set(after):
            path = f"{prefix}.{key}" if prefix else str(key)
            if key not in before or key not in after:
                result.add(path)
            else:
                result.update(_flatten_changed_paths(before[key], after[key], path))
        return result
    return set() if before == after else {prefix}


@dataclass(frozen=True, slots=True)
class EventFootprint:
    event_id: str
    event_index: int
    read_entities: frozenset[EntityId]
    written_entities: frozenset[EntityId]
    written_state_paths: frozenset[str]

    @classmethod
    def from_record(cls, record: EventRecord) -> "EventFootprint":
        read_entities: set[EntityId] = set()
        if record.kind is EventKind.INTERNAL_REWRITE:
            read_entities.update(record.cause.get("vertex_map", {}).values())
            read_entities.update(record.cause.get("edge_map", {}).values())
        elif record.kind is EventKind.EXTERNAL_INPUT:
            bound = record.cause.get("bound_vertex")
            if bound is not None:
                read_entities.add(bound)

        written_entities = record.graph_delta.touched_entities()
        state_paths = _flatten_changed_paths(
            record.parameter_before,
            record.parameter_after,
            "parameters",
        ) | _flatten_changed_paths(
            record.memory_before,
            record.memory_after,
            "memory",
        )
        return cls(
            event_id=record.event_id,
            event_index=record.event_index,
            read_entities=frozenset(read_entities),
            written_entities=frozenset(written_entities),
            written_state_paths=frozenset(state_paths),
        )


@dataclass(slots=True)
class CausalTrace:
    """A conservative event-level causal DAG.

    An edge ``a -> b`` is added when ``a`` is the latest event to write an
    entity read or written by ``b``. State-path writes are chained by path.
    This is conservative with respect to entity-level dependencies because a
    matched entity is treated as wholly read.
    """

    predecessors: dict[str, set[str]] = field(default_factory=dict)
    successors: dict[str, set[str]] = field(default_factory=dict)
    event_index: dict[str, int] = field(default_factory=dict)
    _last_entity_writer: dict[EntityId, str] = field(default_factory=dict)
    _last_state_writer: dict[str, str] = field(default_factory=dict)

    def add(self, record: EventRecord) -> None:
        footprint = EventFootprint.from_record(record)
        event_id = footprint.event_id
        self.predecessors.setdefault(event_id, set())
        self.successors.setdefault(event_id, set())
        self.event_index[event_id] = footprint.event_index

        dependencies: set[str] = set()
        for entity_id in footprint.read_entities | footprint.written_entities:
            writer = self._last_entity_writer.get(entity_id)
            if writer is not None and writer != event_id:
                dependencies.add(writer)
        for path in footprint.written_state_paths:
            writer = self._last_state_writer.get(path)
            if writer is not None and writer != event_id:
                dependencies.add(writer)

        for predecessor in dependencies:
            self.predecessors[event_id].add(predecessor)
            self.successors.setdefault(predecessor, set()).add(event_id)

        for entity_id in footprint.written_entities:
            self._last_entity_writer[entity_id] = event_id
        for path in footprint.written_state_paths:
            self._last_state_writer[path] = event_id

    @classmethod
    def from_records(cls, records: Iterable[EventRecord]) -> "CausalTrace":
        trace = cls()
        for record in records:
            trace.add(record)
        return trace

    def ancestors(self, event_id: str) -> list[str]:
        seen: set[str] = set()
        stack = list(self.predecessors.get(event_id, ()))
        while stack:
            current = stack.pop()
            if current in seen:
                continue
            seen.add(current)
            stack.extend(self.predecessors.get(current, ()))
        return sorted(seen, key=lambda item: self.event_index[item])

    def descendants(self, event_id: str) -> list[str]:
        seen: set[str] = set()
        stack = list(self.successors.get(event_id, ()))
        while stack:
            current = stack.pop()
            if current in seen:
                continue
            seen.add(current)
            stack.extend(self.successors.get(current, ()))
        return sorted(seen, key=lambda item: self.event_index[item])
