"""Bounded repair experiment inside GrokCell; live execution requires explicit setup."""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import random
import shutil
import subprocess
import tempfile
import time
from pathlib import Path

from .artifact import Artifact, read_text_exact
from .fidelity import FidelityStore
from .messages import Message
from .repair_adapters import JevChoice, QwenBuilder
from .repair_fixture import (COMPONENTS, CONTRACT_ROOT, DEPENDENCIES, PUBLIC_END_TO_END,
                             SEED_SOURCES, SEED_VARIANT, VARIANTS)
from .repair_guard import validate_module
from .repair_memory import AttemptStore, simple_retrieve
from .repair_policy import DecisionState, digest, select_action, validate_choice
from .runner import DEADLINE_ENV, RunOutcome, SANDBOX_IMAGE_ENV, isolated_call, pytest_suite
from .surface import GrokCellSurface

ARMS = {"A": ("qwen", "none"), "B": ("deterministic", "none"),
        "C": ("jev", "none"), "D": ("jev", "simple"),
        "E": ("jev", "jev_mem")}
MIN_WORTHWHILE_GAIN = 0.20  # Design hypothesis, frozen before any live result.
CONTRACT_FILES = {component: (
    CONTRACT_ROOT / "held_out" / f"acceptance_hidden_{component}.py")
    for component in COMPONENTS}
PUBLIC_FILES = {component: (
    CONTRACT_ROOT / "public" / f"acceptance_public_{component}.py")
    for component in COMPONENTS}
HELD_E2E = CONTRACT_ROOT / "held_out" / "acceptance_hidden_end_to_end.py"
HELD_CASES = CONTRACT_ROOT / "held_out" / "cases.json"


def verify_contracts() -> dict[str, str]:
    result = {}
    for line in (CONTRACT_ROOT / "SHA256SUMS.txt").read_text(encoding="utf-8").splitlines():
        expected, relative = line.split("  ", 1)
        path = CONTRACT_ROOT / relative
        actual = hashlib.sha256(path.read_bytes()).hexdigest()
        if actual != expected:
            raise ValueError(f"frozen contract changed: {relative}")
        result[relative] = actual
    required = {"PUBLIC_CONTRACT.md", *(path.relative_to(CONTRACT_ROOT).as_posix()
                                          for path in (*PUBLIC_FILES.values(), *CONTRACT_FILES.values(), HELD_E2E, HELD_CASES))}
    if not required.issubset(result):
        raise ValueError("incomplete frozen contract")
    return result


def revision_name(component: str, artifact_hash: str, dependencies: list[str],
                  contract_hash: str, environment: str) -> str:
    return component.replace("_", ".") + ".r" + digest({
        "artifact": artifact_hash, "dependencies": dependencies,
        "contract": contract_hash, "environment": environment})


def _public_diagnostic(result) -> str:
    # Public only: never pass held-out traceback or test names to a provider.
    raw = (result.stdout + "\n" + result.stderr)[:6000]
    for key in ("HF_TOKEN", "TYPESAFE_API_KEY", "QWEN_API_KEY"):
        secret = os.environ.get(key)
        if secret:
            raw = raw.replace(secret, "[redacted]")
    return json.dumps({"outcome": result.outcome.value, "exit_code": result.exit_code,
                       "diagnostic": raw, "stdout_truncated": result.stdout_truncated,
                       "stderr_truncated": result.stderr_truncated})


def _failure_signature(detail: str) -> str:
    """Keep the diagnostic object _read_prior accepts, and wrap every other string."""
    required = {"outcome", "exit_code", "diagnostic", "stdout_truncated", "stderr_truncated"}
    try:
        parsed = json.loads(detail)
    except (json.JSONDecodeError, TypeError):
        parsed = None
    if (isinstance(parsed, dict) and set(parsed) == required
            and parsed.get("outcome") == "tests_failed"
            and isinstance(parsed.get("diagnostic"), str)
            and len(parsed["diagnostic"]) <= 6000):
        return detail
    text = detail if isinstance(detail, str) else ""
    return json.dumps({"outcome": "tests_failed", "exit_code": 1,
                       "diagnostic": text[:6000], "stdout_truncated": False,
                       "stderr_truncated": False})


def _strict_json(raw: str):
    return json.loads(raw, parse_constant=lambda value: (_ for _ in ()).throw(
        ValueError("nonfinite_json_number")))


class Budget:
    def __init__(self, values: dict) -> None:
        required = {"sandbox_image", "max_total_usd", "max_task_usd", "max_calls",
                    "max_total_calls", "max_output_tokens", "max_total_output_tokens",
                    "max_worker_attempts", "max_total_worker_attempts",
                    "max_retrieval_rounds", "max_total_retrieval_rounds",
                    "max_elapsed_seconds", "max_task_elapsed_seconds",
                    "max_input_tokens_per_call",
                    "qwen_input_usd_per_million", "qwen_output_usd_per_million",
                    "jev_input_usd_per_million", "jev_output_usd_per_million",
                    "executor_usd_per_second"}
        if set(values) != required:
            raise ValueError(f"budget fields must be exactly {sorted(required)}")
        self.config = values
        if (not isinstance(values["sandbox_image"], str)
                or "@sha256:" not in values["sandbox_image"]):
            raise ValueError("pinned sandbox image required")
        integer_fields = {"max_calls", "max_total_calls", "max_output_tokens",
                          "max_total_output_tokens", "max_worker_attempts",
                          "max_total_worker_attempts", "max_retrieval_rounds",
                          "max_total_retrieval_rounds", "max_input_tokens_per_call"}
        for key in required - {"sandbox_image"}:
            value = values[key]
            if (isinstance(value, bool) or not isinstance(value, (int, float))
                    or not math.isfinite(value) or value <= 0
                    or (key in integer_fields and type(value) is not int)):
                raise ValueError(f"positive budget value required: {key}")
        self.started = time.monotonic()
        self.task_started = self.started
        self.total_usd = 0.0
        self.task_usd = 0.0
        self.calls = 0
        self.output_tokens = 0
        self.executor_seconds = 0.0
        self.unknown_cost = False
        self.limit_breached = False

    def start_task(self) -> None:
        self.task_usd = 0.0
        self.task_started = time.monotonic()

    def remaining_seconds(self) -> float:
        return max(0.0, min(
            self.config["max_elapsed_seconds"] - (time.monotonic() - self.started),
            self.config["max_task_elapsed_seconds"] - (time.monotonic() - self.task_started)))

    def remaining_calls(self) -> int:
        return max(0, int(self.config["max_calls"]) - self.calls)

    def remaining_output_tokens(self) -> int:
        return max(0, int(self.config["max_output_tokens"]) - self.output_tokens)

    def _limit(self, dollars: float) -> None:
        if (self.unknown_cost or self.limit_breached
                or self.total_usd + dollars > self.config["max_total_usd"]
                or self.task_usd + dollars > self.config["max_task_usd"]
                or self.remaining_seconds() <= 0):
            raise RuntimeError("budget_exhausted_or_cost_unknown")

    def _worst_call_cost(self, provider: str, max_output: int) -> float:
        prefix = "qwen" if provider == "qwen" else "jev"
        return (self.config["max_input_tokens_per_call"] *
                self.config[f"{prefix}_input_usd_per_million"] +
                max_output * self.config[f"{prefix}_output_usd_per_million"]) / 1_000_000

    def can_call(self, provider: str, max_output: int) -> bool:
        return self.can_bundle(((provider, max_output),))

    def can_bundle(self, calls: tuple[tuple[str, int], ...]) -> bool:
        if (self.remaining_calls() < len(calls) or
                self.remaining_output_tokens() < sum(output for _, output in calls)):
            return False
        try:
            self._limit(sum(self._worst_call_cost(provider, output)
                            for provider, output in calls))
        except RuntimeError:
            return False
        return True

    def call(self, provider: str, max_output: int, operation):
        if not self.can_call(provider, max_output):
            raise RuntimeError("model_call_limit")
        prefix = "qwen" if provider == "qwen" else "jev"
        self.calls += 1
        try:
            reply = operation()
        except Exception:
            self.unknown_cost = True  # A failed external request may still be billed.
            raise
        usage = reply.usage
        input_count = usage.get("prompt_tokens", usage.get("input_tokens"))
        output_count = usage.get("completion_tokens", usage.get("output_tokens"))
        if (type(input_count) is not int or type(output_count) is not int
                or input_count < 0 or output_count < 0):
            self.unknown_cost = True
            raise RuntimeError("provider_usage_unavailable")
        cost = (input_count * self.config[f"{prefix}_input_usd_per_million"] +
                output_count * self.config[f"{prefix}_output_usd_per_million"]) / 1_000_000
        self.total_usd += cost
        self.task_usd += cost
        self.output_tokens += output_count
        if (input_count > self.config["max_input_tokens_per_call"]
                or output_count > max_output
                or self.output_tokens > self.config["max_output_tokens"]
                or self.task_usd > self.config["max_task_usd"]):
            self.limit_breached = True
            raise RuntimeError("provider_usage_or_spend_cap_breached")
        self._limit(0)
        return reply

    def executor(self, elapsed_ms: int) -> None:
        seconds = elapsed_ms / 1000
        cost = seconds * self.config["executor_usd_per_second"]
        self.executor_seconds += seconds
        self.total_usd += cost
        self.task_usd += cost
        if self.task_usd > self.config["max_task_usd"]:
            self.limit_breached = True
        self._limit(0)

    def reserve_executor(self, maximum_seconds: float, *, require_full: bool = False) -> None:
        if require_full and self.remaining_seconds() < maximum_seconds:
            raise RuntimeError("insufficient_time_for_admission")
        self._limit(min(maximum_seconds, self.remaining_seconds()) *
                    self.config["executor_usd_per_second"])

    def summary(self) -> dict:
        return {"estimated_total_usd": None if self.unknown_cost else self.total_usd,
                "cost_basis": "configured_token_tariffs_plus_executor_time_estimate",
                "calls": self.calls, "output_tokens": self.output_tokens,
                "executor_seconds": self.executor_seconds,
                "wall_seconds": time.monotonic() - self.task_started,
                "cost_unknown": self.unknown_cost,
                "limit_breached": self.limit_breached}


