"""Offline safe-restart contracts for the repair experiment.

These tests use fakes and monkeypatches. They are not live provider performance.
"""
from __future__ import annotations

import json
import random
from pathlib import Path

import pytest

from grokcell.artifact import Artifact
from grokcell.messages import DrainItem, PostAck
from grokcell.repair_experiment import (ARMS, CONTRACT_FILES, CONTRACT_ROOT, Budget,
                                        Episode, main, revision_name, verify_contracts,
                                        write_terminal)
from grokcell.repair_fixture import VARIANTS
from grokcell.repair_memory import AttemptStore
from grokcell.repair_policy import digest
from grokcell.runner import SANDBOX_IMAGE_ENV, RunOutcome, RunResult

IMAGE = "x@sha256:" + "a" * 64
PRIOR = [{"id": "seed.a1", "status": "finished"}]
MODULE = "def decode_event(raw):\n    return {}\n"
TESTS = "def test_candidate():\n    assert True\n"


def _budget(**changes) -> dict:
    values = {"sandbox_image": IMAGE, "max_total_usd": 25, "max_task_usd": 1,
              "max_calls": 8, "max_total_calls": 200,
              "max_output_tokens": 16384, "max_total_output_tokens": 409600,
              "max_worker_attempts": 2, "max_total_worker_attempts": 50,
              "max_retrieval_rounds": 2, "max_total_retrieval_rounds": 50,
              "max_elapsed_seconds": 7500, "max_task_elapsed_seconds": 300,
              "max_input_tokens_per_call": 50000,
              "qwen_input_usd_per_million": 1, "qwen_output_usd_per_million": 1,
              "jev_input_usd_per_million": 1, "jev_output_usd_per_million": 1,
              "executor_usd_per_second": 0.001}
    values.update(changes)
    return values


def _recorded(variant: str, arm: str, *, reason: str = "policy_escalated",
              status: str = "escalated", unknown: bool = False) -> dict:
    return {"variant": variant, "arm": arm, "status": status, "reason": reason,
            "manifest": {}, "evaluation_binding": "", "worker_attempts": 0,
            "retrieval_rounds": 0, "observations": [], "decisions": [], "attempts": [],
            "budget": {"estimated_total_usd": None if unknown else 0.0,
                       "cost_basis": "configured_token_tariffs_plus_executor_time_estimate",
                       "calls": 0, "output_tokens": 0, "executor_seconds": 0.0,
                       "wall_seconds": 0.0, "cost_unknown": unknown, "limit_breached": False}}


def _order() -> list[list[str]]:
    order = [[variant, arm] for variant in VARIANTS for arm in ARMS]
    random.Random(260925).shuffle(order)
    return order


def _live_guards(monkeypatch) -> None:
    monkeypatch.setenv("HF_TOKEN", "fake")
    monkeypatch.setenv("TYPESAFE_API_KEY", "fake")
    monkeypatch.setattr("grokcell.repair_experiment.shutil.which",
                        lambda name: "/usr/bin/docker" if name == "docker" else None)

    class Completed:
        returncode = 0

    monkeypatch.setattr("grokcell.repair_experiment.subprocess.run",
                        lambda *args, **kwargs: Completed())
    monkeypatch.setattr("grokcell.repair_adapters._post_json",
                        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("live provider")))
    monkeypatch.setattr("grokcell.repair_experiment.pytest_suite",
                        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("docker")))
    monkeypatch.setattr("grokcell.repair_experiment.isolated_call",
                        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("docker")))


