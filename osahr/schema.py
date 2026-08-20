"""Typed schema for directed attributed hypergraphs."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from .canonical import stable_hash
from .errors import SchemaError, ValidationError
from .expr import Expr


class ValueKind(str, Enum):
    BOOL = "bool"
    INT = "int"
    FLOAT = "float"
    STRING = "string"
    ENTITY_REF = "entity_ref"
    ANY = "any"


@dataclass(frozen=True, slots=True)
class AttributeSpec:
    kind: ValueKind = ValueKind.ANY
    required: bool = False
    default: Any = None
    mutable: bool = True
    nullable: bool = False
    minimum: float | int | None = None
    maximum: float | int | None = None
    choices: frozenset[Any] | None = None
    indexed: bool = False

    def validate(self, name: str, value: Any) -> None:
        if value is None:
            if self.nullable:
                return
            raise ValidationError(f"Attribute {name!r} is not nullable")

        valid = {
            ValueKind.BOOL: lambda x: isinstance(x, bool),
            ValueKind.INT: lambda x: isinstance(x, int) and not isinstance(x, bool),
            ValueKind.FLOAT: lambda x: isinstance(x, (int, float)) and not isinstance(x, bool),
            ValueKind.STRING: lambda x: isinstance(x, str),
            ValueKind.ENTITY_REF: lambda x: hasattr(x, "namespace") and hasattr(x, "counter"),
            ValueKind.ANY: lambda _x: True,
        }[self.kind](value)
        if not valid:
            raise ValidationError(
                f"Attribute {name!r} expected {self.kind.value}, got {type(value).__name__}"
            )
        if self.minimum is not None and value < self.minimum:
            raise ValidationError(f"Attribute {name!r} is below minimum {self.minimum}")
        if self.maximum is not None and value > self.maximum:
            raise ValidationError(f"Attribute {name!r} is above maximum {self.maximum}")
        if self.choices is not None and value not in self.choices:
            raise ValidationError(f"Attribute {name!r} is not one of {sorted(self.choices)!r}")


@dataclass(frozen=True, slots=True)
class VertexType:
    type_id: str
    attributes: dict[str, AttributeSpec] = field(default_factory=dict)
    parents: frozenset[str] = frozenset()
    allow_extensions: bool = False
    invariants: tuple[Expr, ...] = ()


@dataclass(frozen=True, slots=True)
class PortSpec:
    role: str
    accepted_vertex_type: str
    minimum: int = 1
    maximum: int | None = 1
    ordered: bool = True
    allow_subtypes: bool = True
    repeated_vertices: bool = False

    def __post_init__(self) -> None:
        if self.minimum < 0:
            raise SchemaError("Port minimum cannot be negative")
        if self.maximum is not None and self.maximum < self.minimum:
            raise SchemaError("Port maximum cannot be less than minimum")


@dataclass(frozen=True, slots=True)
class HyperedgeType:
    type_id: str
    tail_ports: dict[str, PortSpec]
    head_ports: dict[str, PortSpec]
    attributes: dict[str, AttributeSpec] = field(default_factory=dict)
    allow_extensions: bool = False
    invariants: tuple[Expr, ...] = ()


class Schema:
    def __init__(
        self,
        vertex_types: list[VertexType] | tuple[VertexType, ...],
        edge_types: list[HyperedgeType] | tuple[HyperedgeType, ...],
        *,
        schema_id: str = "schema",
        version: str = "1.0.0",
    ) -> None:
        self.schema_id = schema_id
        self.version = version
        self.vertex_types = {item.type_id: item for item in vertex_types}
        self.edge_types = {item.type_id: item for item in edge_types}
        if len(self.vertex_types) != len(vertex_types):
            raise SchemaError("Duplicate vertex type ID")
        if len(self.edge_types) != len(edge_types):
            raise SchemaError("Duplicate hyperedge type ID")
        self._validate_type_graph()
        self._ancestors = self._compute_ancestors()
        self.hash = stable_hash(self.to_canonical())

    def _validate_type_graph(self) -> None:
        for vertex_type in self.vertex_types.values():
            unknown = set(vertex_type.parents) - self.vertex_types.keys()
            if unknown:
                raise SchemaError(f"Unknown parent types for {vertex_type.type_id}: {unknown}")

        visiting: set[str] = set()
        visited: set[str] = set()

        def visit(type_id: str) -> None:
            if type_id in visiting:
                raise SchemaError(f"Subtype cycle involving {type_id}")
            if type_id in visited:
                return
            visiting.add(type_id)
            for parent in self.vertex_types[type_id].parents:
                visit(parent)
            visiting.remove(type_id)
            visited.add(type_id)

        for type_id in self.vertex_types:
            visit(type_id)

        for edge_type in self.edge_types.values():
            for port in (*edge_type.tail_ports.values(), *edge_type.head_ports.values()):
                if port.accepted_vertex_type not in self.vertex_types:
                    raise SchemaError(
                        f"Port {edge_type.type_id}.{port.role} references unknown vertex type "
                        f"{port.accepted_vertex_type}"
                    )

    def _compute_ancestors(self) -> dict[str, frozenset[str]]:
        memo: dict[str, frozenset[str]] = {}

        def ancestors(type_id: str) -> frozenset[str]:
            if type_id in memo:
                return memo[type_id]
            result = {type_id}
            for parent in self.vertex_types[type_id].parents:
                result.update(ancestors(parent))
            memo[type_id] = frozenset(result)
            return memo[type_id]

        return {type_id: ancestors(type_id) for type_id in self.vertex_types}

    def is_vertex_compatible(self, actual: str, expected: str, *, allow_subtypes: bool = True) -> bool:
        if actual not in self.vertex_types or expected not in self.vertex_types:
            return False
        return actual == expected or (allow_subtypes and expected in self._ancestors[actual])

    @staticmethod
    def _materialize_attributes(
        specs: dict[str, AttributeSpec],
        attrs: dict[str, Any],
        *,
        allow_extensions: bool,
    ) -> dict[str, Any]:
        result = dict(attrs)
        for name, spec in specs.items():
            if name not in result:
                if spec.default is not None or spec.nullable:
                    result[name] = spec.default
                elif spec.required:
                    raise ValidationError(f"Required attribute {name!r} is missing")
        if not allow_extensions:
            unknown = set(result) - specs.keys()
            if unknown:
                raise ValidationError(f"Unknown attributes: {sorted(unknown)!r}")
        for name, value in result.items():
            if name in specs:
                specs[name].validate(name, value)
        return result

    def materialize_vertex_attributes(self, type_id: str, attrs: dict[str, Any]) -> dict[str, Any]:
        try:
            definition = self.vertex_types[type_id]
        except KeyError as exc:
            raise ValidationError(f"Unknown vertex type {type_id!r}") from exc
        result = self._materialize_attributes(
            definition.attributes, attrs, allow_extensions=definition.allow_extensions
        )
        for invariant in definition.invariants:
            context = {**result, "a": result, "attributes": result}
            if not bool(invariant.evaluate(context)):
                raise ValidationError(
                    f"Vertex invariant failed for type {type_id}: {invariant.source}"
                )
        return result

    def materialize_edge_attributes(self, type_id: str, attrs: dict[str, Any]) -> dict[str, Any]:
        try:
            definition = self.edge_types[type_id]
        except KeyError as exc:
            raise ValidationError(f"Unknown edge type {type_id!r}") from exc
        result = self._materialize_attributes(
            definition.attributes, attrs, allow_extensions=definition.allow_extensions
        )
        for invariant in definition.invariants:
            context = {**result, "a": result, "attributes": result}
            if not bool(invariant.evaluate(context)):
                raise ValidationError(
                    f"Edge invariant failed for type {type_id}: {invariant.source}"
                )
        return result

    def to_canonical(self) -> dict[str, Any]:
        def attr_map(attributes: dict[str, AttributeSpec]) -> dict[str, Any]:
            return {
                name: {
                    "kind": spec.kind.value,
                    "required": spec.required,
                    "default": spec.default,
                    "mutable": spec.mutable,
                    "nullable": spec.nullable,
                    "minimum": spec.minimum,
                    "maximum": spec.maximum,
                    "choices": spec.choices,
                    "indexed": spec.indexed,
                }
                for name, spec in attributes.items()
            }

        return {
            "schema_id": self.schema_id,
            "version": self.version,
            "vertex_types": {
                type_id: {
                    "parents": definition.parents,
                    "attributes": attr_map(definition.attributes),
                    "allow_extensions": definition.allow_extensions,
                    "invariants": [item.source for item in definition.invariants],
                }
                for type_id, definition in self.vertex_types.items()
            },
            "edge_types": {
                type_id: {
                    "tail_ports": definition.tail_ports,
                    "head_ports": definition.head_ports,
                    "attributes": attr_map(definition.attributes),
                    "allow_extensions": definition.allow_extensions,
                    "invariants": [item.source for item in definition.invariants],
                }
                for type_id, definition in self.edge_types.items()
            },
        }