class _BudgetedChoice:
    def __init__(self, chooser, budget: Budget, provider: str):
        self.chooser, self.budget, self.provider = chooser, budget, provider
        self.min_confidence = getattr(chooser, "min_confidence", 0.0)

    def choose(self, **kwargs):
        self.chooser.timeout = min(self.chooser.timeout, self.budget.remaining_seconds())
        if self.chooser.timeout <= 0:
            raise RuntimeError("task_elapsed_limit")
        return self.budget.call(self.provider, 128 if self.provider == "qwen" else 512,
                                lambda: self.chooser.choose(**kwargs))


class Episode:
    def __init__(self, *, variant: str, arm: str, root: Path, budget: Budget,
                 prior_records: list[dict], contracts: dict[str, str],
                 resume: bool = False) -> None:
        if os.environ.get(SANDBOX_IMAGE_ENV) != budget.config["sandbox_image"]:
            raise RuntimeError("experiment_requires_pinned_sandbox")
        self.variant, self.arm, self.root, self.budget = variant, arm, root, budget
        self.root.mkdir(parents=True, exist_ok=True)
        self.state_root = root / "state"
        self.acceptance_root = root / "operator_acceptance"
        self.attempts = AttemptStore(self.state_root)
        unfinished = self.attempts.unfinished()
        # A started attempt may already have been sent. Resume closes it without
        # constructing this episode; proposal_ready can continue only explicitly.
        if any(item.get("status") == "started" for item in unfinished) or (
                any(item.get("status") == "proposal_ready" for item in unfinished) and not resume):
            raise RuntimeError("interrupted_attempt_requires_operator_review")
        self.surface = GrokCellSurface.open(
            fidelity=FidelityStore(root / "fidelity"), state=self.state_root)
        self.sources = dict(SEED_SOURCES if variant == SEED_VARIANT else VARIANTS[variant])
        for source in self.sources.values():
            validate_module(source)
        self.contracts = contracts
        self.candidate_tests = {component: self._frozen_text(PUBLIC_FILES[component])
                                for component in COMPONENTS}
        self.manifest: dict[str, str] = {}
        self.observations: list[dict] = []
        self.attempt_history: list[dict] = []
        self.prior_records = list(prior_records) if ARMS[arm][1] == "simple" else []
        self.evaluation_binding_inputs = None
        self.recalled: list[dict] = []
        for prior in self.prior_records:
            if self.attempts.path_for(prior["id"]).exists():
                if self.attempts.read(prior["id"]) != prior:
                    raise ValueError("prior_attempt_changed")
                continue
            self.attempts.write(prior)
        self.oracle = json.loads(self._frozen_text(HELD_CASES))
        self.retrievals = 0
        self.worker_attempts = 0
        input_cap = int(budget.config["max_input_tokens_per_call"])
        self.qwen = QwenBuilder(max_input_bytes=input_cap)
        self.jev = JevChoice(max_input_bytes=input_cap)

    def _frozen_text(self, path: Path) -> str:
        relative = path.relative_to(CONTRACT_ROOT).as_posix()
        raw = path.read_bytes()
        if hashlib.sha256(raw).hexdigest() != self.contracts[relative]:
            raise ValueError(f"frozen contract changed: {relative}")
        return raw.decode("utf-8")

    def _run_files(self, files: dict[str, str], *, public: bool) -> object:
        self.budget.reserve_executor(30)
        for name, source in files.items():
            if name in {"service.py", *(f"{part}.py" for part in COMPONENTS)}:
                validate_module(source)
        with tempfile.TemporaryDirectory(prefix="grokcell-repair-") as raw:
            folder = Path(raw)
            for name, content in files.items():
                (folder / name).write_text(content, encoding="utf-8", newline="")
            result = pytest_suite(folder, untrusted=True)
        self.budget.executor(result.elapsed_ms)
        if not public and result.outcome is not RunOutcome.PASS:
            # Hidden text stays in this trusted process and is never logged to prompts.
            return result.outcome.value
        return result

    def _host_oracle(self, component: str | None = None) -> tuple[str, str]:
        """Host compares exact outputs; candidate never receives expected values."""
        source_files = ({"service.py": self.sources[component]} if component else
                        {f"{name}.py": self.sources[name] for name in COMPONENTS})
        for source in source_files.values():
            validate_module(source)
        cases = [item for item in self.oracle["cases"]
                 if (item.get("scope") == "component" and item.get("component") == component)
                 or (component is None and item.get("scope") == "application")]
        with tempfile.TemporaryDirectory(prefix="grokcell-oracle-") as raw:
            folder = Path(raw)
            for name, source in source_files.items():
                (folder / name).write_text(source, encoding="utf-8", newline="")
            for item in cases:
                self.budget.reserve_executor(8)
                if component:
                    payload = {"scope": "component", "function":
                               self.oracle["component_entrypoints"][component],
                               "args": item["args"]}
                else:
                    payload = {"scope": "application", "raw_events": item["raw_events"],
                               "sku": item["sku"]}
                run, actual = isolated_call(folder, payload)
                self.budget.executor(run.elapsed_ms)
                if actual is None:
                    if run.outcome is RunOutcome.TESTS_FAILED:
                        return "tests_failed", "candidate_probe_exited"
                    return "infra_error", "trusted_probe_incomplete_" + run.outcome.value
                expected = item["expected"]
                for field in ("type", "value", "name", "args_after"):
                    if field not in expected:
                        continue
                    if json.dumps(actual.get(field), sort_keys=True, separators=(",", ":")) != json.dumps(
                            expected[field], sort_keys=True, separators=(",", ":")):
                        return "tests_failed", "operator_case_failed"
        return "pass", "operator_cases_passed"

    def _stage_operator_contract(self, component: str, revision: str) -> None:
        source = CONTRACT_FILES[component]
        relative = source.relative_to(CONTRACT_ROOT).as_posix()
        raw = source.read_bytes()
        if hashlib.sha256(raw).hexdigest() != self.contracts[relative]:
            raise ValueError("operator contract changed")
        directory = self.acceptance_root / revision
        directory.mkdir(parents=True, exist_ok=True)
        (directory / "test_acceptance.py").write_bytes(raw)
        (directory / "test_acceptance.sha256").write_text(
            hashlib.sha256(raw).hexdigest() + "\n", encoding="ascii")

    def _artifact_revision(self, component: str) -> tuple[Artifact, str, str] | None:
        if any(dep not in self.manifest for dep in DEPENDENCIES[component]):
            return None
        artifact = Artifact(name=component, source="payload", files={
            "service.py": self.sources[component],
            "test_service.py": self.candidate_tests[component]})
        contract_hash = self.contracts[
            CONTRACT_FILES[component].relative_to(CONTRACT_ROOT).as_posix()]
        revision = revision_name(component, artifact.digest(),
                                 [self.manifest[dep] for dep in DEPENDENCIES[component]],
                                 contract_hash, self.budget.config["sandbox_image"])
        return artifact, revision, contract_hash

    def _admit(self, component: str) -> tuple[str, str]:
        validate_module(self.sources[component])
        binding = self._artifact_revision(component)
        if binding is None:
            return "hold_unresolved", "missing_dependency_revision"
        artifact, revision, contract_hash = binding
        depends = [self.manifest[dep] for dep in DEPENDENCIES[component]]
        artifact_digest = artifact.digest()
        intent = self._read_admission_intent()
        if intent is not None:
            # A previous process may already have posted. Never post again unless
            # the surface license is this exact admitted revision.
            if (intent.get("component") == component and intent.get("revision") == revision
                    and intent.get("artifact_digest") == artifact_digest
                    and intent.get("contract_hash") == contract_hash
                    and self._exact_admitted(component, revision, artifact_digest, contract_hash)):
                self.manifest[component] = revision
                return "admit", "already_admitted_exact_revision"
            return "outcome_unknown", "admission_outcome_unknown"
        if revision in self.surface.components():
            stored = self.surface.artifacts.path_for(revision)
            license_record = self.surface.artifacts._read_license(stored)
            if (not stored.is_dir()
                    or self.surface.artifacts._current_digest(stored) != artifact_digest
                    or license_record.get("name") != revision
                    or license_record.get("license") != "admitted"
                    or license_record.get("hash") != artifact_digest
                    or license_record.get("acceptance_suite_hash") != contract_hash):
                raise RuntimeError("admitted_revision_changed")
            self.manifest[component] = revision
            return "admit", "already_admitted_exact_revision"
        # Baseline, mutant, operator suite, and operator mutant can each run
        # for 30 seconds plus container cleanup. Reserve before posting.
        self.budget.reserve_executor(180, require_full=True)
        self._stage_operator_contract(component, revision)
        self._write_admission_intent(component=component, revision=revision,
                                     artifact_digest=artifact_digest,
                                     contract_hash=contract_hash)
        message = Message(source_owner="MOUTH", kind="forge.propose", priority=1,
                          payload={"name": revision, "module": self.sources[component],
                                   "tests": self.candidate_tests[component],
                                   "constraint": "critical_module", "depends_on": depends})
        ack = self.surface.post(message)
        if not ack.queued:
            return "outcome_unknown", ack.reason
        started = time.monotonic()
        previous = os.environ.get("GROKCELL_ACCEPTANCE_DIR")
        os.environ["GROKCELL_ACCEPTANCE_DIR"] = str(self.acceptance_root)
        try:
            result = self.surface.drain()[0]
        finally:
            if previous is None:
                os.environ.pop("GROKCELL_ACCEPTANCE_DIR", None)
            else:
                os.environ["GROKCELL_ACCEPTANCE_DIR"] = previous
        self.budget.executor(int((time.monotonic() - started) * 1000))
        if result.status == "admit":
            self.manifest[component] = revision
        if not any(item.get("target") == component and item.get("status") == "proposal_ready"
                   for item in self.attempt_history):
            self._clear_admission_intent()
        return result.status, result.reason

    def _current_revision(self, component: str) -> str | None:
        binding = self._artifact_revision(component)
        return binding[1] if binding else None

    def _mark_evaluation(self, component: str, outcome: str, reason: str) -> None:
        for record in reversed(self.attempt_history):
            if (record.get("target") == component and
                    record.get("observed_outcome") == "proposed_pending_evaluation"):
                record["observed_outcome"] = outcome
                record["evaluation_reason"] = reason[:300]
                record["revision"] = self.manifest.get(component)
                record["status"] = "finished"
                self.attempts.write(record, expected_status="proposal_ready")
                self._clear_admission_intent()
                return

    def _end_to_end(self) -> tuple[str, str, str]:
        sources = {f"{component}.py": self.sources[component] for component in COMPONENTS}
        public = self._run_files({**sources, "test_public_end_to_end.py": PUBLIC_END_TO_END},
                                 public=True)
        if public.outcome is not RunOutcome.PASS:
            return public.outcome.value, _public_diagnostic(public), ""
        hidden = self._run_files({**sources, "test_end_to_end.py": self._frozen_text(HELD_E2E)},
                                 public=False)
        if hidden == "pass":
            hidden, _ = self._host_oracle()
        payload = {"manifest": dict(self.manifest),
                   "sources": {key: hashlib.sha256(value.encode()).hexdigest()
                               for key, value in sources.items()},
                   "component_contracts": {key: self.contracts[
                       CONTRACT_FILES[key].relative_to(CONTRACT_ROOT).as_posix()]
                       for key in COMPONENTS},
                   "end_to_end_suite": self.contracts[
                       HELD_E2E.relative_to(CONTRACT_ROOT).as_posix()],
                   "host_oracle": self.contracts[
                       HELD_CASES.relative_to(CONTRACT_ROOT).as_posix()],
                   "environment": self.budget.config["sandbox_image"]}
        self.evaluation_binding_inputs = payload
        binding = digest(payload)
        return hidden, "held_out_end_to_end_" + hidden, binding

    def _admission_intent_path(self) -> Path:
        return self.state_root / "admission_intent.json"

    def _read_admission_intent(self) -> dict | None:
        path = self._admission_intent_path()
        if not path.is_file():
            return None
        try:
            payload = _strict_json(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError, ValueError):
            return {"unreadable": True}
        return payload if isinstance(payload, dict) else {"unreadable": True}

    def _write_admission_intent(self, *, component: str, revision: str,
                                artifact_digest: str, contract_hash: str) -> None:
        path = self._admission_intent_path()
        if path.exists():
            raise RuntimeError("admission_intent_already_exists")
        temporary = path.with_suffix(".json.tmp")
        payload = {"component": component, "revision": revision,
                   "artifact_digest": artifact_digest, "contract_hash": contract_hash}
        with temporary.open("w", encoding="utf-8", newline="") as handle:
            json.dump(payload, handle, sort_keys=True, allow_nan=False)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        temporary.replace(path)

    def _clear_admission_intent(self) -> None:
        path = self._admission_intent_path()
        if path.is_file():
            path.unlink()

    def _exact_admitted(self, component: str, revision: str, artifact_digest: str,
                        contract_hash: str) -> bool:
        """True only for a license GrokCellSurface already admitted. Never writes one."""
        if component not in COMPONENTS or not revision or not artifact_digest:
            return False
        expected = self.contracts[
            CONTRACT_FILES[component].relative_to(CONTRACT_ROOT).as_posix()]
        if contract_hash != expected:
            return False
        try:
            if revision not in self.surface.components():
                return False
            stored = self.surface.artifacts.path_for(revision)
            if not stored.is_dir():
                return False
            license_record = self.surface.artifacts._read_license(stored)
            return (self.surface.artifacts._current_digest(stored) == artifact_digest
                    and license_record.get("name") == revision
                    and license_record.get("license") == "admitted"
                    and license_record.get("hash") == artifact_digest
                    and license_record.get("acceptance_suite_hash") == contract_hash)
        except (AttributeError, OSError, TypeError, ValueError):
            return False

    def _restore_worker_attempts(self) -> None:
        prior_ids = {item.get("id") for item in self.prior_records}
        self.worker_attempts = sum(
            1 for item in self.attempts.all()
            if item.get("id") not in prior_ids and item.get("action") in {
                "REPAIR_COMPONENT", "REIMPLEMENT_COMPONENT"})

    def _proposal_files(self, record: dict) -> dict[str, str]:
        relative = record.get("proposal_dir")
        if not isinstance(relative, str) or not relative:
            raise RuntimeError("interrupted_proposal_missing")
        folder = (self.state_root / relative).resolve()
        if not folder.is_relative_to(self.state_root.resolve()):
            raise RuntimeError("interrupted_proposal_escaped_state")
        proposal = {"module": read_text_exact(folder / "service.py"),
                    "tests": read_text_exact(folder / "test_service.py")}
        if digest(proposal) != record.get("candidate_hash"):
            raise RuntimeError("interrupted_proposal_changed")
        validate_module(proposal["module"])
        return proposal

    def _restore_pending_proposal(self, record: dict) -> None:
        proposal = self._proposal_files(record)
        target = record.get("target")
        if target not in COMPONENTS:
            raise RuntimeError("interrupted_proposal_target_invalid")
        self.sources[target] = proposal["module"]
        self.candidate_tests[target] = proposal["tests"]
        manifest = dict(record.get("dependency_manifest") or {})
        manifest.pop(target, None)
        for downstream in COMPONENTS:
            if target in DEPENDENCIES[downstream] or any(
                    dep not in manifest for dep in DEPENDENCIES[downstream]):
                manifest.pop(downstream, None)
        self.manifest = manifest
        self.attempt_history.append(dict(record))

    def _close_pending(self, record: dict, outcome: str, revision: str) -> None:
        updated = dict(record)
        updated["status"] = "finished"
        updated["observed_outcome"] = outcome
        updated["revision"] = revision
        self.attempts.write(updated, expected_status="proposal_ready")
        for index, item in enumerate(self.attempt_history):
            if item.get("id") == record.get("id"):
                self.attempt_history[index] = updated
                return
        self.attempt_history.append(updated)

    def _blocked_episode(self, reason: str, attempts: list[dict] | None = None) -> dict:
        return {"variant": self.variant, "arm": self.arm, "status": "blocked",
                "reason": reason, "manifest": dict(self.manifest),
                "evaluation_binding": "", "worker_attempts": self.worker_attempts,
                "retrieval_rounds": self.retrievals, "observations": [],
                "decisions": [], "attempts": list(attempts or []),
                "budget": self.budget.summary()}

    def _restart_disposition(self) -> dict | None:
        """Continue a proposal already on disk, or block an unresolved admission."""
        unfinished = self.attempts.unfinished()
        if any(item.get("status") == "started" for item in unfinished):
            raise RuntimeError("interrupted_attempt_requires_operator_review")
        pending = [item for item in unfinished if item.get("status") == "proposal_ready"]
        if len(pending) > 1:
            raise RuntimeError("interrupted_attempt_requires_operator_review")
        intent = self._read_admission_intent()
        if intent is None:
            if pending:
                self._restore_pending_proposal(pending[0])
            return None
        if not self._intent_matches_license(intent):
            return self._blocked_episode("admission_outcome_unknown", pending)
        component = intent.get("component")
        revision = intent.get("revision")
        if not isinstance(component, str) or not isinstance(revision, str):
            return self._blocked_episode("admission_outcome_unknown", pending)
        if pending and pending[0].get("target") != component:
            return self._blocked_episode("admission_outcome_unknown", pending)
        try:
            stored = self.surface.artifacts.path_for(revision)
            module = read_text_exact(stored / "service.py")
            tests = read_text_exact(stored / "test_service.py")
            validate_module(module)
        except (AttributeError, OSError, UnicodeError, ValueError, RuntimeError):
            return self._blocked_episode("admission_outcome_unknown", pending)
        if pending:
            manifest = dict(pending[0].get("dependency_manifest") or {})
            manifest.pop(component, None)
            for downstream in COMPONENTS:
                if component in DEPENDENCIES[downstream] or any(
                        dep not in manifest for dep in DEPENDENCIES[downstream]):
                    manifest.pop(downstream, None)
            self.manifest = manifest
            self.attempt_history.append(dict(pending[0]))
            self._close_pending(pending[0], "admit", revision)
        self.sources[component] = module
        self.candidate_tests[component] = tests
        self.manifest[component] = revision
        self._clear_admission_intent()
        return None

    def _intent_matches_license(self, intent: dict) -> bool:
        component = intent.get("component")
        revision = intent.get("revision")
        artifact_digest = intent.get("artifact_digest")
        contract_hash = intent.get("contract_hash")
        if (not isinstance(component, str) or not isinstance(revision, str)
                or not isinstance(artifact_digest, str) or not isinstance(contract_hash, str)):
            return False
        return self._exact_admitted(component, revision, artifact_digest, contract_hash)

    def run(self) -> dict:
        previous = os.environ.get(DEADLINE_ENV)
        try:
            result = self._run()
            write_terminal(self.root, result)
            return result
        finally:
            if previous is None:
                os.environ.pop(DEADLINE_ENV, None)
            else:
                os.environ[DEADLINE_ENV] = previous

    def _run(self) -> dict:
        policy, retrieval = ARMS[self.arm]
        self.budget.start_task()
        self._restore_worker_attempts()
        os.environ[DEADLINE_ENV] = str(time.monotonic() + self.budget.remaining_seconds())
        decisions: list[dict] = []
        if retrieval == "jev_mem":
            return {"variant": self.variant, "arm": self.arm, "status": "blocked",
                    "reason": "jev_mem_nested_usage_unmetered", "manifest": {},
                    "evaluation_binding": "", "worker_attempts": self.worker_attempts,
                    "retrieval_rounds": 0, "observations": [], "decisions": [],
                    "budget": self.budget.summary()}
        restarted = self._restart_disposition()
        if restarted is not None:
            return restarted
        status, reason, binding = "incomplete", "", ""
        limit = (int(self.budget.config["max_worker_attempts"]) +
                 int(self.budget.config["max_retrieval_rounds"]) + 3)
        for step in range(limit):
            self.observations.clear()
            for component in COMPONENTS:
                if any(dep not in self.manifest for dep in DEPENDENCIES[component]):
                    continue
                if self.manifest.get(component) == self._current_revision(component):
                    continue
                public = self._run_files({"service.py": self.sources[component],
                                          "test_public.py": self._frozen_text(PUBLIC_FILES[component])},
                                         public=True)
                if public.outcome is not RunOutcome.PASS:
                    if public.outcome is not RunOutcome.TESTS_FAILED:
                        status, reason = "blocked", public.outcome.value
                        break
                    detail = _public_diagnostic(public)
                    self.observations.append({"component": component, "status": "tests_failed",
                                              "diagnostic": detail})
                    self._mark_evaluation(component, "public_failed", detail)
                    continue
                oracle_outcome, oracle_reason = self._host_oracle(component)
                if oracle_outcome != "pass":
                    if oracle_outcome == "infra_error":
                        status, reason = "blocked", oracle_reason
                        break
                    self.observations.append({"component": component, "status": "tests_failed",
                                              "diagnostic": "independent_contract_failed"})
                    self._mark_evaluation(component, oracle_outcome, oracle_reason)
                    continue
                outcome, detail = self._admit(component)
                self._mark_evaluation(component, outcome, detail)
                if outcome != "admit":
                    if (outcome in {"outcome_unknown", "hold_unresolved"}
                            or any(word in detail for word in (
                                "infrastructure", "timeout", "sandbox", "output_limit",
                                "cleanup_failed"))):
                        status, reason = "blocked", detail
                        break
                    self.observations.append({"component": component, "status": "tests_failed",
                                              "diagnostic": detail})
            if status == "blocked":
                break
            if len(self.manifest) == len(COMPONENTS):
                status, reason, binding = self._end_to_end()
                if status == "pass":
                    status, reason = "accepted", "component_and_end_to_end_gates_passed"
                    break
                if status in {"infra_error", "timeout", "sandbox_required",
                              "output_limit", "cleanup_failed"}:
                    status, reason = "blocked", status
                    break
                status, reason = "unsupported", "end_to_end_only_failure_requires_public_target_diagnostic"
                break
            route_tokens = 128 if policy == "qwen" else 512
            route_policy = ("deterministic" if policy == "deterministic" or
                            not self.budget.can_bundle(((policy, route_tokens), ("qwen", 2048)))
                            else policy)
            state = DecisionState(
                manifest=dict(self.manifest), observations=tuple(self.observations),
                attempts=tuple(self.attempt_history),
                evidence_ids=tuple(item["id"] for item in self.prior_records[:5]),
                remaining_calls=self.budget.remaining_calls(),
                remaining_output_tokens=self.budget.remaining_output_tokens(),
                remaining_attempts=int(self.budget.config["max_worker_attempts"]) - self.worker_attempts,
                remaining_retrievals=int(self.budget.config["max_retrieval_rounds"]) - self.retrievals,
                infrastructure_ready=self.budget.can_call("qwen", 2048),
                routing_calls=0 if route_policy == "deterministic" else 1,
                routing_tokens=0 if route_policy == "deterministic" else route_tokens,
                retrieval_enabled=retrieval != "none")
            chooser = None if route_policy == "deterministic" else _BudgetedChoice(
                self.qwen if policy == "qwen" else self.jev, self.budget, policy)
            choice, route = select_action(state, route_policy, chooser)
            if route_policy != policy:
                route = {**route, "fallback": True,
                         "reason": "routing_and_worker_reservation_unaffordable"}
            decisions.append({"step": step, "action": choice.action,
                              "target": choice.target, "route": route})
            if self.budget.unknown_cost or self.budget.limit_breached:
                status, reason = "blocked", "routing_cost_or_limit_uncertain"
                break
            if not validate_choice(state, choice):
                status, reason = "blocked", "stale_route"
                break
            if choice.action == "ESCALATE":
                status, reason = "escalated", "policy_escalated"
                break
            if choice.action == "INVESTIGATE":
                # A second identical observation is a stopping condition.
                if self.attempt_history and self.attempt_history[-1].get("action") == "INVESTIGATE":
                    status, reason = "escalated", "unchanged_public_state"
                    break
                self.attempt_history.append({"action": "INVESTIGATE", "route": route})
                continue
            if choice.action == "RETRIEVE_EVIDENCE":
                self.retrievals += 1
                signature = str(self.observations[-1].get("diagnostic", "")) if self.observations else ""
                target = str(self.observations[-1].get("component", "")) if self.observations else ""
                if retrieval == "simple":
                    retrieval_started = time.monotonic()
                    recalled = simple_retrieve(self.attempts, component=target, signature=signature,
                                               contract_hash=digest(self.contracts),
                                               base_hash=hashlib.sha256(
                                                   self.sources[target].encode()).hexdigest(),
                                               dependency_manifest=dict(self.manifest),
                                               environment_hash=hashlib.sha256(
                                                   self.budget.config["sandbox_image"].encode()).hexdigest())
                    self.budget.executor(int((time.monotonic() - retrieval_started) * 1000))
                elif retrieval == "jev_mem":
                    status, reason = "blocked", "jev_mem_nested_usage_unmetered"
                    break
                else:
                    raise RuntimeError("retrieval_not_configured")
                self.recalled = recalled
                self.attempt_history.append({"action": "RETRIEVE_EVIDENCE", "route": route,
                                             "evidence_ids": [item["id"] for item in recalled]})
                continue
            target = choice.target
            if not self.budget.can_call("qwen", 2048):
                status, reason = "blocked", "worker_budget_unavailable_after_route"
                break
            self.worker_attempts += 1
            record_id = f"{digest(str(self.root))[:12]}.{self.variant}.{self.arm.lower()}.a{step:03d}"
            target_diagnostic = next((str(item.get("diagnostic", "")) for item in self.observations
                                      if item.get("component") == target), "")
            started_record = {"id": record_id, "status": "started", "target": target,
                              "action": choice.action, "base_hash": hashlib.sha256(
                                  self.sources[target].encode()).hexdigest(),
                              "dependency_manifest": dict(self.manifest),
                              "contract_hash": digest(self.contracts),
                              "environment_hash": hashlib.sha256(
                                  self.budget.config["sandbox_image"].encode()).hexdigest(),
                              "failure_signature": _failure_signature(target_diagnostic),
                              "route": route}
            self.attempts.write(started_record)
            diagnostic = target_diagnostic
            try:
                self.qwen.timeout = min(self.qwen.timeout, self.budget.remaining_seconds())
                reply = self.budget.call("qwen", 2048, lambda: self.qwen.propose(
                    component=target, source=self.sources[target],
                    contract=self._frozen_text(CONTRACT_ROOT / "PUBLIC_CONTRACT.md"),
                    diagnostic=diagnostic,
                    prior_attempts=[{"id": item["id"], "observed_outcome": item.get("observed_outcome"),
                                     "failure_signature": item.get("failure_signature"),
                                     "applicability": item.get("applicability"),
                                     "patch_source": item.get("patch_source")}
                                    for item in self.recalled[:3]], max_tokens=2048))
                proposal = reply.value
                proposal = {key: value.replace("\r\n", "\n").replace("\r", "\n")
                            for key, value in proposal.items()}
                validate_module(proposal["module"])
                compile(proposal["module"], "service.py", "exec")
                compile(proposal["tests"], "test_service.py", "exec")
                candidate_hash = digest(proposal)
                if any(item.get("candidate_hash") == candidate_hash for item in self.attempt_history):
                    raise ValueError("duplicate_failed_patch")
                self.sources[target] = proposal["module"]
                self.candidate_tests[target] = proposal["tests"]
                self.recalled = []
                predecessor = self.manifest.pop(target, None)
                for downstream in COMPONENTS:
                    if target in DEPENDENCIES[downstream] or any(
                            dep not in self.manifest for dep in DEPENDENCIES[downstream]):
                        self.manifest.pop(downstream, None)
                proposal_dir = self.state_root / "repair_attempts" / record_id
                proposal_dir.mkdir()
                (proposal_dir / "service.py").write_text(
                    proposal["module"], encoding="utf-8", newline="")
                (proposal_dir / "test_service.py").write_text(
                    proposal["tests"], encoding="utf-8", newline="")
                started_record.update({"status": "proposal_ready", "candidate_hash": candidate_hash,
                                       "observed_outcome": "proposed_pending_evaluation",
                                       "predecessor_revision": predecessor,
                                       "proposal_dir": str(proposal_dir.relative_to(self.state_root)),
                                        "qwen": {"model": reply.model, "usage": reply.usage,
                                                 "revision": reply.revision,
                                                 "elapsed_ms": reply.elapsed_ms,
                                                "request_id": reply.request_id}})
            except (RuntimeError, ValueError, SyntaxError) as exc:
                started_record.update({"status": "finished", "observed_outcome": "proposal_failed",
                                       "error": str(exc)[:120]})
            self.attempts.write(started_record, expected_status="started")
            self.attempt_history.append(started_record)
            if self.budget.unknown_cost or self.budget.limit_breached:
                status, reason = "blocked", "worker_cost_or_limit_uncertain"
                break
        else:
            status, reason = "escalated", "iteration_limit"
        return {"variant": self.variant, "arm": self.arm, "status": status,
                "reason": reason, "manifest": self.manifest, "evaluation_binding": binding,
                "evaluation_binding_inputs": self.evaluation_binding_inputs,
                "worker_attempts": self.worker_attempts, "retrieval_rounds": self.retrievals,
                "observations": self.observations, "decisions": decisions,
                "attempts": self.attempt_history,
                "budget": self.budget.summary()}