def _prepare(tmp_path: Path, monkeypatch, rows: list[dict], budget: dict | None = None):
    _live_guards(monkeypatch)
    budget = _budget() if budget is None else budget
    contracts = verify_contracts()
    output = tmp_path / "pilot"
    output.mkdir()
    order = _order()
    prior_path = tmp_path / "prior"
    config = {"seed": 260925, "seed_prior": False, "order": order,
              "contract_hashes": contracts, "budget": budget,
              "prior_state": str(prior_path.resolve()),
              "prior_records_hash": digest(PRIOR), "prior_creation_estimated_usd": 0.0}
    (output / "run_config.json").write_text(json.dumps(config, indent=2) + "\n", encoding="utf-8")
    (output / "budget.json").write_text(json.dumps(budget) + "\n", encoding="utf-8")
    if rows:
        (output / "results.jsonl").write_text(
            "".join(json.dumps(row, sort_keys=True) + "\n" for row in rows), encoding="utf-8")
        for row in rows:
            write_terminal(output / row["variant"] / row["arm"], row)
    monkeypatch.setattr("grokcell.repair_experiment._read_prior",
                        lambda path, loaded: (PRIOR, 0.0))
    return output, order, prior_path


def _resume(output: Path, prior_path: Path) -> int:
    return main(["--live", "--resume", "--budget", str(output / "budget.json"),
                 "--prior-state", str(prior_path), "--output", str(output), "--seed", "260925"])


def _stop_after(monkeypatch, allowed: list[str] | None = None) -> list[list[str]]:
    started: list[list[str]] = []
    real_run = Episode.run

    def wrapped(self):
        identity = [self.variant, self.arm]
        if allowed is not None and identity == allowed:
            return real_run(self)
        started.append(identity)
        result = _recorded(self.variant, self.arm, reason="later_episode_started", status="blocked")
        result["budget"]["limit_breached"] = True
        write_terminal(self.root, result)
        return result

    monkeypatch.setattr(Episode, "run", wrapped)
    return started


def _episode(tmp_path: Path, monkeypatch, surface, *, variant: str = "upstream_sku",
             arm: str = "B", resume: bool = False) -> Episode:
    monkeypatch.setenv(SANDBOX_IMAGE_ENV, IMAGE)
    monkeypatch.setattr("grokcell.repair_experiment.GrokCellSurface.open",
                        lambda **kwargs: surface)
    return Episode(variant=variant, arm=arm, root=tmp_path / arm, budget=Budget(_budget()),
                   prior_records=[], contracts=verify_contracts(), resume=resume)


class _Surface:
    def __init__(self) -> None:
        self.posts = []
        self.components_list: list[str] = []
        self.artifacts = None

    def components(self) -> list[str]:
        return list(self.components_list)

    def post(self, message):
        self.posts.append(message)
        return PostAck(queued=True, message_id="m-0001")

    def drain(self):
        return [DrainItem("m-0001", "forge.propose", "reject", "runner_failed", 1)]


def test_started_attempt_still_refuses_direct_construction(tmp_path, monkeypatch):
    monkeypatch.setenv(SANDBOX_IMAGE_ENV, IMAGE)
    root = tmp_path / "B"
    AttemptStore(root / "state").write(
        {"id": "task.a001", "status": "started", "target": "event_decoder"})
    with pytest.raises(RuntimeError, match="interrupted_attempt_requires_operator_review"):
        Episode(variant="upstream_sku", arm="B", root=root, budget=Budget(_budget()),
                prior_records=[], contracts=verify_contracts(), resume=True)


def test_admission_intent_is_durable_before_post(tmp_path, monkeypatch):
    surface = _Surface()
    episode = _episode(tmp_path, monkeypatch, surface)
    seen = {}

    def post(message):
        intent = json.loads((episode.state_root / "admission_intent.json").read_text())
        seen.update(intent)
        assert message.kind == "forge.propose"
        assert message.payload["name"] == intent["revision"]
        assert intent["component"] == "event_decoder"
        assert intent["artifact_digest"]
        assert intent["contract_hash"]
        return PostAck(queued=True, message_id="m-0001")

    surface.post = post
    status, reason = episode._admit("event_decoder")
    assert status == "reject" and reason == "runner_failed"
    assert seen["component"] == "event_decoder"
    artifacts = episode.state_root / "artifacts"
    assert not artifacts.exists() or not list(artifacts.rglob("license.json"))
    assert __import__("os").environ.get("GROKCELL_ALLOW_UNSANDBOXED_RUNNER") is None


