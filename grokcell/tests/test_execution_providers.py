"""Provider conformance uses injected transports; no live calls or credentials."""
from dataclasses import replace
import json
import os

import pytest

from grokcell.execution.providers import (HuggingFaceWorker, JevAdapter, ProviderConfig,
                                         _NoRedirect, _strict_json, post, preflight)
from grokcell.execution.ports import ObservedReplyError
from grokcell.execution.records import ActionOffer, JsonSnapshot, Observation


def config(provider="jev"):
    return ProviderConfig(provider, "jev-1.13.0" if provider == "jev" else "openai/gpt-oss-20b:ovhcloud",
                          ("jev-1.13.0",) if provider == "jev" else ("openai/gpt-oss-20b",),
                          42_000 if provider == "jev" else 50_000,
                          0 if provider == "jev" else 180_000,
                          1000, 1000, 1000)


def response():
    return {"model": "jev-1.13.0", "answers": {"next_action": {
        "type": "choice", "choice": "repair", "confidence": 0.8,
        "probabilities": {"repair": 0.8, "stop": 0.2}}}, "usage": {"input_tokens": 100}}


OBSERVATION = Observation(JsonSnapshot.capture({"failure": "wrong sum"}), "deps", 0)
OFFERS = (ActionOffer("repair", "generate", "add"), ActionOffer("stop", "yield", "review"))


def test_jev_documented_shape_and_free_output_missing_usage():
    calls = []
    def transport(c, payload):
        calls.append(payload)
        return response(), "typesafe-request", 5
    reply = JevAdapter(config(), transport=transport).choose(OBSERVATION, OFFERS)
    assert len(calls) == 1
    assert calls[0]["questions"]["next_action"]["type"] == "choice"
    assert reply.value == "repair" and reply.actual_microusd == 5
    assert reply.metadata.value()["request_id"] == "typesafe-request"
    assert reply.metadata.value()["output_tokens"] is None
    assert reply.metadata.value()["input_microusd_per_million"] == 42_000
    assert reply.metadata.value()["billing_scope"] == "credential_owner"


def test_missing_billable_usage_is_unknown_not_zero():
    body = response()
    body["usage"] = {}
    reply = JevAdapter(config(), transport=lambda *args: (body, None, 0)).choose(OBSERVATION, OFFERS)
    assert reply.actual_microusd is None


@pytest.mark.parametrize("raw", [b'{"model":"one","model":"two"}',
                                 b'{"usage":{"input_tokens":1,"input_tokens":2}}',
                                 b'{"confidence":NaN}', b'{"confidence":Infinity}'])
def test_duplicate_and_nonfinite_json_fields_are_refused(raw):
    with pytest.raises(ValueError):
        _strict_json(raw)


@pytest.mark.parametrize("field,value", [("choice", "deploy"), ("confidence", True),
                                        ("confidence", float("nan")),
                                        ("probabilities", {"repair": 1.0})])
def test_jev_malformed_choice_refused(field, value):
    body = response()
    body["answers"]["next_action"][field] = value
    with pytest.raises(ObservedReplyError) as error:
        JevAdapter(config(), transport=lambda *args: (body, None, 0)).choose(OBSERVATION, OFFERS)
    assert error.value.actual_microusd == 5
    metadata = error.value.metadata.value()
    assert metadata["estimated_microusd"] == 5
    assert "answers" not in metadata and "probabilities" not in metadata


def test_changed_model_refused():
    body = response()
    body["model"] = "unexpected-model"
    with pytest.raises(ValueError, match="model identity"):
        JevAdapter(config(), transport=lambda *args: (body, None, 0)).choose(OBSERVATION, OFFERS)


@pytest.mark.parametrize("model", ["jev-latest", "jev-preview", "jev-1.bad", "jev-1.13.0-extra"])
def test_jev_requires_an_exact_versioned_model(model):
    with pytest.raises(ValueError, match="versioned"):
        replace(config(), model=model)