def _read_prior(path: Path | None, contracts: dict[str, str]) -> tuple[list[dict], float]:
    if path is None:
        return [], 0.0
    state_root = path.resolve()
    if not state_root.is_dir() or not (state_root / "repair_attempts").is_dir():
        raise ValueError("prior state must be a separate GrokCell state directory")
    episode_root = state_root.parent
    run_root = episode_root.parent.parent
    configuration = _strict_json((run_root / "run_config.json").read_text(encoding="utf-8"))
    if configuration.get("contract_hashes") != contracts:
        raise ValueError("prior_run_contracts_changed")
    if (configuration.get("seed_prior") is not True or
            episode_root.parent.name != SEED_VARIANT or episode_root.name != "B"):
        raise ValueError("prior_must_be_separate_unscored_seed")
    completed_rows = [_strict_json(line) for line in
                      (run_root / "results.jsonl").read_text(encoding="utf-8").splitlines()]
    matched = [row for row in completed_rows if row.get("variant") == episode_root.parent.name
               and row.get("arm") == episode_root.name]
    if len(matched) != 1 or matched[0].get("budget", {}).get("estimated_total_usd") is None:
        raise ValueError("prior_episode_not_recorded")
    verify_terminal(episode_root, matched[0], contracts,
                    configuration["budget"]["sandbox_image"])
    recorded = {item.get("id"): item for item in matched[0].get("attempts", [])}
    records = AttemptStore(state_root).all()
    usable = []
    for item in records:
        if (item.get("status") != "finished" or item.get("target") not in COMPONENTS
                or item.get("observed_outcome") in {None, "proposed_pending_evaluation",
                                                      "proposal_failed"}):
            continue
        if item.get("contract_hash") != digest(contracts):
            raise ValueError("prior_contract_mismatch")
        recorded_item = recorded.get(item.get("id"))
        if recorded_item != item:
            raise ValueError("prior_attempt_not_in_completed_evidence")
        try:
            signature = json.loads(item["failure_signature"])
        except (KeyError, TypeError, json.JSONDecodeError):
            raise ValueError("prior_public_diagnostic_invalid") from None
        if (not isinstance(signature, dict) or set(signature) != {
                "outcome", "exit_code", "diagnostic", "stdout_truncated", "stderr_truncated"}
                or signature["outcome"] != "tests_failed"
                or not isinstance(signature["diagnostic"], str)
                or len(signature["diagnostic"]) > 6000):
            raise ValueError("prior_public_diagnostic_invalid")
        proposal_dir = item.get("proposal_dir")
        if not proposal_dir:
            raise ValueError("prior_proposal_missing")
        folder = (state_root / proposal_dir).resolve()
        if not folder.is_relative_to(state_root):
            raise ValueError("prior_proposal_escaped_state")
        proposal = {"module": read_text_exact(folder / "service.py"),
                    "tests": read_text_exact(folder / "test_service.py")}
        if digest(proposal) != item.get("candidate_hash"):
            raise ValueError("prior_candidate_changed")
        validate_module(proposal["module"])
        # Only fields generated by this harness may reach retrieval and prompts.
        safe = {key: item.get(key) for key in (
            "id", "status", "target", "action", "base_hash", "dependency_manifest",
            "contract_hash", "environment_hash", "failure_signature",
            "observed_outcome", "candidate_hash", "revision")}
        safe["patch_source"] = proposal["module"][:4000]
        usable.append(safe)
    return usable, float(matched[0]["budget"]["estimated_total_usd"])


