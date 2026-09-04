"""Atomic DPO rewrite transactions."""

from __future__ import annotations

import copy
from dataclasses import dataclass
from typing import Any

from .boundary import BoundaryDelta, BoundaryDirection, BoundaryState, OutputEvent
from .canonical import canonical_equal, stable_hash, validate_state_value
from .errors import MatchError, RewriteError, ValidationError
from .expr import evaluate_value, set_path
from .graph import GraphDelta, Hypergraph
from .matcher import Match, Matcher, build_expression_context
from .pattern import BoundaryEffectKind, Rule


@dataclass(slots=True)
class RewriteResult:
    graph: Hypergraph
    boundary: BoundaryState
    parameters: dict[str, Any]
    memory: dict[str, Any]
    graph_delta: GraphDelta
    boundary_delta: BoundaryDelta
    parameter_before: dict[str, Any]
    parameter_after: dict[str, Any]
    memory_before: dict[str, Any]
    memory_after: dict[str, Any]
    outputs: list[OutputEvent]
    post_vertex_map: dict[str, Any]
    post_edge_map: dict[str, Any]


class RewriteEngine:
    def is_applicable(
        self,
        *,
        graph: Hypergraph,
        boundary: BoundaryState,
        rule: Rule,
        match: Match,
    ) -> bool:
        """Return whether the structural DPO/boundary gluing conditions hold.

        This predicate is intentionally side-effect free and is used by stochastic
        schedulers *before* hazards enter the enabled activity. A match that cannot
        produce a valid DPO direct derivation is not a stochastic transition channel.
        """
        if match.rule_id != rule.rule_id or match.graph_epoch != graph.epoch:
            return False
        if any(entity_id not in graph.vertices for entity_id in match.vertex_map.values()):
            return False
        if any(entity_id not in graph.edges for entity_id in match.edge_map.values()):
            return False
        deleted_vertex_ids = {match.vertex_map[key] for key in rule.deleted_vertex_keys}
        deleted_edge_ids = {match.edge_map[key] for key in rule.deleted_edge_keys}
        for vertex_id in deleted_vertex_ids:
            if graph.incident_edges(vertex_id) - deleted_edge_ids:
                return False
        effected_handles = {effect.handle_id for effect in rule.boundary_effects}
        for handle_id, handle in boundary.handles.items():
            if handle.binding in deleted_vertex_ids and handle_id not in effected_handles:
                return False
        return True

    def apply(
        self,
        *,
        graph: Hypergraph,
        boundary: BoundaryState,
        parameters: dict[str, Any],
        memory: dict[str, Any],
        rule: Rule,
        match: Match,
        time: float,
        delta_time: float,
        event_index: int,
        event_id: str,
    ) -> RewriteResult:
        authoritative_match = Matcher().authoritative_rule_match(
            graph,
            rule,
            match,
            parameters=parameters,
            memory=memory,
            time=time,
        )
        if authoritative_match is None:
            raise MatchError("Match is not valid for the authoritative graph and rule")
        match = authoritative_match

        work_graph = graph.clone()
        work_boundary = boundary.clone()
        work_parameters = copy.deepcopy(parameters)
        work_memory = copy.deepcopy(memory)
        parameter_before = copy.deepcopy(parameters)
        memory_before = copy.deepcopy(memory)
        delta = GraphDelta()
        boundary_delta = BoundaryDelta()

        left_vertices = rule.left.vertex_map
        right_vertices = rule.right.vertex_map
        left_edges = rule.left.edge_map
        right_edges = rule.right.edge_map

        deleted_vertex_ids = {
            match.vertex_map[key] for key in rule.deleted_vertex_keys
        }
        deleted_edge_ids = {match.edge_map[key] for key in rule.deleted_edge_keys}

        # DPO dangling condition.
        for vertex_id in deleted_vertex_ids:
            unmatched_incident = work_graph.incident_edges(vertex_id) - deleted_edge_ids
            if unmatched_incident:
                raise RewriteError(
                    f"DPO dangling condition failed for {vertex_id}; incident edges not deleted: "
                    f"{sorted(map(str, unmatched_incident))}"
                )

        # Boundary gluing condition.
        effected_handles = {effect.handle_id: effect for effect in rule.boundary_effects}
        for handle_id, handle in work_boundary.handles.items():
            if handle.binding in deleted_vertex_ids and handle_id not in effected_handles:
                raise RewriteError(
                    f"Rule deletes boundary-bound vertex {handle.binding} without handling {handle_id!r}"
                )

        pre_context = build_expression_context(
            graph,
            match,
            parameters=parameters,
            memory=memory,
            time=time,
            delta_time=delta_time,
            extra={"meta": rule.meta},
        )

        # Delete matched edges before matched vertices.
        for key in sorted(rule.deleted_edge_keys):
            edge_id = match.edge_map[key]
            deleted = work_graph.remove_edge(edge_id, increment_epoch=False)
            delta.deleted_edges[edge_id] = copy.deepcopy(deleted)
        for key in sorted(rule.deleted_vertex_keys):
            vertex_id = match.vertex_map[key]
            deleted = work_graph.remove_vertex(vertex_id, increment_epoch=False)
            delta.deleted_vertices[vertex_id] = copy.deepcopy(deleted)

        post_vertex_map = {
            key: match.vertex_map[key] for key in rule.preserved_vertex_keys
        }
        post_edge_map = {key: match.edge_map[key] for key in rule.preserved_edge_keys}

        # Create RHS-only vertices.
        for key in sorted(rule.created_vertex_keys):
            template = right_vertices[key]
            attrs = {
                name: evaluate_value(value, pre_context)
                for name, value in template.attributes.items()
            }
            created = work_graph.add_vertex(
                template.type_id, attrs, increment_epoch=False
            )
            post_vertex_map[key] = created.entity_id
            delta.created_vertices[created.entity_id] = copy.deepcopy(created)

        # Update preserved vertex attributes.
        for key in sorted(rule.preserved_vertex_keys):
            template = right_vertices[key]
            if template.attributes:
                updates = {
                    name: evaluate_value(value, pre_context)
                    for name, value in template.attributes.items()
                }
                vertex_id = post_vertex_map[key]
                before, after = work_graph.set_vertex_attributes(
                    vertex_id, updates, increment_epoch=False
                )
                if not canonical_equal(before, after):
                    delta.updated_vertices_before[vertex_id] = before
                    delta.updated_vertices_after[vertex_id] = after

        # Create RHS-only edges after all RHS vertices exist.
        for key in sorted(rule.created_edge_keys):
            template = right_edges[key]
            tail = {
                role: tuple(post_vertex_map[vertex_key] for vertex_key in vertex_keys)
                for role, vertex_keys in template.tail.items()
            }
            head = {
                role: tuple(post_vertex_map[vertex_key] for vertex_key in vertex_keys)
                for role, vertex_keys in template.head.items()
            }
            attrs = {
                name: evaluate_value(value, pre_context)
                for name, value in template.attributes.items()
            }
            created = work_graph.add_edge(
                template.type_id, tail, head, attrs, increment_epoch=False
            )
            post_edge_map[key] = created.entity_id
            delta.created_edges[created.entity_id] = copy.deepcopy(created)

        # Update preserved edge attributes.
        for key in sorted(rule.preserved_edge_keys):
            template = right_edges[key]
            if template.attributes:
                updates = {
                    name: evaluate_value(value, pre_context)
                    for name, value in template.attributes.items()
                }
                edge_id = post_edge_map[key]
                before, after = work_graph.set_edge_attributes(
                    edge_id, updates, increment_epoch=False
                )
                if not canonical_equal(before, after):
                    delta.updated_edges_before[edge_id] = before
                    delta.updated_edges_after[edge_id] = after

        # Apply boundary changes.
        for effect in rule.boundary_effects:
            if effect.kind is BoundaryEffectKind.DELETE_HANDLE:
                try:
                    removed = work_boundary.handles.pop(effect.handle_id)
                except KeyError as exc:
                    raise RewriteError(f"Unknown boundary handle {effect.handle_id!r}") from exc
                boundary_delta.deleted_handles[effect.handle_id] = removed
                continue
            try:
                handle = work_boundary.handles[effect.handle_id]
            except KeyError as exc:
                raise RewriteError(f"Unknown boundary handle {effect.handle_id!r}") from exc
            boundary_delta.before.setdefault(effect.handle_id, handle.binding)
            if effect.kind is BoundaryEffectKind.UNBIND:
                if not handle.nullable:
                    raise RewriteError(f"Handle {effect.handle_id!r} is not nullable")
                handle.binding = None
            elif effect.kind in {BoundaryEffectKind.BIND, BoundaryEffectKind.REBIND}:
                assert effect.vertex_key is not None
                if effect.kind is BoundaryEffectKind.BIND and handle.binding is not None:
                    raise RewriteError(f"Handle {effect.handle_id!r} is already bound")
                handle.binding = post_vertex_map[effect.vertex_key]
            else:  # pragma: no cover - defensive
                raise RewriteError(f"Unsupported boundary effect {effect.kind}")
            boundary_delta.after[effect.handle_id] = handle.binding

        work_graph.validate()
        work_boundary.validate(set(work_graph.vertices))
        for handle in work_boundary.handles.values():
            if handle.binding is not None:
                actual_type = work_graph.vertices[handle.binding].type_id
                if not work_graph.schema.is_vertex_compatible(actual_type, handle.interface_type):
                    raise RewriteError(
                        f"Boundary {handle.handle_id!r} expects {handle.interface_type}, "
                        f"got {actual_type}"
                    )

        # Post-state context used for adaptation and outputs.
        post_match = Match.create(
            rule_id=rule.rule_id,
            vertex_map=post_vertex_map,
            edge_map=post_edge_map,
            bindings=match.bindings,
            graph_epoch=work_graph.epoch,
        )
        post_context = build_expression_context(
            work_graph,
            post_match,
            parameters=parameters,
            memory=memory,
            time=time,
            delta_time=delta_time,
            extra={"pre": pre_context, "meta": rule.meta},
        )

        # Evaluate all assignments against the same pre-adaptation state.
        evaluated_assignments = [
            (assignment.target, evaluate_value(assignment.value, post_context))
            for assignment in rule.adaptation
        ]
        for target, value in evaluated_assignments:
            root_name, path = target.split(".", 1)
            if root_name == "parameters":
                set_path(work_parameters, path, value)
            else:
                set_path(work_memory, path, value)

        validate_state_value(work_parameters)
        validate_state_value(work_memory)

        outputs: list[OutputEvent] = []
        output_context = build_expression_context(
            work_graph,
            post_match,
            parameters=work_parameters,
            memory=work_memory,
            time=time,
            delta_time=delta_time,
            extra={"pre": pre_context, "meta": rule.meta},
        )
        for offset, output_spec in enumerate(rule.outputs):
            if output_spec.handle_id not in work_boundary.handles:
                raise RewriteError(f"Unknown output handle {output_spec.handle_id!r}")
            output_handle = work_boundary.handles[output_spec.handle_id]
            if output_handle.direction not in {BoundaryDirection.OUTPUT, BoundaryDirection.BIDIRECTIONAL}:
                raise RewriteError(
                    f"Boundary handle {output_spec.handle_id!r} does not permit output"
                )
            payload = {
                name: evaluate_value(value, output_context)
                for name, value in output_spec.payload.items()
            }
            output_handle.validate_payload(payload)
            outputs.append(
                OutputEvent(
                    event_id=stable_hash(
                        {
                            "causing_event": event_id,
                            "offset": offset,
                            "handle": output_spec.handle_id,
                        }
                    ),
                    simulation_time=time,
                    event_index=event_index,
                    source_handle=output_spec.handle_id,
                    event_type=output_spec.event_type,
                    payload=payload,
                    causing_event_id=event_id,
                )
            )

        # One logical epoch per committed transaction.
        work_graph.epoch = graph.epoch + 1
        return RewriteResult(
            graph=work_graph,
            boundary=work_boundary,
            parameters=work_parameters,
            memory=work_memory,
            graph_delta=delta,
            boundary_delta=boundary_delta,
            parameter_before=parameter_before,
            parameter_after=copy.deepcopy(work_parameters),
            memory_before=memory_before,
            memory_after=copy.deepcopy(work_memory),
            outputs=outputs,
            post_vertex_map=post_vertex_map,
            post_edge_map=post_edge_map,
        )
