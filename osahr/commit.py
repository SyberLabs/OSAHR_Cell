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
    from .runtime import PendingInternalEvent, ScheduledAdaptation


class RuntimeCommitMixin:

    def _advance(self, post_time: float) -> None:
        self.time = post_time
        self.last_event_time = post_time
        self.event_index += 1
        self._validate_limits()
        self._record_event_time()

    def _event_id(self, kind: EventKind, **payload: Any) -> str:
        return stable_hash(
            {
                "run_id": self.run_id,
                "event_index": self.event_index,
                "kind": kind.value,
                **payload,
            }
        )

    def _survival_cause(
        self, cause: dict[str, Any], survival_integral: float | None
    ) -> dict[str, Any]:
        cause["post_graph_epoch"] = self.graph.epoch
        cause["scheduler"] = self.scheduler_kind.value
        cause["survival_integral_exact"] = survival_integral is not None
        if survival_integral is not None:
            cause["survival_integral"] = survival_integral
        return cause

    def _append_record(
        self,
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
        parameter_after: dict[str, Any] | None = None,
        memory_after: dict[str, Any] | None = None,
        outputs: list[OutputEvent] | None = None,
    ) -> EventRecord:
        record = EventRecord(
            event_id=event_id,
            event_index=self.event_index,
            kind=kind,
            pre_time=pre_time,
            post_time=self.time,
            delta_time=self.time - pre_time,
            cause=cause,
            random_draws=draws,
            graph_delta=graph_delta,
            boundary_delta=boundary_delta if boundary_delta is not None else BoundaryDelta(),
            parameter_before=parameter_before,
            parameter_after=(
                copy.deepcopy(self.parameters) if parameter_after is None else parameter_after
            ),
            memory_before=memory_before,
            memory_after=copy.deepcopy(self.memory) if memory_after is None else memory_after,
            pre_state_hash=pre_hash,
            post_state_hash=self.state_hash,
            outputs=list(outputs or ()),
        )
        self.event_log.append(record)
        return record

    def _require_rule(self, rule_id: str) -> Rule:
        try:
            return self.rules[rule_id]
        except KeyError as exc:
            raise ValidationError(f"Unknown rule {rule_id!r}") from exc

    def _fire_internal(self, pending: PendingInternalEvent) -> EventRecord:
        occurrence = pending.occurrence
        if any(
            entity_id not in self.graph.vertices
            for entity_id in occurrence.match.vertex_map.values()
        ):
            raise ReplayError("Pending internal event became invalid without a state transition")
        pre_time = self.last_event_time
        pre_hash = self._state_hash_at(pre_time)
        post_time = pending.absolute_time
        if post_time < pre_time:
            raise ReplayError("Pending internal event lies in the past")
        next_index = self.event_index + 1
        event_id = stable_hash(
            {
                "run_id": self.run_id,
                "event_index": next_index,
                "kind": EventKind.INTERNAL_REWRITE.value,
                "rule": occurrence.rule.rule_id,
                "match": occurrence.match.match_id,
            }
        )

        result = self.rewrite_engine.apply(
            graph=self.graph,
            boundary=self.boundary,
            parameters=self.parameters,
            memory=self.memory,
            rule=occurrence.rule,
            match=occurrence.match,
            time=post_time,
            delta_time=post_time - pre_time,
            event_index=next_index,
            event_id=event_id,
        )
        result = self._normalize_rewrite_result(result)
        self.graph = result.graph
        self.boundary = result.boundary
        self.parameters = result.parameters
        self.memory = result.memory
        self.output_events.extend(result.outputs)
        self._advance(post_time)

        extra_draws = self._post_commit_refresh(
            delta=result.graph_delta,
            state_changed=(
                result.parameter_before != result.parameter_after
                or result.memory_before != result.memory_after
            ),
            boundary_changed=not result.boundary_delta.is_empty(),
            fired_key=(
                OccurrenceKey(occurrence.rule.rule_id, occurrence.match.match_id)
                if self.scheduler_kind is SchedulerKind.NEXT_REACTION
                else None
            ),
        )
        if pending.scheduler_kind is SchedulerKind.NEXT_REACTION:
            # _post_commit_refresh already drained; keep pre-commit draws plus extras.
            random_draws = pending.draws + self.next_reaction.drain_audit_draws() + extra_draws
        else:
            random_draws = pending.draws + extra_draws

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
            "post_graph_epoch": self.graph.epoch,
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

        return self._append_record(
            kind=EventKind.INTERNAL_REWRITE,
            event_id=event_id,
            pre_time=pre_time,
            pre_hash=pre_hash,
            cause=cause,
            draws=random_draws,
            graph_delta=result.graph_delta,
            parameter_before=result.parameter_before,
            memory_before=result.memory_before,
            boundary_delta=result.boundary_delta,
            parameter_after=result.parameter_after,
            memory_after=result.memory_after,
            outputs=result.outputs,
        )

    def _process_external(
        self,
        event: ExternalEvent,
        draws: list[RandomDraw],
        survival_integral: float | None,
    ) -> EventRecord:
        handle = self.boundary.handles[event.handle_id]
        if handle.direction not in {BoundaryDirection.INPUT, BoundaryDirection.BIDIRECTIONAL}:
            raise ValidationError(f"Boundary handle {event.handle_id!r} does not accept input")
        handle.validate_payload(event.payload)
        pre_time = self.last_event_time
        pre_hash = self._state_hash_at(pre_time)
        parameter_before = copy.deepcopy(self.parameters)
        memory_before = copy.deepcopy(self.memory)
        delta = GraphDelta()

        if handle.input_mode is not InputMode.SIGNAL_ONLY:
            if handle.binding is None:
                raise ValidationError(f"Input handle {event.handle_id!r} is unbound")
            before, after = self.graph.set_vertex_attributes(
                handle.binding,
                event.payload,
                replace=handle.input_mode is InputMode.REPLACE_BOUND_VERTEX_ATTRIBUTES,
                increment_epoch=False,
            )
            if before != after:
                delta.updated_vertices_before[handle.binding] = before
                delta.updated_vertices_after[handle.binding] = after
                self.graph.epoch += 1

        self._advance(event.simulation_time)
        extra_draws = self._post_commit_refresh(
            delta=delta,
            state_changed=False,
            force=delta.is_empty(),
        )
        return self._append_record(
            kind=EventKind.EXTERNAL_INPUT,
            event_id=self._event_id(
                EventKind.EXTERNAL_INPUT, external_event_id=event.event_id
            ),
            pre_time=pre_time,
            pre_hash=pre_hash,
            cause=self._survival_cause(
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

    def _process_scheduled_adaptation(
        self,
        update: ScheduledAdaptation,
        draws: list[RandomDraw],
        survival_integral: float | None,
    ) -> EventRecord:
        pre_time = self.last_event_time
        pre_hash = self._state_hash_at(pre_time)
        parameter_before = copy.deepcopy(self.parameters)
        memory_before = copy.deepcopy(self.memory)
        context = {
            "p": self.parameters,
            "parameters": self.parameters,
            "z": self.memory,
            "memory": self.memory,
            "time": update.simulation_time,
            "delta_time": update.simulation_time - pre_time,
            "payload": {},
        }
        next_parameters = copy.deepcopy(self.parameters)
        next_memory = copy.deepcopy(self.memory)
        for assignment in update.assignments:
            root, path = assignment.target.split(".", 1)
            set_path(
                next_parameters if root == "parameters" else next_memory,
                path,
                evaluate_value(assignment.value, context),
            )
        self.parameters = self.adaptive_registry.normalize(next_parameters)
        self.memory = next_memory
        self._advance(update.simulation_time)
        extra_draws = self._post_commit_refresh(
            delta=GraphDelta(),
            state_changed=True,
            force=True,
        )
        return self._append_record(
            kind=EventKind.SCHEDULED_ADAPTATION,
            event_id=self._event_id(
                EventKind.SCHEDULED_ADAPTATION, update_id=update.update_id
            ),
            pre_time=pre_time,
            pre_hash=pre_hash,
            cause=self._survival_cause({"update_id": update.update_id}, survival_integral),
            draws=draws + extra_draws,
            graph_delta=GraphDelta(),
            parameter_before=parameter_before,
            memory_before=memory_before,
        )

    def _process_meta(
        self,
        event: MetaRuleEvent,
        draws: list[RandomDraw],
        survival_integral: float | None,
    ) -> EventRecord:
        pre_time = self.last_event_time
        pre_hash = self._state_hash_at(pre_time)
        parameter_before = copy.deepcopy(self.parameters)
        memory_before = copy.deepcopy(self.memory)
        before_rules = self._rule_state_canonical()
        rule_after: Rule | None = None

        if event.action is MetaRuleAction.INSTANTIATE:
            assert event.template_id is not None
            try:
                template = self.rule_templates[event.template_id]
            except KeyError as exc:
                raise ValidationError(f"Unknown rule template {event.template_id!r}") from exc
            if event.rule_id in self.rules:
                raise ValidationError(f"Rule {event.rule_id!r} already exists")
            instance_count = sum(
                1
                for rule in self.rules.values()
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
            self.rules[event.rule_id] = rule_after
        elif event.action is MetaRuleAction.ENABLE:
            rule_after = replace(self._require_rule(event.rule_id), enabled=True)
            self.rules[event.rule_id] = rule_after
        elif event.action is MetaRuleAction.DISABLE:
            rule_after = replace(self._require_rule(event.rule_id), enabled=False)
            self.rules[event.rule_id] = rule_after
        elif event.action is MetaRuleAction.REMOVE:
            self._require_rule(event.rule_id)
            self.rules.pop(event.rule_id)
            self.occurrence_index.invalidate_rule(event.rule_id)
        else:  # pragma: no cover
            raise ValidationError(f"Unsupported meta action {event.action}")

        self._validate_scheduler_contract()
        self._advance(event.simulation_time)
        extra_draws = self._post_commit_refresh(
            delta=GraphDelta(),
            state_changed=True,
            force=True,
        )
        return self._append_record(
            kind=EventKind.META_RULE_UPDATE,
            event_id=self._event_id(
                EventKind.META_RULE_UPDATE, meta_event_id=event.event_id
            ),
            pre_time=pre_time,
            pre_hash=pre_hash,
            cause=self._survival_cause(
                {
                    "meta_event_id": event.event_id,
                    "action": event.action.value,
                    "rule_id": event.rule_id,
                    "template_id": event.template_id,
                    "bindings": dict(event.bindings),
                    "rules_before": before_rules,
                    "rules_after": self._rule_state_canonical(),
                    "rule_after": rule_after,
                },
                survival_integral,
            ),
            draws=draws + extra_draws,
            graph_delta=GraphDelta(),
            parameter_before=parameter_before,
            memory_before=memory_before,
        )