def write_terminal(root: Path, result: dict) -> None:
    """A completed episode gets one durable result before the run-level row."""
    target = root / "state" / "repair_terminal.json"
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists():
        raise RuntimeError("terminal_result_already_exists")
    temporary = target.with_suffix(".tmp")
    with temporary.open("w", encoding="utf-8", newline="") as handle:
        json.dump(result, handle, sort_keys=True, allow_nan=False)
        handle.write("\n")
        handle.flush()
        os.fsync(handle.fileno())
    temporary.replace(target)


def verify_terminal(root: Path, row: dict, contracts: dict[str, str],
                    image: str, *, allow_unknown: bool = False) -> None:
    target = root / "state" / "repair_terminal.json"
    stored = _strict_json(target.read_text(encoding="utf-8"))
    if stored != row:
        raise ValueError("run_row_differs_from_terminal_state")
    budget = row.get("budget", {})
    if budget.get("cost_unknown") and not allow_unknown:
        raise ValueError("unknown_terminal_cost")
    for key in ("calls", "output_tokens"):
        value = budget.get(key)
        if type(value) is not int or value < 0:
            raise ValueError("invalid_terminal_usage")
    if budget.get("cost_basis") != "configured_token_tariffs_plus_executor_time_estimate":
        raise ValueError("terminal_cost_basis_changed")
    for key in ("estimated_total_usd", "executor_seconds", "wall_seconds"):
        value = budget.get(key)
        if value is None and key == "estimated_total_usd" and allow_unknown:
            continue
        if (isinstance(value, bool) or not isinstance(value, (int, float))
                or not math.isfinite(value) or value < 0):
            raise ValueError("invalid_terminal_cost")
    if row.get("status") != "accepted":
        return
    if budget.get("cost_unknown") or budget.get("limit_breached"):
        raise ValueError("accepted_under_uncertain_budget")
    manifest = row.get("manifest", {})
    if set(manifest) != set(COMPONENTS):
        raise ValueError("accepted_manifest_incomplete")
    from .artifact import ArtifactStore
    artifacts = ArtifactStore(root / "state" / "artifacts")
    sources = {}
    for component in COMPONENTS:
        revision = manifest[component]
        path = artifacts.path_for(revision)
        license_record = artifacts._read_license(path)
        suite_hash = contracts[CONTRACT_FILES[component].relative_to(CONTRACT_ROOT).as_posix()]
        artifact_hash = artifacts._current_digest(path)
        if (license_record.get("name") != revision
                or license_record.get("license") != "admitted"
                or license_record.get("hash") != artifact_hash
                or license_record.get("acceptance_suite_hash") != suite_hash
                or revision != revision_name(component, artifact_hash,
                                             [manifest[dep] for dep in DEPENDENCIES[component]],
                                             suite_hash, image)):
            raise ValueError("accepted_artifact_binding_changed")
        sources[f"{component}.py"] = read_text_exact(path / "service.py")
    binding = digest({"manifest": manifest,
                      "sources": {key: hashlib.sha256(value.encode()).hexdigest()
                                  for key, value in sources.items()},
                      "component_contracts": {key: contracts[
                          CONTRACT_FILES[key].relative_to(CONTRACT_ROOT).as_posix()]
                          for key in COMPONENTS},
                      "end_to_end_suite": contracts[
                          HELD_E2E.relative_to(CONTRACT_ROOT).as_posix()],
                      "host_oracle": contracts[
                          HELD_CASES.relative_to(CONTRACT_ROOT).as_posix()],
                      "environment": image})
    if row.get("evaluation_binding") != binding:
        raise ValueError("accepted_evaluation_binding_changed")


