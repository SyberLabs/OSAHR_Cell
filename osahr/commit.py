"""Committed state transitions for the OSAHR runtime event loop."""

from __future__ import annotations

import copy
from dataclasses import replace
from typing import TYPE_CHECKING, Any

from .boundary import (
    BoundaryDelta,
    BoundaryDirection,
    ExternalEvent,
    InputMode,
    OutputEvent,
)
from .canonical import stable_hash
from .errors import ReplayError, ResourceLimitError, ValidationError
from .events import EventKind, EventRecord
from .expr import evaluate_value, set_path
from .graph import GraphDelta
from .meta import MetaRuleAction, MetaRuleEvent
from .occurrence import OccurrenceKey
from .pattern import Rule
from .rng import RandomDraw
from .schedulers import SchedulerKind

if TYPE_CHECKING:
    from .runtime import PendingInternalEvent, Runtime, ScheduledAdaptation


def _advance(rt: Runtime, post_time: float) -> None:
    rt.time = post_time
    rt.last_event_time = post_time
    rt.event_index += 1
    rt._validate_limits()
    rt._record_event_time()


def _event_id(rt: Runtime, kind: EventKind, **payload: Any) -> str:
    return stable_hash(
        {
            "run_id": rt.run_id,
            "event_index": rt.event_index,
            "kind": kind.value,
            **payload,
        }
    )


def _survival_cause(
    rt: Runtime, cause: dict[str, Any], survival_integral: float | None
) -> dict[str, Any]:
    cause["post_graph_epoch"] = rt.graph.epoch
    cause["scheduler"] = rt.scheduler_kind.value
    cause["survival_integral_exact"] = survival_integral is not None
    if survival_integral is not None:
        cause["survival_integral"] = survival_integral
    return cause


def _append_record(
    rt: Runtime,
    *,
    kind: EventKind,
    event_id: str,
    pre_time: float,
    pre_hash: str,
    cause: dict[str, Any],
    draws: list[RandomDraw],
    graph_delta: GraphDelta,
    parameter_before: dict[str, Any],
    memory_before: dict[str, Any],
    boundary_delta: BoundaryDelta | None = None,
    outputs: list[OutputEvent] | None = None,
) -> EventRecord:
    record = EventRecord(
        event_id=event_id,
        event_index=rt.event_index,
        kind=kind,
        pre_time=pre_time,
        post_time=rt.time,
        delta_time=rt.time - pre_time,
        cause=cause,
        random_draws=draws,
        graph_delta=graph_delta,
        boundary_delta=boundary_delta or BoundaryDelta(),
        parameter_before=parameter_before,
        parameter_after=copy.deepcopy(rt.parameters),
        memory_before=memory_before,
        memory_after=copy.deepcopy(rt.memory),
        pre_state_hash=pre_hash,
        post_state_hash=rt.state_hash,
        outputs=list(outputs or ()),
    )
    rt.event_log.append(record)
    return record


def _require_rule(rt: Runtime, rule_id: str) -> Rule:
    try:
        return rt.rules[rule_id]
    except KeyError as exc:
        raise ValidationError(f"Unknown rule {rule_id!r}") from exc


