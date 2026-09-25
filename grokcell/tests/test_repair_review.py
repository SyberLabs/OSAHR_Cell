"""Offline counterexamples for the Qwen/Jev repair-arm review."""
from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from grokcell.repair_adapters import ProviderReply, QWEN_MODEL
from grokcell.repair_experiment import (Budget, Episode, _read_prior, summarize,
                                        verify_contracts)
from grokcell.repair_fixture import COMPONENTS, GOOD, SEED_VARIANT, VARIANTS
from grokcell.runner import RunOutcome


def _budget(image: str, **changes) -> Budget:
    values = {"sandbox_image": image, "max_total_usd": 25, "max_task_usd": 1,
              "max_calls": 8, "max_total_calls": 200,
              "max_output_tokens": 16384, "max_total_output_tokens": 409600,
              "max_worker_attempts": 1, "max_total_worker_attempts": 50,
              "max_retrieval_rounds": 1, "max_total_retrieval_rounds": 50,
              "max_elapsed_seconds": 7500, "max_task_elapsed_seconds": 300,
              "max_input_tokens_per_call": 50000,
              "qwen_input_usd_per_million": 1, "qwen_output_usd_per_million": 1,
              "jev_input_usd_per_million": 1, "jev_output_usd_per_million": 1,
              "executor_usd_per_second": 0.001}
    values.update(changes)
    return Budget(values)


def _row(variant: str, arm: str, route: dict, *, status: str, usd: float,
         binding: str = "", attempts: list | None = None,
         decisions: list | None = None) -> dict:
    return {"variant": variant, "arm": arm, "status": status,
            "manifest": dict.fromkeys(COMPONENTS, "revision"),
            "evaluation_binding": binding,
            "attempts": ([{"qwen": {"model": QWEN_MODEL, "revision": "rev-1"}}]
                         if attempts is None else attempts),
            "decisions": [{"route": route}] if decisions is None else decisions,
            "budget": {"estimated_total_usd": usd, "wall_seconds": 1.0,
                       "limit_breached": False, "cost_unknown": False}}


def test_blocked_arm_e_does_not_store_shared_priors(tmp_path, monkeypatch):
    # expects the correction: Jev-Mem must not copy priors into its store before the block
    image = "example/python-pytest@sha256:" + "a" * 64
    monkeypatch.setenv("GROKCELL_SANDBOX_IMAGE", image)
    monkeypatch.setattr("grokcell.repair_experiment.GrokCellSurface.open",
                        lambda **kwargs: object())
    prior = [{"id": "seed.a1", "status": "finished", "target": "inventory_reducer",
              "observed_outcome": "admit", "failure_signature": "public failure",
              "patch_source": "def apply_event(state, event):\n    return state\n"}]
    memory = Episode(variant="later_related", arm="D", root=tmp_path / "D",
                     budget=_budget(image), prior_records=prior,
                     contracts=verify_contracts())
    blocked = Episode(variant="later_related", arm="E", root=tmp_path / "E",
                      budget=_budget(image), prior_records=prior,
                      contracts=verify_contracts())
    result = blocked.run()
    assert result["status"] == "blocked"
    assert result["reason"] == "jev_mem_nested_usage_unmetered"
    assert memory.attempts.all() and memory.prior_records
    assert blocked.prior_records == []
    assert blocked.attempts.all() == []


