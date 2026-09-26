from __future__ import annotations

import ast
import json
import math

import pytest

from grokcell.repair_adapters import QwenBuilder, QWEN_MODEL, _NoRedirect
from grokcell.repair_experiment import (Budget, Episode, main, revision_name,
                                        verify_contracts, verify_terminal,
                                        write_terminal)
from grokcell.repair_fixture import COMPONENTS, GOOD, SEED_SOURCES, SEED_VARIANT, VARIANTS
from grokcell.repair_guard import validate_module
from grokcell.repair_attempts import AttemptStore
from grokcell.mutant import mutate_source
from grokcell.repair_policy import (DecisionState, deterministic_choice,
                                    digest, legal_candidates,
                                    validate_choice)
from grokcell.runner import RunOutcome, RunResult, _sandbox_command, isolated_call


def _state(**changes):
    values = dict(manifest={"event_decoder": "e.r1"},
                  observations=({"component": "inventory_reducer", "status": "tests_failed",
                                 "diagnostic": "reserved count wrong"},), attempts=(),
                  remaining_calls=2, remaining_output_tokens=4096,
                  remaining_attempts=2, infrastructure_ready=True)
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


def test_passing_hidden_end_to_end_reaches_host_oracle(monkeypatch):
    episode = object.__new__(Episode)
    episode.sources = dict(GOOD)
    episode.manifest = dict.fromkeys(COMPONENTS, "revision")
    episode.contracts = verify_contracts()
    episode.budget = type("BudgetStub", (), {
        "config": {"sandbox_image": "pinned-image"},
        "reserve_executor": lambda self, seconds: None,
        "executor": lambda self, elapsed_ms: None,
    })()
    monkeypatch.setattr("grokcell.repair_experiment.pytest_suite",
                        lambda *args, **kwargs: RunResult(RunOutcome.PASS, 0))
    oracle_calls = []
    monkeypatch.setattr(episode, "_host_oracle",
                        lambda: (oracle_calls.append(True) or "pass", "operator_cases_passed"))

    status, reason, binding = episode._end_to_end()

    assert (status, reason) == ("pass", "held_out_end_to_end_pass")
    assert binding and oracle_calls == [True]


def test_preflight_is_offline_and_verifies_frozen_contracts(capsys):
    assert main(["--check"]) == 0
    result = json.loads(capsys.readouterr().out)
    assert result["status"] == "offline_preflight_only"
    assert result["contract_count"] == 9
    assert result["fixture"] == SEED_VARIANT


def test_choice_is_one_legal_action_target_pair_and_stale_decisions_fail():
    state = _state()
    choice = deterministic_choice(legal_candidates(state))
    assert (choice.action, choice.target) == ("REPAIR_COMPONENT", "inventory_reducer")
    assert validate_choice(state, choice)
    assert not validate_choice(_state(manifest={"event_decoder": "e.r2"}), choice)
    assert not validate_choice(_state(remaining_attempts=0), choice)


def test_action_selection_requires_worker_budget():
    state = _state(remaining_calls=0)
    assert [item.action for item in legal_candidates(state)] == ["ESCALATE"]


def test_contradiction_and_infrastructure_escalate():
    contradictory = _state(observations=({"status": "contradictory"},))
    assert [item.action for item in legal_candidates(contradictory)] == ["ESCALATE"]
    blocked = _state(infrastructure_ready=False)
    assert [item.action for item in legal_candidates(blocked)] == ["ESCALATE"]


def test_component_repair_remains_legal_after_one_prior_attempt():
    state = _state(attempts=({"target": "inventory_reducer",
                              "action": "REPAIR_COMPONENT"},))
    assert [item.action for item in legal_candidates(state)] == [
        "REPAIR_COMPONENT", "ESCALATE"]


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
                                 diagnostic="failed", max_tokens=128).value["module"]


def test_revision_binding_changes_with_dependency_contract_and_environment():
    base = revision_name("inventory_reducer", "a" * 64, ["decoder.r1"], "b" * 64, "image1")
    assert base != revision_name("inventory_reducer", "a" * 64, ["decoder.r2"], "b" * 64, "image1")
    assert base != revision_name("inventory_reducer", "a" * 64, ["decoder.r1"], "c" * 64, "image1")
    assert base != revision_name("inventory_reducer", "a" * 64, ["decoder.r1"], "b" * 64, "image2")


def test_attempt_store_preserves_transitions(tmp_path):
    store = AttemptStore(tmp_path)
    started = {"id": "task.a1", "status": "started", "target": "inventory_reducer"}
    store.write(started)
    assert store.unfinished() == [started]
    with pytest.raises(ValueError, match="already exists"):
        store.write(started)
    finished = dict(started, status="finished", observed_outcome="public_failed")
    store.write(finished, expected_status="started")
    assert store.unfinished() == []
    assert store.all() == [finished]


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
              "max_usd": 1, "max_calls": 2, "max_output_tokens": 4096,
              "max_worker_attempts": 2,
              "max_elapsed_seconds": 60,
              "max_input_tokens_per_call": 100,
              "qwen_input_usd_per_million": 1, "qwen_output_usd_per_million": 1,
              "executor_usd_per_second": 0.001}
    budget = Budget(values)
    with pytest.raises(RuntimeError):
        budget.call(100, lambda: (_ for _ in ()).throw(RuntimeError("outage")))
    assert budget.summary()["calls"] == 1
    assert budget.summary()["estimated_total_usd"] is None
    for key, value in (("max_usd", math.nan), ("max_elapsed_seconds", math.inf),
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


def test_terminal_result_cannot_be_altered(tmp_path):
    contracts = verify_contracts()
    state = tmp_path / "run" / "local_reserve" / "state"
    row = {"variant": "local_reserve", "status": "blocked",
           "budget": {"estimated_total_usd": 0.25, "calls": 1, "output_tokens": 10,
                      "executor_seconds": 1.0, "wall_seconds": 2.0,
                      "cost_basis": "configured_token_tariffs_plus_executor_time_estimate"}}
    write_terminal(state.parent, row)
    verify_terminal(state.parent, row, contracts, "image")
    with pytest.raises(ValueError, match="run_row_differs_from_terminal_state"):
        verify_terminal(state.parent, {**row, "status": "accepted"}, contracts, "image")
    with pytest.raises(ValueError, match="run_row_differs_from_terminal_state"):
        verify_terminal(state.parent, {**row, "budget": {**row["budget"],
                                                 "estimated_total_usd": math.nan}}, contracts, "image")


def test_redirect_handler_never_forwards_authorization():
    assert _NoRedirect().redirect_request(None, None, 302, "Moved", {},
                                          "https://other.example/path") is None