def _binding_verified(item: dict) -> bool:
    """An acceptance counts only when its binding recomputes from frozen contracts."""
    payload = item.get("evaluation_binding_inputs")
    claimed = item.get("evaluation_binding")
    manifest = item.get("manifest")
    if (not isinstance(payload, dict) or not isinstance(claimed, str) or not claimed
            or not isinstance(manifest, dict) or set(manifest) != set(COMPONENTS)
            or payload.get("manifest") != manifest):
        return False
    sources = payload.get("sources")
    if (not isinstance(sources, dict)
            or set(sources) != {f"{name}.py" for name in COMPONENTS}
            or any(not isinstance(value, str) or len(value) != 64 for value in sources.values())):
        return False
    try:
        frozen = verify_contracts()
        expected = {name: frozen[CONTRACT_FILES[name].relative_to(CONTRACT_ROOT).as_posix()]
                    for name in COMPONENTS}
        if (payload.get("component_contracts") != expected
                or payload.get("end_to_end_suite") != frozen[
                    HELD_E2E.relative_to(CONTRACT_ROOT).as_posix()]
                or payload.get("host_oracle") != frozen[
                    HELD_CASES.relative_to(CONTRACT_ROOT).as_posix()]):
            return False
        return digest(payload) == claimed
    except (OSError, ValueError, TypeError):
        return False


