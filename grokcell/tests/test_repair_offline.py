from __future__ import annotations

import ast
import json
import math

import pytest

from grokcell.repair_adapters import JevChoice, QwenBuilder, QWEN_MODEL, _NoRedirect
from grokcell.repair_experiment import (Budget, Episode, _read_prior, revision_name,
                                        summarize, verify_contracts, verify_terminal,
                                        write_terminal)
from grokcell.repair_fixture import COMPONENTS, SEED_SOURCES, SEED_VARIANT, VARIANTS
from grokcell.repair_guard import validate_module
from grokcell.repair_memory import AttemptStore, simple_retrieve
from grokcell.mutant import mutate_source
from grokcell.repair_policy import (DecisionState, deterministic_choice,
                                    digest, legal_candidates, select_action,
                                    validate_choice)
from grokcell.runner import RunOutcome, _sandbox_command, isolated_call


def _state(**changes):
    values = dict(manifest={"event_decoder": "e.r1"},
                  observations=({"component": "inventory_reducer", "status": "tests_failed",
                                 "diagnostic": "reserved count wrong"},), attempts=(),
                  evidence_ids=(), remaining_calls=2, remaining_output_tokens=4096,
                  remaining_attempts=2, remaining_retrievals=1,
                  infrastructure_ready=True)
    values.update(changes)
    return DecisionState(**values)


def test_frozen_contract_and_fixture_shapes_are_offline():
    assert len(verify_contracts()) == 9
    assert set(VARIANTS) == {"upstream_sku", "local_reserve", "plausible_bool",
                             "later_related", "release_decoy"}
    for sources in VARIANTS.values():
        assert set(sources) == set(COMPONENTS)
        for source in sources.values():
            ast.parse(source)  # Parse only; never execute candidate code on the host.
            validate_module(source)
    assert VARIANTS["local_reserve"]["inventory_reducer"] != VARIANTS["later_related"]["inventory_reducer"]
    assert SEED_VARIANT not in VARIANTS
    assert all(SEED_SOURCES["inventory_reducer"] != item["inventory_reducer"]
               for item in VARIANTS.values())
    assert mutate_source(VARIANTS["local_reserve"]["availability_api"]) is not None


def test_choice_is_one_legal_action_target_pair_and_stale_decisions_fail():
    state = _state()
    choice = deterministic_choice(legal_candidates(state))
    assert (choice.action, choice.target) == ("REPAIR_COMPONENT", "inventory_reducer")
    assert validate_choice(state, choice)
    assert not validate_choice(_state(manifest={"event_decoder": "e.r2"}), choice)
    assert not validate_choice(_state(remaining_attempts=0), choice)


def test_route_reserves_worker_call_and_disables_retrieval_without_backend():
    state = _state(remaining_calls=1, routing_calls=1,
                   evidence_ids=("prior.a1",), retrieval_enabled=False)
    assert "REPAIR_COMPONENT" not in {item.action for item in legal_candidates(state)}
    assert "RETRIEVE_EVIDENCE" not in {item.action for item in legal_candidates(state)}
    with_memory = _state(evidence_ids=("prior.a1",), retrieval_enabled=True)
    assert "RETRIEVE_EVIDENCE" in {item.action for item in legal_candidates(with_memory)}


def test_contradiction_forces_investigation_and_infrastructure_escalates():
    contradictory = _state(observations=({"status": "contradictory"},))
    assert {item.action for item in legal_candidates(contradictory)} == {
        "INVESTIGATE", "ESCALATE"}
    blocked = _state(infrastructure_ready=False)
    assert [item.action for item in legal_candidates(blocked)] == ["ESCALATE"]


def test_low_confidence_and_invalid_jev_choice_are_visible_fallbacks():
    class LowConfidence:
        min_confidence = 0.65

        def choose(self, **kwargs):
            return type("Reply", (), {"value": kwargs["candidates"][-1]["id"],
                                      "confidence": 0.2, "usage": {"input_tokens": 1,
                                                                     "output_tokens": 1},
                                      "model": "jev-1", "elapsed_ms": 1,
                                      "request_id": "r", "probabilities": {}})()

    choice, route = select_action(_state(), "jev", LowConfidence())
    assert choice.action == "REPAIR_COMPONENT"
    assert route["fallback"] and route["reason"] == "jev_low_confidence"
    assert route["model"] == "jev-1" and route["confidence"] == 0.2
    assert route["usage"] == {"input_tokens": 1, "output_tokens": 1}