def fire_internal(rt: Runtime, pending: PendingInternalEvent) -> EventRecord:
    occurrence = pending.occurrence
    if any(
        entity_id not in rt.graph.vertices
        for entity_id in occurrence.match.vertex_map.values()
    ):
        raise ReplayError("Pending internal event became invalid without a state transition")
    pre_time = rt.last_event_time
    pre_hash = rt._state_hash_at(pre_time)
    post_time = pending.absolute_time
    if post_time < pre_time:
        raise ReplayError("Pending internal event lies in the past")
    next_index = rt.event_index + 1
    event_id = stable_hash(
        {
            "run_id": rt.run_id,
            "event_index": next_index,
            "kind": EventKind.INTERNAL_REWRITE.value,
            "rule": occurrence.rule.rule_id,
            "match": occurrence.match.match_id,
        }
    )

    result = rt.rewrite_engine.apply(
        graph=rt.graph,
        boundary=rt.boundary,
        parameters=rt.parameters,
        memory=rt.memory,
        rule=occurrence.rule,
        match=occurrence.match,
        time=post_time,
        delta_time=post_time - pre_time,
        event_index=next_index,
        event_id=event_id,
    )
    result = rt._normalize_rewrite_result(result)
    rt.graph = result.graph
    rt.boundary = result.boundary
    rt.parameters = result.parameters
    rt.memory = result.memory
    rt.output_events.extend(result.outputs)
    _advance(rt, post_time)

    extra_draws = rt._post_commit_refresh(
        delta=result.graph_delta,
        state_changed=(
            result.parameter_before != result.parameter_after
            or result.memory_before != result.memory_after
        ),
        boundary_changed=not result.boundary_delta.is_empty(),
        fired_key=(
            OccurrenceKey(occurrence.rule.rule_id, occurrence.match.match_id)
            if rt.scheduler_kind is SchedulerKind.NEXT_REACTION
            else None
        ),
    )
    cause: dict[str, Any] = {
        "rule_id": occurrence.rule.rule_id,
        "rule_version": occurrence.rule.version,
        "rule_hash": occurrence.rule.hash,
        "match_id": occurrence.match.match_id,
        "vertex_map": occurrence.match.vertex_map,
        "edge_map": occurrence.match.edge_map,
        "hazard": occurrence.hazard,
        "pre_total_activity": pending.total_activity,
        "scheduler": pending.scheduler_kind.value,
        "post_graph_epoch": rt.graph.epoch,
    }
    if pending.survival_integral_exact:
        survival = (
            pending.survival_integral
            if pending.survival_integral is not None
            else pending.total_activity * (post_time - pre_time)
        )
        cause["survival_integral"] = survival
        cause["survival_integral_exact"] = True
    else:
        cause["survival_integral_exact"] = False

    return _append_record(
        rt,
        kind=EventKind.INTERNAL_REWRITE,
        event_id=event_id,
        pre_time=pre_time,
        pre_hash=pre_hash,
        cause=cause,
        draws=pending.draws + extra_draws,
        graph_delta=result.graph_delta,
        parameter_before=result.parameter_before,
        memory_before=result.memory_before,
        boundary_delta=result.boundary_delta,
        outputs=result.outputs,
    )


def process_external(
    rt: Runtime,
    event: ExternalEvent,
    draws: list[RandomDraw],
    survival_integral: float | None,
) -> EventRecord:
    handle = rt.boundary.handles[event.handle_id]
    if handle.direction not in {BoundaryDirection.INPUT, BoundaryDirection.BIDIRECTIONAL}:
        raise ValidationError(f"Boundary handle {event.handle_id!r} does not accept input")
    handle.validate_payload(event.payload)
    pre_time = rt.last_event_time
    pre_hash = rt._state_hash_at(pre_time)
    parameter_before = copy.deepcopy(rt.parameters)
    memory_before = copy.deepcopy(rt.memory)
    delta = GraphDelta()

    if handle.input_mode is not InputMode.SIGNAL_ONLY:
        if handle.binding is None:
            raise ValidationError(f"Input handle {event.handle_id!r} is unbound")
        before, after = rt.graph.set_vertex_attributes(
            handle.binding,
            event.payload,
            replace=handle.input_mode is InputMode.REPLACE_BOUND_VERTEX_ATTRIBUTES,
            increment_epoch=False,
        )
        if before != after:
            delta.updated_vertices_before[handle.binding] = before
            delta.updated_vertices_after[handle.binding] = after
            rt.graph.epoch += 1

    _advance(rt, event.simulation_time)
    extra_draws = rt._post_commit_refresh(
        delta=delta,
        state_changed=False,
        force=delta.is_empty(),
    )
    return _append_record(
        rt,
        kind=EventKind.EXTERNAL_INPUT,
        event_id=_event_id(rt, EventKind.EXTERNAL_INPUT, external_event_id=event.event_id),
        pre_time=pre_time,
        pre_hash=pre_hash,
        cause=_survival_cause(
            rt,
            {
                "external_event_id": event.event_id,
                "source_namespace": event.source_namespace,
                "source_sequence": event.source_sequence,
                "handle_id": event.handle_id,
                "payload": event.payload,
                "bound_vertex": handle.binding,
            },
            survival_integral,
        ),
        draws=draws + extra_draws,
        graph_delta=delta,
        parameter_before=parameter_before,
        memory_before=memory_before,
    )