def test_exact_admitted_revision_is_reused_without_posting(tmp_path, monkeypatch):
    surface = _Surface()
    episode = _episode(tmp_path, monkeypatch, surface)
    module = MODULE
    tests = TESTS
    artifact = Artifact(name="event_decoder", source="payload",
                        files={"service.py": module, "test_service.py": tests})
    contract_hash = episode.contracts[
        CONTRACT_FILES["event_decoder"].relative_to(CONTRACT_ROOT).as_posix()]
    revision = revision_name(
        "event_decoder", artifact.digest(), [], contract_hash, IMAGE)
    folder = tmp_path / "admitted" / revision
    folder.mkdir(parents=True)
    (folder / "service.py").write_text(module, encoding="utf-8", newline="")
    (folder / "test_service.py").write_text(tests, encoding="utf-8", newline="")
    # Fixture stands in for a license already written by GrokCellSurface.post/drain.
    (folder / "license.json").write_text(json.dumps({
        "name": revision, "license": "admitted", "hash": artifact.digest(),
        "acceptance_suite_hash": contract_hash}) + "\n", encoding="utf-8")

    class Artifacts:
        def path_for(self, name):
            return tmp_path / "admitted" / name

        def _read_license(self, stored):
            return json.loads((stored / "license.json").read_text(encoding="utf-8"))

        def _current_digest(self, stored):
            return artifact.digest()

        def _write_license(self, *args, **kwargs):
            raise AssertionError("resume must not write an admitted license")

    surface.artifacts = Artifacts()
    surface.components_list = [revision]
    episode._write_admission_intent(component="event_decoder", revision=revision,
                                    artifact_digest=artifact.digest(),
                                    contract_hash=contract_hash)
    AttemptStore(episode.state_root).write({
        "id": "task.a001", "status": "proposal_ready", "target": "event_decoder",
        "action": "REPAIR_COMPONENT", "observed_outcome": "proposed_pending_evaluation",
        "dependency_manifest": {}})
    seen = []

    def fake_run_files(self, files, *, public):
        seen.append(files["service.py"])
        return RunResult(RunOutcome.INFRA_ERROR, 1, stdout="", stderr="")

    monkeypatch.setattr(Episode, "_run_files", fake_run_files)
    monkeypatch.setattr(episode.qwen, "propose",
                        lambda **kwargs: (_ for _ in ()).throw(AssertionError("provider replay")))
    result = episode.run()
    assert surface.posts == []
    assert module not in seen
    assert episode.manifest["event_decoder"] == revision
    assert not episode._admission_intent_path().exists()
    stored = episode.attempts.read("task.a001")
    assert stored["status"] == "finished" and stored["observed_outcome"] == "admit"
    assert result["budget"]["cost_unknown"] is False
    assert result["budget"]["calls"] == 0


def test_admission_intent_without_exact_license_does_not_post(tmp_path, monkeypatch):
    surface = _Surface()
    episode = _episode(tmp_path, monkeypatch, surface, resume=True)
    binding = episode._artifact_revision("event_decoder")
    assert binding is not None
    artifact, revision, contract_hash = binding
    episode._write_admission_intent(component="event_decoder", revision=revision,
                                    artifact_digest=artifact.digest(),
                                    contract_hash=contract_hash)

    def forbid_post(message):
        raise AssertionError("replayed admission")

    surface.post = forbid_post
    status, reason = episode._admit("event_decoder")
    assert (status, reason) == ("outcome_unknown", "admission_outcome_unknown")
    monkeypatch.setattr(Episode, "_run_files",
                        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("evaluated")))
    result = episode.run()
    assert result["status"] == "blocked"
    assert result["reason"] == "admission_outcome_unknown"
    assert result["budget"]["cost_unknown"] is False
    assert result["budget"]["estimated_total_usd"] == 0


