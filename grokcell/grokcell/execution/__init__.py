"""Provisional typed execution contract: preview and durable internal runtimes.

Live providers require explicit authorization. No receipt grants deployment or
legacy graph authority. See grokcell/EXECUTION.md for the supported trust scope.
"""
from .ports import CheckContract, DecisionAdapter, Reply, Verifier, WorkerAdapter
from .records import (SCHEMA_VERSION, AcceptedState, ActionOffer, Candidate, CheckResult,
                      Decision, Evidence, JsonSnapshot, Limits, Observation, Permission)
from .durable import DurableRuntime
from .runtime import ExecutionBlocked, OutcomeUnknown, PreviewRuntime

__all__ = [
    "SCHEMA_VERSION", "AcceptedState", "ActionOffer", "Candidate", "CheckContract",
    "CheckResult", "Decision", "DecisionAdapter", "Evidence", "ExecutionBlocked",
    "JsonSnapshot", "Limits", "Observation", "OutcomeUnknown", "Permission",
    "PreviewRuntime", "DurableRuntime", "Reply", "Verifier", "WorkerAdapter",
]