def test_transport_exception_not_retried():
    calls = []
    def transport(*args):
        calls.append(1)
        raise TimeoutError("sent but lost")
    with pytest.raises(TimeoutError):
        JevAdapter(config(), transport=transport).choose(OBSERVATION, OFFERS)
    assert len(calls) == 1


def test_hf_model_route_and_module_only():
    calls = []
    def transport(c, payload):
        calls.append(payload)
        return {"model": "openai/gpt-oss-20b", "id": "hf-request", "usage": {
            "prompt_tokens": 100, "completion_tokens": 50}, "choices": [{"message": {
                "content": json.dumps({"module": "def add(a,b): return a+b"})}}]}, None, 8
    worker = HuggingFaceWorker(config("hf"), output_key="module", transport=transport)
    reply = worker.propose(JsonSnapshot.capture({"public_contract": "add"}))
    assert calls[0]["model"] == "openai/gpt-oss-20b:ovhcloud"
    assert calls[0]["stream"] is False and calls[0]["max_tokens"] == 1000
    assert reply.value.startswith(b"def add") and reply.actual_microusd == 14
    assert reply.metadata.value()["returned_model"] == "openai/gpt-oss-20b"
    assert reply.metadata.value()["request_id"] == "hf-request"
    assert reply.metadata.value()["input_microusd_per_million"] == 50_000
    assert reply.metadata.value()["output_microusd_per_million"] == 180_000


@pytest.mark.parametrize("content", ['{"module":"ok","permission":"deploy"}',
                                    '{"module":"ok","module":"other"}',
                                    '{"module":false}', 'not json'])
def test_hf_invalid_module_payload_refused(content):
    def transport(*args):
        return {"model": "openai/gpt-oss-20b", "id": "hf-observed", "usage": {
            "prompt_tokens": 100, "completion_tokens": 50},
            "choices": [{"message": {"content": content}}]}, None, 0
    with pytest.raises(ObservedReplyError) as error:
        HuggingFaceWorker(config("hf"), output_key="module", transport=transport).propose(JsonSnapshot.capture({}))
    assert error.value.actual_microusd == 14
    metadata = error.value.metadata.value()
    assert metadata["request_id"] == "hf-observed"
    assert metadata["estimated_microusd"] == 14
    assert not {"choices", "content", "module", "HF_TOKEN"}.intersection(metadata)


@pytest.mark.parametrize("result", [
    {"model": "openai/gpt-oss-20b"},
    {"model": "openai/gpt-oss-20b", "choices": []},
    {"model": "openai/gpt-oss-20b", "choices": [{"message": {}}]},
    {"model": "openai/gpt-oss-20b", "choices": [{"message": {"content": 7}}]},
])
def test_hf_missing_or_malformed_content_preserves_valid_usage(result):
    body = {**result, "usage": {"prompt_tokens": 100, "completion_tokens": 50}}
    with pytest.raises(ObservedReplyError) as error:
        HuggingFaceWorker(config("hf"), transport=lambda *a: (body, "hf-usage-known", 3)).propose(
            JsonSnapshot.capture({}))
    assert error.value.actual_microusd == 14
    assert error.value.metadata.value()["request_id"] == "hf-usage-known"
    assert error.value.metadata.value()["output_tokens"] == 50


@pytest.mark.parametrize("details,validation_error", [
    ("malformed optional detail", "invalid prompt token details"),
    ({"cached_tokens": 101}, "provider token detail exceeds total usage"),
])
def test_hf_invalid_optional_usage_details_preserve_total_cost(details, validation_error):
    config_with_small_ceiling = ProviderConfig(
        "hf", "openai/gpt-oss-20b:ovhcloud", ("openai/gpt-oss-20b",),
        1_000_000, 1_000_000, 20, 10, 10)
    body = {"model": "openai/gpt-oss-20b", "id": "known-billing-id",
            "usage": {"prompt_tokens": 100, "completion_tokens": 100,
                      "prompt_tokens_details": details},
            "choices": [{"message": {"content": '{"module":"private candidate text"}'}}]}
    with pytest.raises(ObservedReplyError, match="usage details") as error:
        HuggingFaceWorker(config_with_small_ceiling, output_key="module",
                          transport=lambda *a: (body, None, 1)).propose(JsonSnapshot.capture({}))
    assert error.value.actual_microusd == 200
    metadata = error.value.metadata.value()
    assert metadata["estimated_microusd"] == 200
    assert metadata["input_tokens"] == 100 and metadata["output_tokens"] == 100
    assert metadata["request_id"] == "known-billing-id"
    assert metadata["limits_breached"] is True
    assert metadata["validation_error"] == validation_error
    assert "private candidate text" not in json.dumps(metadata)
    assert "cached_tokens" not in json.dumps(metadata)