def test_proposal_ready_without_intent_uses_disk_and_skips_provider(tmp_path, monkeypatch):
    surface = _Surface()
    root = tmp_path / "B"
    proposal = {"module": MODULE, "tests": TESTS}
    store = AttemptStore(root / "state")
    folder = store.root / "task.a001"
    folder.mkdir()
    (folder / "service.py").write_text(MODULE, encoding="utf-8", newline="")
    (folder / "test_service.py").write_text(TESTS, encoding="utf-8", newline="")
    store.write({"id": "task.a001", "status": "proposal_ready", "target": "event_decoder",
                 "action": "REPAIR_COMPONENT",
                 "observed_outcome": "proposed_pending_evaluation",
                 "candidate_hash": digest(proposal),
                 "proposal_dir": "repair_attempts/task.a001", "dependency_manifest": {}})
    monkeypatch.setenv(SANDBOX_IMAGE_ENV, IMAGE)
    monkeypatch.setattr("grokcell.repair_experiment.GrokCellSurface.open",
                        lambda **kwargs: surface)
    seen = []

    def fake_run_files(self, files, *, public):
        seen.append(files["service.py"])
        return RunResult(RunOutcome.TESTS_FAILED, 1, stdout="public failure", stderr="")

    monkeypatch.setattr(Episode, "_run_files", fake_run_files)
    episode = Episode(variant="upstream_sku", arm="B", root=root,
                      budget=Budget(_budget(max_worker_attempts=1)),
                      prior_records=[], contracts=verify_contracts(), resume=True)
    monkeypatch.setattr(episode.qwen, "propose",
                        lambda **kwargs: (_ for _ in ()).throw(AssertionError("provider replay")))
    result = episode.run()
    assert seen == [MODULE]
    assert MODULE != VARIANTS["upstream_sku"]["event_decoder"]
    assert result["status"] == "escalated"
    stored = episode.attempts.read("task.a001")
    assert stored["status"] == "finished"
    assert stored["observed_outcome"] == "public_failed"
    assert result["budget"]["calls"] == 0
    assert surface.posts == []


def test_resume_skips_fully_recorded_episodes(tmp_path, monkeypatch):
    order = _order()
    output, order, prior_path = _prepare(tmp_path, monkeypatch, [_recorded(*order[0])])
    started = _stop_after(monkeypatch)
    assert _resume(output, prior_path) == 0
    assert started == [order[1]]


def test_resume_appends_missing_terminal_once(tmp_path, monkeypatch):
    order = _order()
    output, order, prior_path = _prepare(tmp_path, monkeypatch, [_recorded(*order[0])])
    missing = _recorded(*order[1], reason="held_for_append", status="blocked")
    write_terminal(output / order[1][0] / order[1][1], missing)
    started = _stop_after(monkeypatch)
    assert _resume(output, prior_path) == 0
    lines = (output / "results.jsonl").read_text(encoding="utf-8").splitlines()
    parsed = [json.loads(line) for line in lines]
    assert [item["reason"] for item in parsed].count("held_for_append") == 1
    assert started == [order[2]]
    assert _resume(output, prior_path) == 0
    again = [json.loads(line)["reason"] for line in
             (output / "results.jsonl").read_text(encoding="utf-8").splitlines()]
    assert again.count("held_for_append") == 1