def test_jev_adapter_uses_documented_choice_and_rejects_invalid_probability(monkeypatch):
    monkeypatch.setenv("TYPESAFE_API_KEY", "fake")
    captured = {}

    def response(url, payload, token, timeout, max_input_bytes):
        captured.update(payload)
        return ({"model": "jev-1.13.0", "answers": {"next_action": {
            "type": "choice", "choice": "a0", "confidence": 0.8,
            "probabilities": {"a0": 0.8, "a1": 0.2}}},
            "usage": {"input_tokens": 10, "output_tokens": 2}}, "req", 12)

    monkeypatch.setattr("grokcell.repair_adapters._post_json", response)
    reply = JevChoice().choose(state={"observation": "failed"}, candidates=[
        {"id": "a0", "description": "repair x"}, {"id": "a1", "description": "escalate"}])
    assert captured["questions"]["next_action"]["type"] == "choice"
    assert reply.value == "a0" and reply.probabilities == {"a0": 0.8, "a1": 0.2}

    def invalid(*args):
        raw, request_id, elapsed = response(*args)
        raw["answers"]["next_action"]["probabilities"] = {"a0": 1.0}
        return raw, request_id, elapsed

    monkeypatch.setattr("grokcell.repair_adapters._post_json", invalid)
    with pytest.raises(ValueError, match="jev_invalid_choice"):
        JevChoice().choose(state={}, candidates=[{"id": "a0", "description": "repair"},
                                                   {"id": "a1", "description": "stop"}])


def test_qwen_adapter_requires_requested_model_and_only_code_fields(monkeypatch):
    monkeypatch.setenv("HF_TOKEN", "fake")

    def response(url, payload, token, timeout, max_input_bytes):
        assert payload["model"] == QWEN_MODEL
        assert "held_out" not in json.dumps(payload)
        assert "import json" in payload["messages"][1]["content"]
        assert "No top-level effects" in payload["messages"][1]["content"]
        return ({"model": QWEN_MODEL, "choices": [{"message": {"content": json.dumps({
            "module": "def f(): return 1", "tests": "def test_f(): assert True"})}}],
            "usage": {"prompt_tokens": 10, "completion_tokens": 5}}, "req", 3)

    monkeypatch.setattr("grokcell.repair_adapters._post_json", response)
    assert QwenBuilder().propose(component="x", source="old", contract="public",
                                 diagnostic="failed", prior_attempts=[], max_tokens=128).value["module"]


def test_revision_binding_changes_with_dependency_contract_and_environment():
    base = revision_name("inventory_reducer", "a" * 64, ["decoder.r1"], "b" * 64, "image1")
    assert base != revision_name("inventory_reducer", "a" * 64, ["decoder.r2"], "b" * 64, "image1")
    assert base != revision_name("inventory_reducer", "a" * 64, ["decoder.r1"], "c" * 64, "image1")
    assert base != revision_name("inventory_reducer", "a" * 64, ["decoder.r1"], "b" * 64, "image2")


def test_attempt_restart_and_simple_retrieval_scope(tmp_path):
    store = AttemptStore(tmp_path)
    started = {"id": "task.a1", "status": "started", "target": "inventory_reducer"}
    store.write(started)
    assert store.unfinished() == [started]
    with pytest.raises(ValueError, match="already exists"):
        store.write(started)
    finished = dict(started, status="finished", observed_outcome="public_failed",
                    contract_hash="contract1", failure_signature="reserve wrong",
                    base_hash="base1", dependency_manifest={"event_decoder": "r1"},
                    environment_hash="env1")
    store.write(finished, expected_status="started")
    assert store.unfinished() == []
    found = simple_retrieve(store, component="inventory_reducer",
                            signature="reserve wrong", contract_hash="contract1",
                            base_hash="base1", dependency_manifest={"event_decoder": "r1"},
                            environment_hash="env1")
    assert found[0]["id"] == "task.a1"
    assert found[0]["applicability"] == "exact_context"
    assert simple_retrieve(store, component="other", signature="unrelated",
                           contract_hash="other", base_hash="base2",
                           dependency_manifest={}, environment_hash="env1") == []
    related = simple_retrieve(store, component="inventory_reducer",
                              signature="reserve wrong", contract_hash="contract1",
                              base_hash="base1", dependency_manifest={"event_decoder": "r2"},
                              environment_hash="env1")
    assert related[0]["applicability"] == "related_requires_retest"


def test_sandbox_command_has_hard_boundary_and_no_unsafe_fallback(tmp_path, monkeypatch):
    image = "example/python-pytest@sha256:" + "a" * 64
    command, _ = _sandbox_command(tmp_path, image)
    assert "--network=none" in command and "--read-only" in command
    assert "--cap-drop=ALL" in command and "--pull=never" in command
    assert "--log-driver=none" in command
    assert not any("docker.sock" in item or "Users/scarl" in item.replace("\\", "/")
                   for item in command if "target=/workspace" not in item)
    monkeypatch.delenv("GROKCELL_SANDBOX_IMAGE", raising=False)
    result, report = isolated_call(tmp_path, {"scope": "component"})
    assert result.outcome is RunOutcome.SANDBOX_REQUIRED and report is None