@pytest.mark.parametrize("field,value", [("input_microusd_per_million", -1),
                                         ("max_charge_microusd", 1), ("max_input_tokens", 0),
                                         ("timeout_seconds", 61), ("max_output_tokens", True)])
def test_invalid_rate_and_budget_fields_refused(field, value):
    with pytest.raises(ValueError):
        replace(config(), **{field: value})


def test_zero_tariffs_are_accepted():
    zero = replace(config(), input_microusd_per_million=0, output_microusd_per_million=0,
                   max_charge_microusd=0)
    assert zero.estimate(None, None) == 0


@pytest.mark.parametrize("model", ["openai/gpt-oss-20b", "openai/gpt-oss-20b:fastest",
                                    "openai/gpt-oss-20b:cheapest", "openai/gpt-oss-20b:unknown",
                                    ":ovhcloud"])
def test_hf_route_requires_documented_explicit_chat_provider(model):
    with pytest.raises(ValueError, match="documented"):
        replace(config("hf"), model=model)


def test_hf_unexpected_returned_model_is_refused():
    body = {"model": "openai/gpt-oss-20b:other", "choices": [{"message": {"content": "{}"}}]}
    with pytest.raises(ValueError, match="model identity"):
        HuggingFaceWorker(config("hf"), transport=lambda *a: (body, None, 0)).propose(
            JsonSnapshot.capture({}))


def test_hf_reasoning_and_cache_detail_counts_are_recorded_without_double_counting():
    body = {"model": "openai/gpt-oss-20b", "choices": [{"message": {"content": "{}"}}],
            "usage": {"prompt_tokens": 100, "completion_tokens": 50,
                      "prompt_tokens_details": {"cached_tokens": 20},
                      "completion_tokens_details": {"reasoning_tokens": 30}}}
    reply = HuggingFaceWorker(config("hf"), transport=lambda *a: (body, "hf-123", 2)).propose(
        JsonSnapshot.capture({}))
    metadata = reply.metadata.value()
    assert reply.actual_microusd == 14
    assert metadata["cached_input_tokens"] == 20
    assert metadata["reasoning_output_tokens"] == 30
    assert metadata["request_id"] == "hf-123"
    assert metadata["retry_policy"] == "none"
    assert metadata["max_input_bytes"] == 24_000 and metadata["max_response_bytes"] == 1_048_576


@pytest.mark.parametrize("usage", [None, {}, {"prompt_tokens": 100},
                                   {"prompt_tokens": True, "completion_tokens": 1},
                                   {"prompt_tokens": -1, "completion_tokens": 1},
                                   {"prompt_tokens": 100, "completion_tokens": 10,
                                    "prompt_tokens_details": {"cached_tokens": 101}},
                                   {"prompt_tokens": 100, "completion_tokens": 10,
                                    "completion_tokens_details": {"reasoning_tokens": 11}}])
def test_hf_missing_or_invalid_billable_usage_is_unknown_or_rejected(usage):
    body = {"model": "openai/gpt-oss-20b", "choices": [{"message": {"content": "{}"}}],
            "usage": usage}
    if usage in (None, {}, {"prompt_tokens": 100}):
        reply = HuggingFaceWorker(config("hf"), transport=lambda *a: (body, None, 0)).propose(
            JsonSnapshot.capture({}))
        assert reply.actual_microusd is None
    else:
        with pytest.raises(ValueError):
            HuggingFaceWorker(config("hf"), transport=lambda *a: (body, None, 0)).propose(
                JsonSnapshot.capture({}))