def test_oracle_failure_signature_round_trips_through_prior_reader(tmp_path, monkeypatch):
    # expects the correction: failure_signature must be the JSON diagnostic _read_prior accepts
    image = "example/python-pytest@sha256:" + "b" * 64
    monkeypatch.setenv("GROKCELL_SANDBOX_IMAGE", image)
    monkeypatch.setattr("grokcell.repair_experiment.GrokCellSurface.open",
                        lambda **kwargs: object())
    monkeypatch.setattr("grokcell.repair_experiment.pytest_suite",
                        lambda *args, **kwargs: (_ for _ in ()).throw(
                            AssertionError("candidate execution is out of scope")))
    monkeypatch.setattr("grokcell.repair_experiment.isolated_call",
                        lambda *args, **kwargs: (_ for _ in ()).throw(
                            AssertionError("candidate execution is out of scope")))

    def propose(self, **kwargs):
        return ProviderReply(
            {"module": GOOD["event_decoder"], "tests": "def test_candidate():\n    assert True\n"},
            QWEN_MODEL, {"prompt_tokens": 3, "completion_tokens": 4}, 5, "req",
            revision="rev-test")

    monkeypatch.setattr("grokcell.repair_experiment.QwenBuilder.propose", propose)
    calls = {"n": 0}

    def run_files(files, *, public):
        calls["n"] += 1
        outcome = RunOutcome.PASS if calls["n"] == 1 else RunOutcome.TESTS_FAILED
        return SimpleNamespace(outcome=outcome, stdout="", stderr="", exit_code=1,
                               stdout_truncated=False, stderr_truncated=False, elapsed_ms=1)

    root = tmp_path / "run" / SEED_VARIANT / "B"
    episode = Episode(variant=SEED_VARIANT, arm="B", root=root, budget=_budget(image),
                      prior_records=[], contracts=verify_contracts())
    episode._run_files = run_files
    episode._host_oracle = lambda component=None: ("tests_failed", "operator_case_failed")
    result = episode.run()
    assert result["status"] == "escalated", result.get("reason")
    signature = result["attempts"][0]["failure_signature"]
    contracts = verify_contracts()
    run_root = root.parent.parent
    (run_root / "run_config.json").write_text(json.dumps({
        "contract_hashes": contracts, "seed_prior": True,
        "budget": {"sandbox_image": image}}), encoding="utf-8")
    (run_root / "results.jsonl").write_text(
        json.dumps(result, sort_keys=True, allow_nan=False) + "\n", encoding="utf-8")
    try:
        prior, _cost = _read_prior(root / "state", contracts)
    except ValueError as exc:
        raise AssertionError(f"{exc}; writer stored failure_signature={signature!r}") from exc
    assert json.loads(prior[0]["failure_signature"])["diagnostic"] == "independent_contract_failed"


def test_nonempty_binding_is_not_zero_false_acceptances():
    # expects the correction: summarize must recompute the evaluation binding
    rows = []
    for variant in VARIANTS:
        rows.append(_row(variant, "B", {"source": "deterministic", "fallback": False},
                         status="accepted", usd=2.0, binding="forged-binding"))
        rows.append(_row(variant, "C",
                         {"source": "jev", "fallback": False, "model": "jev-v1"},
                         status="accepted", usd=1.0, binding="forged-binding"))
    scored = summarize(rows)
    assert scored["arms"]["C"]["observed_false_acceptances"] == len(VARIANTS)
    assert scored["comparisons"]["C_vs_B"]["observed_effect_exceeds_threshold"] is False


def test_fallback_routes_do_not_establish_shared_model_identity():
    # expects the correction: fallback routes must not count as a known provider identity
    rows = []
    for variant in VARIANTS:
        for arm in ("C", "D"):
            rows.append(_row(
                variant, arm,
                {"source": "jev", "fallback": True, "model": "jev-v1",
                 "revision": "jev-rev", "reason": "jev_low_confidence"},
                status="escalated", usd=1.0))
    scored = summarize(rows)
    assert scored["comparisons"]["D_vs_C"]["provider_versions_match"] is False
    assert scored["comparisons"]["D_vs_C"]["comparable"] is False
    qwen_fallback = {"source": "qwen", "fallback": True, "model": QWEN_MODEL,
                     "revision": "rev-1", "reason": "qwen_invalid_choice"}
    routed = []
    for variant in VARIANTS:
        routed.append(_row(variant, "A", qwen_fallback, status="escalated", usd=1.0,
                           attempts=[], decisions=[{"route": qwen_fallback}]))
        routed.append(_row(
            variant, "C", qwen_fallback, status="escalated", usd=1.0, attempts=[],
            decisions=[{"route": qwen_fallback},
                       {"route": {"source": "jev", "fallback": False, "model": "jev-v1"}}]))
    scored = summarize(routed)
    assert scored["comparisons"]["C_vs_A"]["provider_versions_match"] is False
    assert scored["comparisons"]["C_vs_A"]["comparable"] is False