def process_scheduled_adaptation(
    rt: Runtime,
    update: ScheduledAdaptation,
    draws: list[RandomDraw],
    survival_integral: float | None,
) -> EventRecord:
    pre_time = rt.last_event_time
    pre_hash = rt._state_hash_at(pre_time)
    parameter_before = copy.deepcopy(rt.parameters)
    memory_before = copy.deepcopy(rt.memory)
    context = {
        "p": rt.parameters,
        "parameters": rt.parameters,
        "z": rt.memory,
        "memory": rt.memory,
        "time": update.simulation_time,
        "delta_time": update.simulation_time - pre_time,
        "payload": {},
    }
    next_parameters = copy.deepcopy(rt.parameters)
    next_memory = copy.deepcopy(rt.memory)
    for assignment in update.assignments:
        root, path = assignment.target.split(".", 1)
        set_path(
            next_parameters if root == "parameters" else next_memory,
            path,
            evaluate_value(assignment.value, context),
        )
    rt.parameters = rt.adaptive_registry.normalize(next_parameters)
    rt.memory = next_memory
    _advance(rt, update.simulation_time)
    extra_draws = rt._post_commit_refresh(
        delta=GraphDelta(),
        state_changed=True,
        force=True,
    )
    return _append_record(
        rt,
        kind=EventKind.SCHEDULED_ADAPTATION,
        event_id=_event_id(rt, EventKind.SCHEDULED_ADAPTATION, update_id=update.update_id),
        pre_time=pre_time,
        pre_hash=pre_hash,
        cause=_survival_cause(rt, {"update_id": update.update_id}, survival_integral),
        draws=draws + extra_draws,
        graph_delta=GraphDelta(),
        parameter_before=parameter_before,
        memory_before=memory_before,
    )


def process_meta(
    rt: Runtime,
    event: MetaRuleEvent,
    draws: list[RandomDraw],
    survival_integral: float | None,
) -> EventRecord:
    pre_time = rt.last_event_time
    pre_hash = rt._state_hash_at(pre_time)
    parameter_before = copy.deepcopy(rt.parameters)
    memory_before = copy.deepcopy(rt.memory)
    before_rules = rt._rule_state_canonical()
    rule_after: Rule | None = None

    if event.action is MetaRuleAction.INSTANTIATE:
        assert event.template_id is not None
        try:
            template = rt.rule_templates[event.template_id]
        except KeyError as exc:
            raise ValidationError(f"Unknown rule template {event.template_id!r}") from exc
        if event.rule_id in rt.rules:
            raise ValidationError(f"Rule {event.rule_id!r} already exists")
        instance_count = sum(
            1
            for rule in rt.rules.values()
            if rule.meta.get("__osahr_template_id") == template.template_id
        )
        if instance_count >= template.max_instances:
            raise ResourceLimitError(
                f"Template {template.template_id!r} reached max_instances"
            )
        rule_after = template.instantiate(event.rule_id, event.bindings)
        rule_after = replace(
            rule_after,
            meta={
                **rule_after.meta,
                "__osahr_template_id": template.template_id,
            },
        )
        rt.rules[event.rule_id] = rule_after
    elif event.action is MetaRuleAction.ENABLE:
        rule_after = replace(_require_rule(rt, event.rule_id), enabled=True)
        rt.rules[event.rule_id] = rule_after
    elif event.action is MetaRuleAction.DISABLE:
        rule_after = replace(_require_rule(rt, event.rule_id), enabled=False)
        rt.rules[event.rule_id] = rule_after
    elif event.action is MetaRuleAction.REMOVE:
        _require_rule(rt, event.rule_id)
        rt.rules.pop(event.rule_id)
        rt.occurrence_index.invalidate_rule(event.rule_id)
    else:  # pragma: no cover
        raise ValidationError(f"Unsupported meta action {event.action}")

    rt._validate_scheduler_contract()
    _advance(rt, event.simulation_time)
    extra_draws = rt._post_commit_refresh(
        delta=GraphDelta(),
        state_changed=True,
        force=True,
    )
    return _append_record(
        rt,
        kind=EventKind.META_RULE_UPDATE,
        event_id=_event_id(rt, EventKind.META_RULE_UPDATE, meta_event_id=event.event_id),
        pre_time=pre_time,
        pre_hash=pre_hash,
        cause=_survival_cause(
            rt,
            {
                "meta_event_id": event.event_id,
                "action": event.action.value,
                "rule_id": event.rule_id,
                "template_id": event.template_id,
                "bindings": dict(event.bindings),
                "rules_before": before_rules,
                "rules_after": rt._rule_state_canonical(),
                "rule_after": rule_after,
            },
            survival_integral,
        ),
        draws=draws + extra_draws,
        graph_delta=GraphDelta(),
        parameter_before=parameter_before,
        memory_before=memory_before,
    )
