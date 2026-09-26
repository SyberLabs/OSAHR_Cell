"""Provider conformance uses injected transports; no live calls or credentials."""
from dataclasses import replace
import json

import pytest

from grokcell.execution.providers import (HuggingFaceWorker, JevAdapter, ProviderConfig,
                                         _NoRedirect, post, preflight)
from grokcell.execution.records import ActionOffer, JsonSnapshot, Observation


def config(provider="jev"):
    return ProviderConfig(provider, "jev-1.13.0" if provider == "jev" else "example/model:deepinfra",
                          ("jev-1.13.0",) if provider == "jev" else ("example/model",),
                          100_000, 0 if provider == "jev" else 200_000,
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
    assert reply.value == "repair" and reply.actual_microusd == 10
    assert reply.metadata.value()["request_id"] == "typesafe-request"
    assert reply.metadata.value()["output_tokens"] is None


def test_missing_billable_usage_is_unknown_not_zero():
    body = response()
    body["usage"] = {}
    reply = JevAdapter(config(), transport=lambda *args: (body, None, 0)).choose(OBSERVATION, OFFERS)
    assert reply.actual_microusd is None


@pytest.mark.parametrize("field,value", [("choice", "deploy"), ("confidence", True),
                                        ("confidence", float("nan")),
                                        ("probabilities", {"repair": 1.0})])
def test_jev_malformed_choice_refused(field, value):
    body = response()
    body["answers"]["next_action"][field] = value
    with pytest.raises(ValueError):
        JevAdapter(config(), transport=lambda *args: (body, None, 0)).choose(OBSERVATION, OFFERS)


def test_changed_model_refused():
    body = response()
    body["model"] = "unexpected-model"
    with pytest.raises(ValueError, match="model identity"):
        JevAdapter(config(), transport=lambda *args: (body, None, 0)).choose(OBSERVATION, OFFERS)


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
        return {"model": "example/model", "id": "hf-request", "usage": {
            "prompt_tokens": 100, "completion_tokens": 50}, "choices": [{"message": {
                "content": json.dumps({"module": "def add(a,b): return a+b"})}}]}, None, 8
    worker = HuggingFaceWorker(config("hf"), output_key="module", transport=transport)
    reply = worker.propose(JsonSnapshot.capture({"public_contract": "add"}))
    assert calls[0]["model"] == "example/model:deepinfra"
    assert calls[0]["stream"] is False and calls[0]["max_tokens"] == 1000
    assert reply.value.startswith(b"def add") and reply.actual_microusd == 20


@pytest.mark.parametrize("content", ['{"module":"ok","permission":"deploy"}', '{"module":false}', 'not json'])
def test_hf_invalid_module_payload_refused(content):
    def transport(*args):
        return {"model": "example/model", "choices": [{"message": {"content": content}}]}, None, 0
    with pytest.raises(ValueError):
        HuggingFaceWorker(config("hf"), output_key="module", transport=transport).propose(JsonSnapshot.capture({}))


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


def test_usage_bound_violation_is_visible():
    body = response()
    body["usage"]["input_tokens"] = 1001
    reply = JevAdapter(config(), transport=lambda *a: (body, None, 1)).choose(OBSERVATION, OFFERS)
    assert reply.metadata.value()["limits_breached"] is True


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
        return {"model": "example/model", "choices": [{"message": {
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
        assert runtime.audit()["liability_microusd"] == 30
    with DurableRuntime(**options) as runtime:
        assert dependency(runtime) == first
        assert runtime.audit()["calls"] == 2
        assert [item["provider"]["request_id"] for item in runtime.audit()["journal"]
                if "provider" in item] == ["injected-jev-id", "injected-hf-id"]
    assert sends == ["jev", "hf"]


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
