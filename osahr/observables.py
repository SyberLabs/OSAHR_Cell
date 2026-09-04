"""Deterministic observables over runtime state."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol

from .canonical import canonical_equal
from .graph import Hypergraph


class Observable(Protocol):
    observable_id: str

    def evaluate(
        self,
        graph: Hypergraph,
        parameters: dict[str, Any],
        memory: dict[str, Any],
    ) -> Any: ...


@dataclass(frozen=True, slots=True)
class EntityCount:
    observable_id: str
    type_id: str
    attributes_equal: dict[str, Any] | None = None

    def evaluate(self, graph: Hypergraph, parameters: dict[str, Any], memory: dict[str, Any]) -> int:
        expected = self.attributes_equal or {}
        return sum(
            1
            for entity_id in graph.vertices_by_type.get(self.type_id, ())
            if all(
                key in graph.vertices[entity_id].attributes
                and canonical_equal(graph.vertices[entity_id].attributes[key], value)
                for key, value in expected.items()
            )
        )


@dataclass(frozen=True, slots=True)
class EdgeCount:
    observable_id: str
    type_id: str
    attributes_equal: dict[str, Any] | None = None

    def evaluate(self, graph: Hypergraph, parameters: dict[str, Any], memory: dict[str, Any]) -> int:
        expected = self.attributes_equal or {}
        return sum(
            1
            for entity_id in graph.edges_by_type.get(self.type_id, ())
            if all(
                key in graph.edges[entity_id].attributes
                and canonical_equal(graph.edges[entity_id].attributes[key], value)
                for key, value in expected.items()
            )
        )


@dataclass(frozen=True, slots=True)
class AttributeSum:
    observable_id: str
    type_id: str
    attribute: str

    def evaluate(self, graph: Hypergraph, parameters: dict[str, Any], memory: dict[str, Any]) -> float:
        return float(
            sum(
                graph.vertices[entity_id].attributes[self.attribute]
                for entity_id in graph.vertices_by_type.get(self.type_id, ())
            )
        )