def test_resume_drops_only_torn_trailing_line(tmp_path, monkeypatch):
    order = _order()
    output, order, prior_path = _prepare(tmp_path, monkeypatch, [_recorded(*order[0])])
    evidence = output / "results.jsonl"
    evidence.write_text(evidence.read_text(encoding="utf-8") + '{"variant": "torn"', encoding="utf-8")
    missing = _recorded(*order[1], reason="recovered_terminal", status="blocked")
    write_terminal(output / order[1][0] / order[1][1], missing)
    _stop_after(monkeypatch)
    assert _resume(output, prior_path) == 0
    text = evidence.read_text(encoding="utf-8")
    assert '{"variant": "torn"' not in text
    reasons = [json.loads(line)["reason"] for line in text.splitlines()]
    assert reasons[:2] == ["policy_escalated", "recovered_terminal"]
    summary = json.loads((output / "summary.json").read_text(encoding="utf-8"))
    assert sum(item["episodes"] for item in summary["arms"].values()) == len(text.splitlines())
    assert summary["interpretation"] == "pilot_only_no_production_promotion"


def test_complete_line_that_disagrees_with_terminal_fails_closed(tmp_path, monkeypatch):
    order = _order()
    output, order, prior_path = _prepare(tmp_path, monkeypatch, [_recorded(*order[0])])
    evidence = output / "results.jsonl"
    bad = _recorded(*order[0], reason="changed_after_terminal")
    evidence.write_text(json.dumps(bad, sort_keys=True) + '\n{"torn"', encoding="utf-8")
    before = evidence.read_bytes()
    sentinel = {"sentinel": True}
    (output / "summary.json").write_text(json.dumps(sentinel), encoding="utf-8")
    with pytest.raises(ValueError, match="run_row_differs_from_terminal_state"):
        _resume(output, prior_path)
    assert evidence.read_bytes() == before
    assert json.loads((output / "summary.json").read_text(encoding="utf-8")) == sentinel


def test_interrupted_provider_call_is_not_replayed(tmp_path, monkeypatch):
    output, order, prior_path = _prepare(tmp_path, monkeypatch, [])
    variant, arm = order[0]
    AttemptStore(output / variant / arm / "state").write(
        {"id": "task.a001", "status": "started", "target": "event_decoder",
         "action": "REPAIR_COMPONENT"})
    monkeypatch.setattr(Episode, "run",
                        lambda self: (_ for _ in ()).throw(AssertionError("replayed episode")))
    monkeypatch.setattr("grokcell.repair_experiment.GrokCellSurface.post",
                        lambda self, message: (_ for _ in ()).throw(AssertionError("replayed admission")))
    monkeypatch.setattr("grokcell.repair_experiment.QwenBuilder.propose",
                        lambda self, **kwargs: (_ for _ in ()).throw(AssertionError("replayed provider")))
    assert _resume(output, prior_path) == 0
    stored = AttemptStore(output / variant / arm / "state").read("task.a001")
    assert stored["status"] == "finished"
    assert stored["observed_outcome"] == "proposal_failed"
    assert stored["error"] == "interrupted_provider_call_not_replayed"
    terminal_path = output / variant / arm / "state" / "repair_terminal.json"
    terminal_bytes = terminal_path.read_bytes()
    terminal = json.loads(terminal_bytes)
    assert terminal["status"] == "blocked"
    assert terminal["reason"] == "interrupted_provider_call_not_replayed"
    assert terminal["budget"]["cost_unknown"] is True
    assert terminal["budget"]["estimated_total_usd"] is None
    lines = (output / "results.jsonl").read_text(encoding="utf-8").splitlines()
    assert len(lines) == 1
    assert json.loads(lines[0])["reason"] == "interrupted_provider_call_not_replayed"
    assert not (output / order[1][0] / order[1][1]).exists()
    with pytest.raises(SystemExit, match="unknown external cost"):
        _resume(output, prior_path)
    assert terminal_path.read_bytes() == terminal_bytes
    assert (output / "results.jsonl").read_text(encoding="utf-8").splitlines() == lines
    assert not (output / order[1][0] / order[1][1]).exists()