def test_budget_requires_explicit_prices_and_marks_failed_external_call_unknown():
    values = {"sandbox_image": "x@sha256:" + "a" * 64,
              "max_total_usd": 1, "max_task_usd": 1, "max_calls": 2,
              "max_total_calls": 50, "max_output_tokens": 4096,
              "max_total_output_tokens": 102400,
              "max_worker_attempts": 2, "max_total_worker_attempts": 50,
              "max_retrieval_rounds": 1, "max_total_retrieval_rounds": 25,
              "max_elapsed_seconds": 60,
              "max_task_elapsed_seconds": 30,
              "max_input_tokens_per_call": 100,
              "qwen_input_usd_per_million": 1, "qwen_output_usd_per_million": 1,
              "jev_input_usd_per_million": 1, "jev_output_usd_per_million": 1,
              "executor_usd_per_second": 0.001}
    budget = Budget(values)
    with pytest.raises(RuntimeError):
        budget.call("qwen", 100, lambda: (_ for _ in ()).throw(RuntimeError("outage")))
    assert budget.summary()["calls"] == 1
    assert budget.summary()["estimated_total_usd"] is None
    for key, value in (("max_task_usd", math.nan), ("max_elapsed_seconds", math.inf),
                       ("qwen_input_usd_per_million", math.inf), ("max_calls", 2.5)):
        with pytest.raises(ValueError):
            Budget({**values, key: value})


def test_generated_module_cannot_control_test_or_probe_process():
    validate_module(VARIANTS["upstream_sku"]["event_decoder"])
    for source in ("import pytest\ndef decode_event(raw): pytest.exit(returncode=0)",
                   "import os\ndef decode_event(raw): os._exit(0)",
                   "def decode_event(raw): print('forged completion')"):
        with pytest.raises(ValueError):
            validate_module(source)


def test_prior_only_enters_memory_arms_after_retrieval(tmp_path, monkeypatch):
    image = "x@sha256:" + "a" * 64
    monkeypatch.setenv("GROKCELL_SANDBOX_IMAGE", image)
    monkeypatch.setattr("grokcell.repair_experiment.GrokCellSurface.open",
                        lambda **kwargs: object())
    values = {"sandbox_image": image, "max_total_usd": 25, "max_task_usd": 1,
              "max_calls": 8, "max_total_calls": 200,
              "max_output_tokens": 16384, "max_total_output_tokens": 409600,
              "max_worker_attempts": 2, "max_total_worker_attempts": 50,
              "max_retrieval_rounds": 2, "max_total_retrieval_rounds": 50,
              "max_elapsed_seconds": 7500, "max_task_elapsed_seconds": 300,
              "max_input_tokens_per_call": 50000,
              "qwen_input_usd_per_million": 1, "qwen_output_usd_per_million": 1,
              "jev_input_usd_per_million": 1, "jev_output_usd_per_million": 1,
              "executor_usd_per_second": 0.001}
    prior = [{"id": "seed.a1", "status": "finished", "target": "inventory_reducer",
              "observed_outcome": "admit", "failure_signature": "public failure"}]
    for arm in "ABCDE":
        episode = Episode(variant="later_related", arm=arm, root=tmp_path / arm,
                          budget=Budget(values), prior_records=prior,
                          contracts=verify_contracts())
        assert episode.recalled == []
        assert bool(episode.prior_records) == (arm in "DE")
        assert bool(episode.attempts.all()) == (arm in "DE")
        if arm == "E":
            monkeypatch.setenv("GROKCELL_EXPERIMENT_DEADLINE", "prior-value")
            assert episode.run()["status"] == "blocked"
            assert __import__("os").environ["GROKCELL_EXPERIMENT_DEADLINE"] == "prior-value"


def test_self_hashed_prior_without_completed_episode_is_rejected(tmp_path):
    state = tmp_path / "run" / "local_reserve" / "B" / "state"
    store = AttemptStore(state)
    store.write({"id": "seed.a1", "status": "finished", "target": "inventory_reducer",
                 "contract_hash": "forged", "observed_outcome": "admit"})
    with pytest.raises((FileNotFoundError, ValueError)):
        _read_prior(state, verify_contracts())


def test_unmeasured_memory_arm_cannot_earn_retention():
    rows = [{"arm": "E", "variant": variant, "status": "blocked",
             "budget": {"estimated_total_usd": 0, "wall_seconds": 0}}
            for variant in VARIANTS]
    scored = summarize(rows)
    assert not scored["comparisons"]["E_vs_D"]["comparable"]
    assert not scored["comparisons"]["E_vs_D"]["retention_supported"]


