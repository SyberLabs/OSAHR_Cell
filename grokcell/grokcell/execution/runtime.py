"""Executable, in-memory reference semantics. NOT a production execution boundary.

Only trusted offline adapters are accepted. No generated code is executed here.
The journal supports same-process replay, not restart or power-loss durability.
"""
from __future__ import annotations

import math
import threading
import time
from dataclasses import asdict
from typing import Callable

from .ports import DecisionAdapter, Reply, Verifier, WorkerAdapter
from .records import (AcceptedState, ActionOffer, Candidate, Decision, Evidence,
                      JsonSnapshot, Limits, Observation, Permission, digest, integer, text)


class ExecutionBlocked(RuntimeError):
    pass


class OutcomeUnknown(ExecutionBlocked):
    pass


class PreviewRuntime:
    """Single-run harness. Configuration and every callback are trusted host code.

    Logical byte/call/step/deadline checks are implemented; callbacks are not
    preempted. Production needs an isolated executor and a durable state backend.
    """

    def __init__(self, *, permission: Permission, dependencies: JsonSnapshot,
                 chooser: DecisionAdapter, workers: dict[str, WorkerAdapter],
                 verifier: Verifier, limits: Limits = Limits(),
                 clock: Callable[[], float] = time.time):
        for adapter in (chooser, verifier, *workers.values()):
            if adapter.mode != "offline":
                raise ExecutionBlocked("live adapters require the durable/isolation gates")
        self._permission, self._dependencies = permission, dependencies
        self._chooser, self._workers, self._verifier = chooser, dict(workers), verifier
        self._contract = verifier.contract
        self._limits, self._clock, self._started = limits, clock, clock()
        self._last_time = self._started
        self._epoch, self._revision = permission.epoch, 0
        self._canceled = self._paused = self._active = self._breach = False
        self._steps = self._calls = 0
        self._journal: dict[str, dict] = {}
        self._observations: dict[str, Observation] = {}
        self._decisions: set[Decision] = set()
        self._candidates: dict[str, Candidate] = {}
        self._evidence: dict[str, Evidence] = {}
        self._accepted: list[AcceptedState] = []
        self._lock = threading.RLock()

    def _guard(self, effect: str, *, count: bool = False):
        now = self._clock()
        if type(now) not in (int, float) or not math.isfinite(now) or now < self._last_time:
            raise ExecutionBlocked("invalid or regressed clock")
        self._last_time = now
        if self._canceled or self._epoch != self._permission.epoch:
            raise ExecutionBlocked("canceled or revoked")
        if self._paused:
            raise ExecutionBlocked("yielded; resume explicitly")
        if now >= self._permission.expires_at or now - self._started >= self._limits.max_seconds:
            raise ExecutionBlocked("expired")
        if effect not in self._permission.effects:
            raise ExecutionBlocked("effect not permitted: " + effect)
        if self._breach:
            raise ExecutionBlocked("accounting bound breached")
        if count:
            if self._steps >= self._limits.max_steps:
                raise ExecutionBlocked("step limit")
            self._steps += 1

    def _liability(self) -> int:
        return sum(row["actual"] if row["actual"] is not None else row["reserved"]
                   for row in self._journal.values())

    def _run(self, step: str, effect: str, binding: object, operation: Callable,
             *, reserve: int | None = None, fresh_revision: int | None = None):
        text(step)
        if reserve is not None:
            integer(reserve)
        key = digest([1, effect, binding, reserve])
        with self._lock:
            self._guard(effect, count=True)
            prior = self._journal.get(step)
            if prior:
                if prior["binding"] != key:
                    raise ExecutionBlocked("replay input mismatch")
                if prior["status"] != "complete":
                    raise OutcomeUnknown("unresolved step; never resend automatically")
                return prior["result"]
            if self._active:
                raise ExecutionBlocked("one operation in flight per preview run")
            if fresh_revision is not None and fresh_revision != self._revision:
                raise ExecutionBlocked("stale accepted-state revision")
            if reserve is not None:
                integer(reserve)
                if self._calls >= self._limits.max_calls:
                    raise ExecutionBlocked("call limit")
                if self._liability() + reserve > self._limits.max_microusd:
                    raise ExecutionBlocked("reservation exceeds budget")
                self._calls += 1
            row = {"operation": effect, "binding": key, "status": "started",
                   "reserved": reserve or 0, "actual": None, "result": None}
            self._journal[step] = row
            self._active = True
        try:
            result, actual = operation()
            if actual is not None:
                integer(actual)
            with self._lock:
                row.update(status="complete", result=result, actual=actual)
                self._active = False
                if actual is not None and actual > row["reserved"]:
                    self._breach = True
                # Keep the response/accounting even when it arrived after cancellation.
                self._guard(effect)
            return result
        except BaseException:
            with self._lock:
                if row["status"] == "started":
                    row["status"] = "outcome_unknown"
                self._active = False
            raise

    def _observation(self, observation: Observation):
        if self._observations.get(observation.identity) != observation:
            raise ExecutionBlocked("observation not issued by this run")
        if observation.dependency_hash != self._dependencies.identity:
            raise ExecutionBlocked("dependency snapshot changed")

    def _candidate(self, candidate: Candidate):
        if self._candidates.get(candidate.identity) != candidate:
            raise ExecutionBlocked("candidate not produced by this run")
        if candidate.dependency_hash != self._dependencies.identity:
            raise ExecutionBlocked("dependency snapshot changed")

    def read(self, step: str, value: JsonSnapshot) -> Observation:
        if len(value.raw) > self._limits.max_bytes:
            raise ExecutionBlocked("observation byte limit")

        def operation():
            result = Observation(value, self._dependencies.identity, self._revision)
            self._observations[result.identity] = result
            return result, 0

        return self._run(step, "read", [value.identity, self._dependencies.identity], operation)

    def decide(self, step: str, observation: Observation,
               offers: tuple[ActionOffer, ...], *, reserve_microusd: int = 0) -> Decision:
        self._observation(observation)
        offers = tuple(offers)
        if not offers or len({x.id for x in offers}) != len(offers):
            raise ExecutionBlocked("nonempty unique action offers required")
        if any(x.effect not in self._permission.effects for x in offers):
            raise ExecutionBlocked("offer exceeds permission")
        offers_hash = digest([asdict(x) for x in offers])

        def operation():
            reply = self._chooser.choose(observation, offers)
            if type(reply) is not Reply or type(reply.value) is not str:
                raise ExecutionBlocked("invalid decision reply")
            choice = next((x for x in offers if x.id == reply.value), None)
            if choice is None:
                raise ExecutionBlocked("decision outside permitted offers")
            result = Decision(observation.identity, offers_hash, choice, self._chooser.id)
            self._decisions.add(result)
            return result, reply.actual_microusd

        return self._run(step, "decide", [observation.identity, offers_hash, self._chooser.id],
                         operation, reserve=reserve_microusd,
                         fresh_revision=observation.state_revision)

    def call(self, step: str, observation: Observation, decision: Decision,
             request: JsonSnapshot, *, artifact_type: str,
             reserve_microusd: int = 0) -> Candidate:
        self._observation(observation)
        if decision not in self._decisions or decision.observation_hash != observation.identity:
            raise ExecutionBlocked("decision not bound to this observation")
        if len(request.raw) > self._limits.max_bytes:
            raise ExecutionBlocked("request byte limit")
        worker = self._workers.get(decision.choice.effect)
        if worker is None:
            raise ExecutionBlocked("no worker registered for effect")

        def operation():
            reply = worker.propose(request)
            if type(reply) is not Reply or type(reply.value) is not bytes:
                raise ExecutionBlocked("worker must return candidate bytes")
            if len(reply.value) > self._limits.max_bytes:
                raise ExecutionBlocked("candidate byte limit")
            result = Candidate(artifact_type, reply.value, observation.dependency_hash,
                               observation.state_revision, step)
            self._candidates[result.identity] = result
            return result, reply.actual_microusd

        binding = [observation.identity, asdict(decision), request.identity, artifact_type, worker.id]
        return self._run(step, decision.choice.effect, binding, operation,
                         reserve=reserve_microusd, fresh_revision=observation.state_revision)

    def check(self, step: str, candidate: Candidate) -> Evidence:
        self._candidate(candidate)
        if self._verifier.contract != self._contract:
            raise ExecutionBlocked("checker contract changed")
        contract_hash = digest(asdict(self._contract) | {"required": list(self._contract.required)})

        def operation():
            results = tuple(self._verifier.verify(candidate))
            names = tuple(x.id for x in results)
            if len(set(names)) != len(names) or set(names) != set(self._contract.required):
                raise ExecutionBlocked("missing, duplicate, or unexpected mandatory checks")
            result = Evidence(candidate.identity, contract_hash, self._contract.checker_id,
                              self._contract.environment_hash, results)
            self._evidence[result.identity] = result
            return result, 0

        return self._run(step, "check", [candidate.identity, contract_hash], operation,
                         fresh_revision=candidate.base_revision)

    def admit(self, step: str, candidate: Candidate, evidence: Evidence) -> AcceptedState:
        def validate():
            self._candidate(candidate)
            if self._verifier.contract != self._contract:
                raise ExecutionBlocked("checker contract changed")
            if self._evidence.get(evidence.identity) != evidence:
                raise ExecutionBlocked("evidence not issued by this verifier")
            if evidence.candidate_hash != candidate.identity:
                raise ExecutionBlocked("evidence belongs to another candidate")
            if any(x.status != "pass" for x in evidence.checks):
                raise ExecutionBlocked("mandatory check did not pass")

        with self._lock:
            validate()

        def operation():
            with self._lock:
                self._guard("admit")
                validate()
                if candidate.base_revision != self._revision:
                    raise ExecutionBlocked("stale accepted-state revision")
                result = AcceptedState(self._revision + 1, candidate.identity,
                                       evidence.identity, self._dependencies.identity)
                self._revision += 1
                self._accepted.append(result)
                return result, 0

        return self._run(step, "admit", [candidate.identity, evidence.identity], operation,
                         fresh_revision=candidate.base_revision)

    def yield_(self, step: str, reason: str) -> JsonSnapshot:
        text(reason)
        result = self._run(step, "yield", reason,
                           lambda: (JsonSnapshot.capture({"reason": reason}), 0))
        with self._lock:
            self._paused = True
        return result

    def resume(self):
        """Continue the same object; this is NOT process-restart recovery."""
        with self._lock:
            self._paused = False

    def cancel(self):
        with self._lock:
            self._canceled = True

    def revoke(self):
        with self._lock:
            self._epoch += 1

    def replace_dependencies(self, dependencies: JsonSnapshot):
        """Trusted operator hook; old evidence remains historical, not applicable."""
        with self._lock:
            self._dependencies = dependencies

    def audit(self) -> dict:
        with self._lock:
            return {"schema_version": 1, "assurance": "offline_preview",
                    "live_execution_enabled": False, "durable": False,
                    "revision": self._revision, "calls": self._calls, "steps": self._steps,
                    "liability_microusd": self._liability(), "bound_breached": self._breach,
                    "accepted": [asdict(x) | {"assurance": x.assurance} for x in self._accepted],
                    "journal": [{"step": name, **{k: v for k, v in row.items() if k != "result"}}
                                for name, row in self._journal.items()]}
