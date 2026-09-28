"""Single-operator durable execution using the existing SnapshotStore.

Local storage, configuration, adapters and verifier are trusted. Candidates do
not receive this object. The OS lease prevents concurrent coordinators; short
store transactions permit operator cancellation while a provider is in flight.
This is not a public multi-tenant authorization service or a legacy graph writer.
"""
from __future__ import annotations

import time
import hashlib
from dataclasses import asdict
from pathlib import Path

from ..snapshot import SnapshotStore, _StateLock
from .codec import decode, encode
from .journal import private_root
from .records import (AcceptedState, Candidate, Decision, Evidence, JsonSnapshot,
                      Limits, Observation, Permission, digest, integer, text)
from .runtime import ExecutionBlocked, PreviewRuntime

CHECKPOINT_SCHEMA = 1
_FIELDS = ("_started", "_last_time", "_epoch", "_revision", "_canceled", "_paused", "_breach",
           "_steps", "_calls", "_dependencies", "_journal", "_observations",
           "_candidates", "_evidence", "_accepted")


def configuration(*, run_id, workflow_id, permission, dependencies, limits, chooser, workers, verifier):
    package = Path(__file__).parent
    # Pin replay engine, adapters, built-in workflows, and storage semantics.
    # Built-in verifier code is covered here or by its source-derived checker_id.
    implementation = {name: hashlib.sha256((package / name).read_bytes()).hexdigest() for name in (
        "runtime.py", "durable.py", "records.py", "ports.py", "codec.py", "journal.py",
        "providers.py", "http_worker.py", "../snapshot.py", "workflows.py", "examples.py")}
    return {"implementation": implementation, "run_id": run_id, "workflow_id": workflow_id, "permission": encode(permission),
            "dependencies": encode(dependencies), "limits": encode(limits),
            "chooser": [chooser.id, chooser.mode],
            "workers": {key: [value.id, value.mode] for key, value in sorted(workers.items())},
            "contract": asdict(verifier.contract) | {"required": list(verifier.contract.required)},
            "verifier_mode": verifier.mode}