def test_prior_record_is_bound_to_completed_episode_and_seed_cost(tmp_path):
    contracts = verify_contracts()
    state = tmp_path / "run" / SEED_VARIANT / "B" / "state"
    store = AttemptStore(state)
    folder = store.root / "seed.a1"
    folder.mkdir()
    proposal = {"module": "def apply_event(state, event):\n    return state\n",
                "tests": "def test_candidate():\n    assert True\n"}
    (folder / "service.py").write_text(proposal["module"], encoding="utf-8", newline="")
    (folder / "test_service.py").write_text(proposal["tests"], encoding="utf-8", newline="")
    signature = json.dumps({"outcome": "tests_failed", "exit_code": 1,
                            "diagnostic": "public failure", "stdout_truncated": False,
                            "stderr_truncated": False})
    record = {"id": "seed.a1", "status": "finished", "target": "inventory_reducer",
              "action": "REPAIR_COMPONENT", "base_hash": "old", "dependency_manifest": {},
              "environment_hash": "image", "contract_hash": digest(contracts),
              "failure_signature": signature, "observed_outcome": "admit",
              "candidate_hash": digest(proposal), "proposal_dir": "repair_attempts/seed.a1"}
    store.write(record)
    (state.parent.parent.parent / "run_config.json").write_text(
        json.dumps({"contract_hashes": contracts, "seed_prior": True,
                    "budget": {"sandbox_image": "image"}}), encoding="utf-8")
    row = {"variant": SEED_VARIANT, "arm": "B", "status": "escalated",
           "attempts": [record],
           "budget": {"estimated_total_usd": 0.25, "calls": 1, "output_tokens": 10,
                      "executor_seconds": 1.0, "wall_seconds": 2.0,
                      "cost_basis": "configured_token_tariffs_plus_executor_time_estimate"}}
    write_terminal(state.parent, row)
    (state.parent.parent.parent / "results.jsonl").write_text(
        json.dumps(row) + "\n", encoding="utf-8")
    prior, cost = _read_prior(state, contracts)
    assert cost == 0.25 and prior[0]["patch_source"] == proposal["module"]
    altered = dict(record, failure_signature=signature.replace("public failure", "secret hint"))
    store.write(altered, expected_status="finished")
    with pytest.raises(ValueError, match="prior_attempt_not_in_completed_evidence"):
        _read_prior(state, contracts)
    with pytest.raises(ValueError, match="run_row_differs_from_terminal_state"):
        verify_terminal(state.parent, {**row, "status": "accepted"}, contracts, "image")
    with pytest.raises(ValueError, match="run_row_differs_from_terminal_state"):
        verify_terminal(state.parent, {**row, "budget": {**row["budget"],
                                                 "estimated_total_usd": math.nan}}, contracts, "image")
    (state.parent.parent.parent / "run_config.json").write_text(
        json.dumps({"contract_hashes": contracts, "seed_prior": False,
                    "budget": {"sandbox_image": "image"}}), encoding="utf-8")
    with pytest.raises(ValueError, match="prior_must_be_separate_unscored_seed"):
        _read_prior(state, contracts)


def test_redirect_handler_never_forwards_authorization():
    assert _NoRedirect().redirect_request(None, None, 302, "Moved", {},
                                          "https://other.example/path") is None


def test_score_labels_estimated_cost_and_rejects_model_drift():
    rows = []
    for variant in VARIANTS:
        for arm in ("A", "B", "C"):
            route = ({"source": "qwen", "model": QWEN_MODEL,
                      "revision": "r1" if variant != "release_decoy" else "r2"}
                     if arm == "A" else
                     {"source": "jev", "model": "jev-v1" if variant != "release_decoy"
                      else "jev-v2", "revision": None} if arm == "C" else
                     {"source": "deterministic"})
            rows.append({"variant": variant, "arm": arm, "status": "accepted",
                         "manifest": dict.fromkeys(COMPONENTS, "revision"),
                         "evaluation_binding": "binding",
                         "attempts": [{"qwen": {"model": QWEN_MODEL, "revision": "r1"}}],
                         "decisions": [{"route": route}],
                         "budget": {"estimated_total_usd": 1.0, "wall_seconds": 1.0,
                                    "limit_breached": False}})
    scored = summarize(rows, prior_creation_estimated_usd=0.5)
    assert scored["primary_metric"].endswith("estimated_usd")
    assert scored["cost_basis"] == "configured_token_tariffs_plus_executor_time_estimate"
    assert scored["prior_creation_estimated_usd"] == 0.5
    assert not scored["comparisons"]["C_vs_A"]["comparable"]
    assert not scored["comparisons"]["C_vs_B"]["comparable"]
    assert not scored["comparisons"]["C_vs_B"]["retention_supported"]