def summarize(results: list[dict], *, prior_creation_estimated_usd: float = 0.0) -> dict:
    """Descriptive pilot score only; no small pilot licenses deployment."""
    by_arm = {}
    for arm in ARMS:
        rows = [item for item in results if item["arm"] == arm]
        known = all(item.get("budget", {}).get("estimated_total_usd") is not None for item in rows)
        cost = sum(item["budget"]["estimated_total_usd"] for item in rows) if known else None
        accepted = sum(item.get("status") == "accepted" for item in rows)
        construction = prior_creation_estimated_usd if arm in {"D", "E"} else 0.0
        fully_loaded = cost + construction if cost is not None else None
        qwen_calls = ([attempt["qwen"] for row in rows
                       for attempt in row.get("attempts", []) if attempt.get("qwen")] +
                      [decision["route"] for row in rows
                       for decision in row.get("decisions", [])
                       if decision.get("route", {}).get("source") == "qwen"
                       and decision["route"].get("model")
                       and not decision["route"].get("fallback")])
        revisions = sorted({item.get("revision") for item in qwen_calls
                            if isinstance(item.get("revision"), str) and item["revision"]})
        jev_routes = [decision["route"] for row in rows
                      for decision in row.get("decisions", [])
                      if decision.get("route", {}).get("source") == "jev"
                      and not decision["route"].get("fallback")]
        jev_models = sorted({route.get("model") for route in jev_routes
                             if isinstance(route.get("model"), str) and route["model"]})
        by_arm[arm] = {
            "episodes": len(rows), "accepted": accepted,
            "completion_rate": accepted / len(rows) if rows else None,
            "pilot_estimated_usd": cost, "prior_creation_estimated_usd": construction,
            "fully_loaded_estimated_usd": fully_loaded,
            "repairs_per_estimated_usd": accepted / fully_loaded if fully_loaded else None,
            "escalations": sum(item.get("status") == "escalated" for item in rows),
            "blocked": sum(item.get("status") == "blocked" for item in rows),
            "worker_attempts": sum(item.get("worker_attempts", 0) for item in rows),
            "wall_seconds": sum(item.get("budget", {}).get("wall_seconds", 0) for item in rows),
            "limit_breaches": sum(bool(item.get("budget", {}).get("limit_breached")) for item in rows),
            "qwen_revisions": revisions,
            "qwen_revision_known": bool(qwen_calls) and len(revisions) == 1 and all(
                item.get("revision") == revisions[0] for item in qwen_calls),
            "jev_models": jev_models,
            "jev_model_known": bool(jev_routes) and len(jev_models) == 1 and all(
                route.get("model") == jev_models[0] for route in jev_routes),
            "observed_false_acceptances": sum(
                item.get("status") == "accepted" and not _binding_verified(item)
                for item in rows),
        }
    comparisons = {}
    for label, baseline, challenger in (("C_vs_A", "A", "C"),
                                        ("C_vs_B", "B", "C"),
                                        ("D_vs_C", "C", "D"),
                                        ("E_vs_D", "D", "E")):
        left, right = by_arm[baseline], by_arm[challenger]
        left_rows = {item["variant"]: item for item in results if item["arm"] == baseline}
        right_rows = {item["variant"]: item for item in results if item["arm"] == challenger}
        paired = {"both": 0, "challenger_only": 0, "baseline_only": 0, "neither": 0}
        for variant in set(left_rows) & set(right_rows):
            left_ok = left_rows[variant].get("status") == "accepted"
            right_ok = right_rows[variant].get("status") == "accepted"
            bucket = ("both" if left_ok and right_ok else
                      "challenger_only" if right_ok else
                      "baseline_only" if left_ok else "neither")
            paired[bucket] += 1
        versions_match = (left["qwen_revision_known"] and right["qwen_revision_known"]
                          and left["qwen_revisions"] == right["qwen_revisions"]
                          and (baseline not in {"C", "D", "E"} or left["jev_model_known"])
                          and (challenger not in {"C", "D", "E"} or right["jev_model_known"])
                          and (label not in {"D_vs_C", "E_vs_D"} or
                               left["jev_models"] == right["jev_models"]))
        complete = (set(left_rows) == set(right_rows) == set(VARIANTS)
                    and left["episodes"] == right["episodes"] == len(VARIANTS)
                    and left["blocked"] == right["blocked"] == 0
                    and left["limit_breaches"] == right["limit_breaches"] == 0
                    and versions_match
                    and left["repairs_per_estimated_usd"] is not None
                    and right["repairs_per_estimated_usd"] is not None)
        gain = (right["repairs_per_estimated_usd"] / left["repairs_per_estimated_usd"] - 1
                if left["repairs_per_estimated_usd"] and right["repairs_per_estimated_usd"] is not None else None)
        comparisons[label] = {
            "comparable": complete, "observed_relative_gain": gain,
            "paired_outcomes": paired, "provider_versions_match": versions_match,
            "observed_effect_exceeds_threshold": bool(
                complete and gain is not None and gain >= MIN_WORTHWHILE_GAIN
                and right["accepted"] >= left["accepted"]
                and right["observed_false_acceptances"] == 0),
            "retention_supported": False,
            "retention_reason": "single_small_pilot_no_uncertainty_estimate",
        }
    return {"primary_metric": "accepted_complete_tasks_per_estimated_usd",
            "cost_basis": "configured_token_tariffs_plus_executor_time_estimate",
            "minimum_worthwhile_relative_gain": MIN_WORTHWHILE_GAIN,
            "prior_creation_estimated_usd": prior_creation_estimated_usd,
            "arms": by_arm, "comparisons": comparisons,
            "interpretation": "pilot_only_no_production_promotion"}