class DurableRuntime(PreviewRuntime):
    """Restartable six-operation runtime. Use as a context manager to release its lease."""

    def __init__(self, *, state_dir: Path, run_id: str, workflow_id: str,
                 permission: Permission, dependencies: JsonSnapshot, chooser,
                 workers: dict, verifier, limits: Limits = Limits(), allow_live: bool = False,
                 clock=time.time):
        text(run_id)
        text(workflow_id)
        if type(allow_live) is not bool:
            raise ValueError("explicit Boolean live authorization required")
        self._permitted_modes = ("offline", "isolated", "live") if allow_live else ("offline", "isolated")
        if any(item.mode == "live" for item in (chooser, *workers.values())):
            if not allow_live:
                raise ExecutionBlocked("live provider execution not authorized")
            if verifier.mode not in ("isolated", "data_only"):
                raise ExecutionBlocked("live generation requires isolated or data-only verifier")
        if verifier.mode == "data_only":
            self._permitted_modes += ("data_only",)
        super().__init__(permission=permission, dependencies=dependencies, chooser=chooser,
                         workers=workers, verifier=verifier, limits=limits, clock=clock)
        self._config = configuration(run_id=run_id, workflow_id=workflow_id, permission=permission,
                                     dependencies=dependencies, limits=limits, chooser=chooser,
                                     workers=workers, verifier=verifier)
        self._config_hash = digest(self._config)
        self._store = SnapshotStore(private_root(Path(state_dir)))
        self._lease = _StateLock(self._store.root / ".execution-owner.lock")
        self._closed = False
        self._lease.__enter__()
        try:
            saved = self._store.load_execution()
            if saved is not None:
                self._restore(saved)
            self._checkpoint("open")
        except BaseException:
            self.close()
            raise

    def _document(self):
        return {"schema": CHECKPOINT_SCHEMA, "configuration": self._config,
                "configuration_hash": self._config_hash,
                "state": {key: encode(getattr(self, key)) for key in _FIELDS},
                "decisions": [encode(item) for item in sorted(self._decisions, key=repr)]}

    def _restore(self, document):
        if (set(document) != {"schema", "configuration", "configuration_hash", "state", "decisions"}
                or document["schema"] != CHECKPOINT_SCHEMA
                or document["configuration_hash"] != digest(document["configuration"])
                or document["configuration_hash"] != self._config_hash):
            raise ExecutionBlocked("checkpoint configuration or version mismatch")
        if type(document["state"]) is not dict or set(document["state"]) != set(_FIELDS):
            raise ExecutionBlocked("checkpoint state fields mismatch")
        state = {key: decode(value) for key, value in document["state"].items()}
        for key in ("_epoch", "_revision", "_steps", "_calls"):
            integer(state[key])
        for key in ("_canceled", "_paused", "_breach"):
            if type(state[key]) is not bool:
                raise ExecutionBlocked("invalid checkpoint flag")
        for key, kind in (("_observations", Observation), ("_candidates", Candidate), ("_evidence", Evidence)):
            if type(state[key]) is not dict or any(type(item) is not kind or identity != item.identity
                                                  for identity, item in state[key].items()):
                raise ExecutionBlocked("checkpoint record identity mismatch")
        if type(state["_dependencies"]) is not JsonSnapshot:
            raise ExecutionBlocked("invalid checkpoint dependencies")
        accepted = state["_accepted"]
        if (type(accepted) is not list or any(type(item) is not AcceptedState for item in accepted)
                or [item.revision for item in accepted] != list(range(1, state["_revision"] + 1))):
            raise ExecutionBlocked("invalid admission history")
        journal = state["_journal"]
        if type(journal) is not dict or len(journal) > self._limits.max_steps:
            raise ExecutionBlocked("invalid journal size")
        for step, row in list(journal.items()):
            text(step)
            if (type(row) is not dict or not {"operation", "binding", "status", "reserved", "actual", "result"} <= set(row)
                    or row["status"] not in ("started", "complete", "outcome_unknown")):
                raise ExecutionBlocked("invalid journal row")
            integer(row["reserved"])
            if row["actual"] is not None:
                integer(row["actual"])
            if row["status"] == "started":
                if row["operation"] in ("read", "admit", "yield"):
                    # These operations have no separately committed external effects.
                    # Their result and state change share the same generation commit.
                    del journal[step]
                else:
                    row["status"] = "outcome_unknown"
        decisions = [decode(item) for item in document["decisions"]]
        if any(type(item) is not Decision for item in decisions):
            raise ExecutionBlocked("invalid decision history")
        for key, value in state.items():
            setattr(self, key, value)
        self._decisions = set(decisions)
        self._active = False
        self._pending_step = None
        # _guard checks clock regression and original expiry before the next effect.

    def _checkpoint(self, stage: str) -> None:
        if not hasattr(self, "_store"):
            return
        if self._closed or self._faulted:
            raise ExecutionBlocked("runtime closed or faulted")
        try:
            self._store.save_execution(self._document())
        except BaseException:
            self._faulted = True
            raise

    def close(self):
        if not self._closed:
            self._closed = True
            self._lease.__exit__(None, None, None)

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()

    def _guard(self, effect, *, count=False):
        if getattr(self, "_closed", False):
            raise ExecutionBlocked("runtime closed")
        super()._guard(effect, count=count)

    def _assurance(self):
        return {"isolated": "isolated_contract_checked", "data_only": "data_contract_checked"}.get(
            self._verifier.mode, "offline_preview")

    def audit(self):
        result = super().audit()
        live = any(item.mode == "live" for item in (self._chooser, *self._workers.values()))
        result.update(durable=True, live_execution_enabled=live,
                      run_id=self._config["run_id"], workflow_id=self._config["workflow_id"],
                      configuration_hash=self._config_hash,
                      admission_scope="execution_receipt_not_legacy_graph_or_deployment",
                      verification_mode=self._verifier.mode,
                      assurance="internal_contract_preview" if live else "offline_preview")
        for item in result["accepted"]:
            item["currently_applicable"] = item["dependency_hash"] == self._dependencies.identity
        return result


def control(state_dir: Path, action: str) -> None:
    """Operator-only cancellation/revocation; no provider call or automatic replay.

    May run while the coordinator holds its lease. Its next commit loses CAS and
    fails closed. A received-but-unpersisted reply then remains outcome-unknown.
    """
    if action not in ("cancel", "revoke"):
        raise ValueError("only cancel/revoke are supported")
    store = SnapshotStore(private_root(Path(state_dir)))
    with store.locked():
        document = store.load_execution()
        if document is None:
            raise ExecutionBlocked("run does not exist")
        state = document["state"]
        if action == "cancel":
            state["_canceled"] = True
        else:
            integer(state["_epoch"])
            state["_epoch"] += 1
        store.save_execution(document)


def inspect_state(state_dir: Path) -> dict:
    store = SnapshotStore(private_root(Path(state_dir)))
    value = store.load_execution()
    if value is None:
        raise ExecutionBlocked("run does not exist")
    return value