def test_input_limit_applies_even_to_injected_transport():
    with pytest.raises(ValueError, match="byte ceiling"):
        JevAdapter(replace(config(), max_input_bytes=10), transport=lambda *a: pytest.fail("sent")).choose(OBSERVATION, OFFERS)


def test_no_redirect_and_no_credentials_no_send(monkeypatch):
    assert _NoRedirect().redirect_request(None, None, 302, "moved", {}, "https://evil.invalid") is None
    monkeypatch.delenv("TYPESAFE_API_KEY", raising=False)
    with pytest.raises(RuntimeError, match="credential"):
        post(config(), {"state": "test"})
    monkeypatch.setenv("HF_TOKEN", "DO_NOT_EXPOSE_THIS_VALUE")
    assert "DO_NOT_EXPOSE_THIS_VALUE" not in json.dumps(preflight())


def test_http_redirect_and_transport_failure_are_single_attempt(monkeypatch):
    from urllib.error import HTTPError, URLError
    from grokcell.execution import providers

    monkeypatch.setenv("TYPESAFE_API_KEY", "synthetic-test-token")
    class Opener:
        def __init__(self, exc):
            self.exc, self.calls = exc, 0
        def open(self, *args, **kwargs):
            self.calls += 1
            raise self.exc

    failures = ((HTTPError(providers.ENDPOINTS["jev"], 302, "redirect", {}, None), "provider_http_302"),
                (URLError("interrupted"), "outcome_unknown"))
    for failure, expected in failures:
        opener = Opener(failure)
        monkeypatch.setattr(providers.request, "build_opener", lambda *handlers, _opener=opener: _opener)
        with pytest.raises(RuntimeError, match=expected):
            providers._post_http(config(), {"state": "offline"})
        assert opener.calls == 1


def test_usage_bound_violation_is_visible():
    body = response()
    body["usage"]["input_tokens"] = 1001
    reply = JevAdapter(config(), transport=lambda *a: (body, None, 1)).choose(OBSERVATION, OFFERS)
    assert reply.metadata.value()["limits_breached"] is True


def test_provider_response_exceeding_reserved_charge_is_not_clamped():
    body = response()
    body["usage"] = {"input_tokens": 10_000, "output_tokens": 0}
    reply = JevAdapter(replace(config(), max_charge_microusd=42),
                       transport=lambda *a: (body, "over-reserved", 1)).choose(OBSERVATION, OFFERS)
    assert reply.actual_microusd == 420
    assert reply.actual_microusd > 42
    assert reply.metadata.value()["limits_breached"] is True


@pytest.mark.skipif(os.name != "posix", reason="durable execution requires POSIX local storage")
def test_provider_adapters_compose_with_durable_data_checks_without_network(tmp_path):
    """Adapter conformance integration, not a live provider result."""
    from grokcell.execution.checking import DependencyVerifier
    from grokcell.execution.durable import DurableRuntime
    from grokcell.execution.records import Limits, Permission
    from grokcell.execution.workflows import (DEPENDENCY_OBSERVATION, assessment_bytes,
                                             dependency, workflow_identity)

    sends = []
    def jev_transport(configuration, payload):
        sends.append("jev")
        body = response()
        body["answers"]["next_action"].update(
            choice="assess", probabilities={"assess": 0.8, "review": 0.2})
        return body, "injected-jev-id", 1

    def hf_transport(configuration, payload):
        sends.append("hf")
        return {"model": "openai/gpt-oss-20b", "choices": [{"message": {
            "content": assessment_bytes().decode()}}],
            "usage": {"prompt_tokens": 100, "completion_tokens": 50}}, "injected-hf-id", 1

    options = dict(state_dir=tmp_path, run_id="adapter-integration",
                   workflow_id=workflow_identity("dependency"),
                   permission=Permission("test", "operator", ("read", "decide", "generate", "check", "admit", "yield"), 2_000_000_000),
                   dependencies=DEPENDENCY_OBSERVATION, limits=Limits(max_seconds=60),
                   chooser=JevAdapter(config(), transport=jev_transport),
                   workers={"generate": HuggingFaceWorker(config("hf"), transport=hf_transport)},
                   verifier=DependencyVerifier(DEPENDENCY_OBSERVATION), allow_live=True)
    with DurableRuntime(**options) as runtime:
        first = dependency(runtime)
        assert first.assurance == "data_contract_checked"
        assert runtime.audit()["liability_microusd"] == 19
    with DurableRuntime(**options) as runtime:
        assert dependency(runtime) == first
        assert runtime.audit()["calls"] == 2
        assert [item["provider"]["request_id"] for item in runtime.audit()["journal"]
                if "provider" in item] == ["injected-jev-id", "injected-hf-id"]
    assert sends == ["jev", "hf"]