def _cost_unknown(result: dict) -> bool:
    budget = result.get("budget") or {}
    return bool(budget.get("cost_unknown")) or budget.get("estimated_total_usd") is None


def _load_recorded_results(path: Path) -> tuple[list[dict], bool]:
    """Return parsed rows and whether they should replace a torn or unterminated file.

    An incomplete trailing line is omitted only in memory. The caller rewrites the
    file after the kept rows match their terminals. A complete row is never dropped.
    """
    if not path.exists():
        return [], False
    raw = path.read_text(encoding="utf-8")
    if raw == "":
        return [], False
    rewrite = not raw.endswith("\n")
    lines = raw.splitlines()
    if rewrite and lines:
        try:
            parsed = _strict_json(lines[-1])
        except (json.JSONDecodeError, UnicodeError, ValueError):
            parsed = None
        if not isinstance(parsed, dict):
            lines = lines[:-1]
    rows = []
    for line in lines:
        if not line.strip():
            continue
        parsed = _strict_json(line)
        if not isinstance(parsed, dict):
            raise ValueError("invalid_result_row")
        rows.append(parsed)
    return rows, rewrite


def _write_recorded_results(path: Path, rows: list[dict]) -> None:
    payload = "".join(json.dumps(row, sort_keys=True, allow_nan=False) + "\n" for row in rows)
    temporary = path.with_name(path.name + ".tmp")
    with temporary.open("w", encoding="utf-8", newline="") as handle:
        handle.write(payload)
        handle.flush()
        os.fsync(handle.fileno())
    temporary.replace(path)


def _append_result(handle, result: dict) -> None:
    handle.write(json.dumps(result, sort_keys=True, allow_nan=False) + "\n")
    handle.flush()
    os.fsync(handle.fileno())


def _close_interrupted_provider(episode_root: Path, variant: str, arm: str,
                                budget_config: dict) -> dict | None:
    """A durable status=started attempt may have been billed. Do not send it again."""
    attempts_dir = episode_root / "state" / "repair_attempts"
    if not attempts_dir.is_dir():
        return None
    store = AttemptStore(episode_root / "state")
    records = store.all()
    started = [item for item in records if item.get("status") == "started"]
    already_closed = any(
        item.get("status") == "finished" and item.get("observed_outcome") == "proposal_failed"
        and item.get("error") == "interrupted_provider_call_not_replayed" for item in records)
    if not started and not already_closed:
        return None
    for record in started:
        updated = dict(record)
        updated["status"] = "finished"
        updated["observed_outcome"] = "proposal_failed"
        updated["error"] = "interrupted_provider_call_not_replayed"
        store.write(updated, expected_status="started")
    budget = Budget(budget_config)
    budget.unknown_cost = True
    return {"variant": variant, "arm": arm, "status": "blocked",
            "reason": "interrupted_provider_call_not_replayed",
            "manifest": {}, "evaluation_binding": "",
            "worker_attempts": 0, "retrieval_rounds": 0,
            "observations": [], "decisions": [],
            "attempts": store.all(), "budget": budget.summary()}


def _existing_episode(episode_root: Path, variant: str, arm: str,
                      budget_config: dict) -> dict | str | None:
    """Terminal row, 'run' to continue on disk, or None when the operator must stop."""
    terminal = episode_root / "state" / "repair_terminal.json"
    if terminal.is_file():
        row = _strict_json(terminal.read_text(encoding="utf-8"))
        if not isinstance(row, dict) or [row.get("variant"), row.get("arm")] != [variant, arm]:
            raise SystemExit("resume terminal identity changed")
        return row
    interrupted = _close_interrupted_provider(episode_root, variant, arm, budget_config)
    if interrupted is not None:
        write_terminal(episode_root, interrupted)
        return interrupted
    state = episode_root / "state"
    pending = []
    if (state / "repair_attempts").is_dir():
        pending = [item for item in AttemptStore(state).unfinished()
                   if item.get("status") == "proposal_ready"]
    if (state / "admission_intent.json").is_file() or pending:
        return "run"
    return None