def test_resume_blocks_unknown_admission_without_post_and_keeps_known_cost(tmp_path, monkeypatch):
    order = _order()
    target = next(pair for pair in order if pair[1] != "E")
    prefix = order[:order.index(target)]
    output, order, prior_path = _prepare(
        tmp_path, monkeypatch, [_recorded(*pair) for pair in prefix])
    episode = output / target[0] / target[1]
    (episode / "state").mkdir(parents=True)
    (episode / "state" / "admission_intent.json").write_text(json.dumps({
        "component": "event_decoder", "revision": "event.decoder.missing",
        "artifact_digest": "f" * 64, "contract_hash": "e" * 64}) + "\n", encoding="utf-8")
    monkeypatch.setattr("grokcell.repair_experiment.GrokCellSurface.post",
                        lambda self, message: (_ for _ in ()).throw(AssertionError("replayed admission")))
    monkeypatch.setattr("grokcell.repair_experiment.QwenBuilder.propose",
                        lambda self, **kwargs: (_ for _ in ()).throw(AssertionError("replayed provider")))
    started = _stop_after(monkeypatch, allowed=list(target))
    assert _resume(output, prior_path) == 0
    rows = [json.loads(line) for line in (output / "results.jsonl").read_text().splitlines()]
    matched = [row for row in rows if [row["variant"], row["arm"]] == target]
    assert len(matched) == 1
    assert matched[0]["status"] == "blocked"
    assert matched[0]["reason"] == "admission_outcome_unknown"
    assert matched[0]["budget"]["cost_unknown"] is False
    assert matched[0]["budget"]["estimated_total_usd"] == 0
    assert matched[0]["budget"]["calls"] == 0
    assert started and started[0] != list(target)


def test_resume_of_proposal_ready_does_not_call_provider(tmp_path, monkeypatch):
    budget = _budget(max_worker_attempts=1, max_total_worker_attempts=25)
    order = _order()
    target = next(pair for pair in order if pair[1] != "E")
    prefix = order[:order.index(target)]
    output, order, prior_path = _prepare(
        tmp_path, monkeypatch, [_recorded(*pair) for pair in prefix], budget)
    root = output / target[0] / target[1]
    proposal = {"module": MODULE, "tests": TESTS}
    store = AttemptStore(root / "state")
    folder = store.root / "task.a001"
    folder.mkdir()
    (folder / "service.py").write_text(MODULE, encoding="utf-8", newline="")
    (folder / "test_service.py").write_text(TESTS, encoding="utf-8", newline="")
    store.write({"id": "task.a001", "status": "proposal_ready", "target": "event_decoder",
                 "action": "REPAIR_COMPONENT",
                 "observed_outcome": "proposed_pending_evaluation",
                 "candidate_hash": digest(proposal),
                 "proposal_dir": "repair_attempts/task.a001", "dependency_manifest": {}})
    seen = []

    def fake_run_files(self, files, *, public):
        seen.append(files.get("service.py"))
        return RunResult(RunOutcome.TESTS_FAILED, 1, stdout="public failure", stderr="")

    monkeypatch.setattr(Episode, "_run_files", fake_run_files)
    monkeypatch.setattr("grokcell.repair_experiment.QwenBuilder.propose",
                        lambda self, **kwargs: (_ for _ in ()).throw(AssertionError("replayed provider")))
    _stop_after(monkeypatch, allowed=list(target))
    assert _resume(output, prior_path) == 0
    assert MODULE in seen
    stored = AttemptStore(root / "state").read("task.a001")
    assert stored["observed_outcome"] == "public_failed"
    rows = [json.loads(line) for line in (output / "results.jsonl").read_text().splitlines()]
    matched = [row for row in rows if [row["variant"], row["arm"]] == target]
    assert len(matched) == 1
    assert matched[0]["budget"]["calls"] == 0


def test_empty_episode_directory_still_stops_for_reconciliation(tmp_path, monkeypatch):
    output, order, prior_path = _prepare(tmp_path, monkeypatch, [])
    (output / order[0][0] / order[0][1]).mkdir(parents=True)
    with pytest.raises(SystemExit, match="admission or usage may have committed"):
        _resume(output, prior_path)
    assert not (output / order[1][0] / order[1][1]).exists()
