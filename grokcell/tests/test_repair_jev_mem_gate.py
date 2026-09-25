"""Arm E stays blocked offline. This is not live Jev-Mem performance evidence."""
from __future__ import annotations

from grokcell.repair_experiment import Budget, Episode, verify_contracts


def test_arm_e_blocks_with_zero_provider_calls_when_chooser_and_retriever_injected(
        tmp_path, monkeypatch):
    image = "x@sha256:" + "a" * 64
    monkeypatch.setenv("GROKCELL_SANDBOX_IMAGE", image)
    monkeypatch.setattr("grokcell.repair_experiment.GrokCellSurface.open",
                        lambda **kwargs: object())
    calls = []

    def refuse(*args, **kwargs):
        calls.append("provider")
        raise AssertionError("provider_call")

    monkeypatch.setattr("grokcell.repair_experiment.simple_retrieve", refuse)
    monkeypatch.setattr("grokcell.repair_adapters._post_json", refuse)
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
    episode = Episode(variant="later_related", arm="E", root=tmp_path / "E",
                      budget=Budget(values), prior_records=[{
                          "id": "seed.a1", "status": "finished",
                          "target": "inventory_reducer", "observed_outcome": "admit",
                          "failure_signature": "public failure"}],
                      contracts=verify_contracts())
    episode.qwen.choose = refuse
    episode.qwen.propose = refuse
    episode.jev.choose = refuse
    result = episode.run()
    assert calls == []
    assert result["status"] == "blocked"
    assert result["reason"] == "jev_mem_nested_usage_unmetered"
    assert result["retrieval_rounds"] == 0
    assert result["worker_attempts"] == 0
    assert result["decisions"] == []
    assert result["budget"]["calls"] == 0
    assert result["budget"]["output_tokens"] == 0
    assert episode.budget.calls == 0