def _write_summary(output: Path, results: list[dict], prior_creation_estimated_usd: float) -> None:
    (output / "summary.json").write_text(
        json.dumps(summarize(results, prior_creation_estimated_usd=prior_creation_estimated_usd),
                   indent=2, allow_nan=False) + "\n",
        encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="offline preflight; executes no candidate")
    parser.add_argument("--live", action="store_true", help="run paired pilot with authorized providers")
    parser.add_argument("--seed-prior", action="store_true",
                        help="run one separate deterministic seed episode")
    parser.add_argument("--resume", action="store_true",
                        help="continue only after fully recorded episode boundaries")
    parser.add_argument("--budget", type=Path)
    parser.add_argument("--prior-state", type=Path,
                        help="separate GrokCell state with canonical public attempt records")
    parser.add_argument("--output", type=Path)
    parser.add_argument("--seed", type=int, default=260925)
    args = parser.parse_args(argv)
    contracts = verify_contracts()
    if args.check and not args.live:
        print(json.dumps({"status": "offline_preflight_only", "contract_count": len(contracts),
                          "variants": list(VARIANTS), "arms": list(ARMS),
                          "sandbox_configured": bool(os.environ.get(SANDBOX_IMAGE_ENV)),
                          "docker_available": bool(shutil.which("docker")),
                          "qwen_credential": bool(os.environ.get("HF_TOKEN")),
                          "jev_credential": bool(os.environ.get("TYPESAFE_API_KEY"))}, indent=2))
        return 0
    if not args.live or not args.budget or not args.output:
        parser.error("live run requires --live --budget FILE --output DIR")
    budget_config = _strict_json(args.budget.read_text(encoding="utf-8"))
    Budget(budget_config)  # Validate schema before any side effect.
    if (not shutil.which("docker") or not os.environ.get("HF_TOKEN") or
            (not args.seed_prior and not os.environ.get("TYPESAFE_API_KEY"))):
        raise SystemExit("live prerequisites missing: Docker, HF_TOKEN, and TypeSafe key for paired pilot")
    if subprocess.run(["docker", "image", "inspect", budget_config["sandbox_image"]],
                      stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                      timeout=10, check=False).returncode != 0:
        raise SystemExit("pinned sandbox image is not present locally")
    prior, prior_creation_estimated_usd = _read_prior(args.prior_state, contracts)
    if not prior and not args.seed_prior:
        raise SystemExit("paired memory comparison requires --prior-state with public attempts")
    if args.output.exists() != args.resume:
        raise SystemExit("new runs need a new output directory; existing runs require --resume")
    if not args.resume:
        args.output.mkdir(parents=True)
    os.environ[SANDBOX_IMAGE_ENV] = budget_config["sandbox_image"]
    order = ([(SEED_VARIANT, 'B')] if args.seed_prior else
             [(variant, arm) for variant in VARIANTS for arm in ARMS])
    if budget_config["max_total_usd"] < len(order) * budget_config["max_task_usd"]:
        raise SystemExit("total dollar cap must fund every paired task at its equal task cap")
    if budget_config["max_elapsed_seconds"] < len(order) * budget_config["max_task_elapsed_seconds"]:
        raise SystemExit("total elapsed cap must fund every paired task at its equal task cap")
    for task_field, total_field in (("max_calls", "max_total_calls"),
                                    ("max_output_tokens", "max_total_output_tokens"),
                                    ("max_worker_attempts", "max_total_worker_attempts"),
                                    ("max_retrieval_rounds", "max_total_retrieval_rounds")):
        if budget_config[total_field] < len(order) * budget_config[task_field]:
            raise SystemExit(f"{total_field} must fund every paired task equally")
    random.Random(args.seed).shuffle(order)
    run_config = {
        "seed": args.seed, "seed_prior": args.seed_prior,
        "order": order, "contract_hashes": contracts,
        "budget": budget_config,
        "prior_state": str(args.prior_state.resolve()) if args.prior_state else None,
        "prior_records_hash": digest(prior),
        "prior_creation_estimated_usd": prior_creation_estimated_usd}
    config_path = args.output / "run_config.json"
    comparable_config = {**run_config, "order": [[variant, arm] for variant, arm in order]}
    if args.resume:
        if _strict_json(config_path.read_text(encoding="utf-8")) != comparable_config:
            raise SystemExit("resume configuration or prior evidence changed")
    else:
        config_path.write_text(json.dumps(comparable_config, indent=2) + "\n", encoding="utf-8")
    evidence = args.output / "results.jsonl"
    results, rewrite_results = (_load_recorded_results(evidence)
                                if args.resume and evidence.exists() else ([], False))
    for item in results:
        verify_terminal(args.output / item["variant"] / item["arm"], item,
                        contracts, budget_config["sandbox_image"], allow_unknown=True)
    if rewrite_results:
        _write_recorded_results(evidence, results)
    completed = [[item.get("variant"), item.get("arm")] for item in results]
    if completed != [[variant, arm] for variant, arm in order[:len(completed)]]:
        raise SystemExit("resume result order or identity changed")
    if any(_cost_unknown(item) for item in results):
        _write_summary(args.output, results, prior_creation_estimated_usd)
        raise SystemExit("resume blocked: completed episode has unknown external cost")
    total_spent = sum(item["budget"]["estimated_total_usd"] for item in results)
    totals = {"max_total_calls": sum(item["budget"]["calls"] for item in results),
              "max_total_output_tokens": sum(item["budget"]["output_tokens"] for item in results),
              "max_total_worker_attempts": sum(item.get("worker_attempts", 0) for item in results),
              "max_total_retrieval_rounds": sum(item.get("retrieval_rounds", 0) for item in results)}
    run_started = time.monotonic()

    def run_episode(episode_root: Path, variant: str, arm: str, *, resume_episode: bool) -> dict:
        budget = Budget(budget_config)
        episode = Episode(variant=variant, arm=arm, root=episode_root, budget=budget,
                          prior_records=list(prior), contracts=contracts, resume=resume_episode)
        try:
            return episode.run()
        except Exception as exc:
            result = {"variant": variant, "arm": arm, "status": "blocked",
                      "reason": type(exc).__name__ + ": " + str(exc)[:120],
                      "budget": budget.summary()}
            write_terminal(episode_root, result)
            return result

    with evidence.open("a" if args.resume and evidence.exists() else "w", encoding="utf-8") as handle:
        for variant, arm in order[len(results):]:
            episode_root = args.output / variant / arm
            if episode_root.exists():
                existing = _existing_episode(episode_root, variant, arm, budget_config)
                if existing is None:
                    unfinished = (AttemptStore(episode_root / "state").unfinished()
                                  if (episode_root / "state" / "repair_attempts").is_dir() else [])
                    detail = ("uncertain external attempt: " + ",".join(item["id"] for item in unfinished)
                              if unfinished else "admission or usage may have committed before result")
                    raise SystemExit("resume blocked at interrupted episode; " + detail)
                result = (run_episode(episode_root, variant, arm, resume_episode=True)
                          if existing == "run" else existing)
            else:
                result = run_episode(episode_root, variant, arm, resume_episode=False)
            limit_breached = bool(result.get("budget", {}).get("limit_breached"))
            verify_terminal(episode_root, result, contracts,
                            budget_config["sandbox_image"], allow_unknown=True)
            _append_result(handle, result)
            results.append(result)
            if _cost_unknown(result) or limit_breached:
                break
            total_spent += result["budget"]["estimated_total_usd"]
            if total_spent > budget_config["max_total_usd"]:
                raise RuntimeError("portfolio_dollar_limit_breached")
            for field, used in (("max_total_calls", result["budget"]["calls"]),
                                ("max_total_output_tokens", result["budget"]["output_tokens"]),
                                ("max_total_worker_attempts", result.get("worker_attempts", 0)),
                                ("max_total_retrieval_rounds", result.get("retrieval_rounds", 0))):
                totals[field] += used
                if totals[field] > budget_config[field]:
                    raise RuntimeError("portfolio_limit_breached:" + field)
            if time.monotonic() - run_started > budget_config["max_elapsed_seconds"]:
                break
    _write_summary(args.output, results, prior_creation_estimated_usd)
    print(str(evidence))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