@pytest.mark.skipif(os.name != "posix", reason="durable execution requires POSIX local storage")
def test_usage_above_reservation_is_recorded_and_breaches_run_bound(tmp_path):
    from grokcell.execution.checking import DependencyVerifier
    from grokcell.execution.durable import DurableRuntime
    from grokcell.execution.records import Limits, Permission
    from grokcell.execution.workflows import DEPENDENCY_OBSERVATION, workflow_identity
    from grokcell.execution.runtime import ExecutionBlocked

    body = response()
    body["usage"] = {"input_tokens": 10_000, "output_tokens": 0}
    runtime_options = dict(
        state_dir=tmp_path, run_id="provider-over-reservation",
        workflow_id=workflow_identity("dependency"),
        permission=Permission("test", "operator", ("read", "decide", "yield"), 2_000_000_000),
        dependencies=DEPENDENCY_OBSERVATION, limits=Limits(max_seconds=60),
        chooser=JevAdapter(replace(config(), max_charge_microusd=42),
                           transport=lambda *a: (body, "over-reserved", 1)),
        workers={}, verifier=DependencyVerifier(DEPENDENCY_OBSERVATION), allow_live=True)
    with DurableRuntime(**runtime_options) as runtime:
        observation = runtime.read("read", DEPENDENCY_OBSERVATION)
        decision = runtime.decide("decision", observation, OFFERS)
        assert decision.choice.id == "repair"
        audit = runtime.audit()
        assert audit["liability_microusd"] == 420
        assert audit["bound_breached"] is True
        with pytest.raises(ExecutionBlocked, match="accounting bound breached"):
            runtime.yield_control("stop")


def test_live_template_is_validated_non_authorizing_operator_configuration():
    from pathlib import Path
    template = json.loads((Path(__file__).parents[1] / "execution_live.template.json").read_text())
    assert template["authorized"] is False
    assert template["budget_scope"] == "credential_owner_no_bill_to_override"
    jev = ProviderConfig(**template["jev"])
    hf = ProviderConfig(**template["hf"])
    assert jev.model == "jev-1.13.0" and jev.expected_models == ("jev-1.13.0",)
    assert hf.model == "openai/gpt-oss-20b:ovhcloud"
    assert hf.expected_models == ("openai/gpt-oss-20b",)
    assert jev.max_charge_microusd + hf.max_charge_microusd <= template["limits"]["max_microusd"]


def test_transport_deadline_kills_controlled_child_without_network(monkeypatch):
    """Real subprocess deadline, with a trusted sleeping transport test double."""
    import subprocess
    import sys
    import time
    from grokcell.execution import providers

    popen = subprocess.Popen
    children = []
    def sleeping_child(command, **kwargs):
        # The API transport command is replaced before execution. No HTTP is sent.
        assert command[-1] == "grokcell.execution.http_worker"
        child = popen([sys.executable, "-c", "import time; time.sleep(30)"], **kwargs)
        children.append(child)
        return child

    monkeypatch.setenv("TYPESAFE_API_KEY", "synthetic-test-token")
    monkeypatch.setattr(providers.subprocess, "Popen", sleeping_child)
    started = time.monotonic()
    with pytest.raises(RuntimeError, match="outcome_unknown"):
        post(replace(config(), timeout_seconds=1), {"state": "public test"})
    assert time.monotonic() - started < 10
    assert len(children) == 1 and children[0].poll() is not None
