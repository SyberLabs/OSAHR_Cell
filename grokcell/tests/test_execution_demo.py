"""Demo, claims, data-only verifier and local rollback tests."""
from __future__ import annotations

import json
import os
import shutil
from pathlib import Path

import pytest

from grokcell.execution.checking import DependencyVerifier, IsolatedRepairVerifier, snapshot_directory, validate_arithmetic_component
from grokcell.execution.cli import _live_configuration, demo, execute, main, release_check
from grokcell.execution.records import Candidate, JsonSnapshot, canonical
from grokcell.execution.report import render_report, render_static_export, write_static_export
from grokcell.execution.runtime import ExecutionBlocked
from grokcell.execution.workflows import DEPENDENCY_OBSERVATION, REPAIRED_COMPONENT, assessment_bytes


def candidate(content, kind="dependency_assessment"):
    return Candidate(kind, content, "dependencies", 0, "test-attempt")


def test_dependency_checks_exact_source_facts_and_human_boundary():
    verifier = DependencyVerifier(DEPENDENCY_OBSERVATION)
    data = json.loads(assessment_bytes())
    assert all(check.status == "pass" for check in verifier.verify(candidate(canonical(data))))
    for key, value in (("to_version", "made-up"), ("source_hash", "forged"),
                       ("upgrade_authorized", True), ("review_required", False),
                       ("compatibility", "guaranteed")):
        altered = {**data, key: value}
        assert any(check.status == "fail" for check in verifier.verify(candidate(canonical(altered))))


def test_nonpython_asset_changes_snapshot(tmp_path):
    (tmp_path / "module.py").write_text("pass\n")
    fixture = tmp_path / "fixture.csv"
    fixture.write_text("a,1\n")
    first = snapshot_directory(tmp_path)
    fixture.write_text("a,2\n")
    assert snapshot_directory(tmp_path).identity != first.identity
    (tmp_path / "link").symlink_to(fixture)
    with pytest.raises(ValueError, match="symlink"):
        snapshot_directory(tmp_path)


def test_demo_builds_real_reports_and_replays_in_fresh_processes(tmp_path):
    out = tmp_path / "demo"
    result = demo(out)
    assert result["live_provider_calls"] == 0
    assert result["process_restart_replay"] is True
    for name in ("repair", "dependency"):
        run = json.loads((out / (name + ".json")).read_text())
        assert run["audit"]["calls"] == 2 and run["audit"]["revision"] == 1
        assert run["audit"]["durable"] is True
    html = (out / "index.html").read_text()
    assert "OFFLINE FIXTURES" in html and "not a production" in html
    with pytest.raises(FileExistsError):
        demo(out)


def test_report_escapes_candidate_html():
    run = {"workflow": "dependency", "description": "test", "candidate": "",
           "audit": {"journal": [], "accepted": [], "calls": 0, "revision": 0,
                     "liability_microusd": 0, "live_execution_enabled": False,
                     "verification_mode": "data_only"}}
    run["candidate"] = '<script>alert("xss")</script>'
    rendered = render_report([run])
    assert '<script>alert(' not in rendered
    assert '&lt;script&gt;' in rendered


def test_report_shows_provider_model_and_effort_only_when_observed():
    run = {"workflow": "repair", "description": "fixture", "candidate": "candidate",
           "audit": {"journal": [], "accepted": [], "calls": 0, "revision": 0,
                     "liability_microusd": 0, "live_execution_enabled": False}}
    offline = render_report([run])
    assert "OFFLINE FIXTURES" in offline
    assert "Observed provider details" not in offline
    run["audit"]["journal"] = [{"step": "proposal", "operation": "generate",
                                "status": "complete", "reserved": 0,
                                "provider": {"provider": "hf", "requested_model": "org/model:route",
                                             "returned_model": "org/model"}}]
    observed = render_report([run])
    assert "org/model:route" in observed
    assert "org/model</dd>" in observed
    assert "Reasoning effort" not in observed
    run["audit"]["journal"][0]["provider"]["reasoning_effort"] = "high"
    assert "Reasoning effort</dt><dd>high</dd>" in render_report([run])


def test_local_release_rollback_preserves_effect_ledger(tmp_path):
    result = release_check(tmp_path / "release")
    assert result["rollback_verified"] is True
    assert result["failure_exit_code"] == 42
    assert result["adapter_calls_after_rollback"] == 2


def test_resume_missing_state_does_not_reset_run(tmp_path):
    with pytest.raises(RuntimeError, match="does not exist"):
        execute("repair", tmp_path / "missing", resume=True)
    assert not (tmp_path / "missing").exists()


def test_live_requires_operator_configuration_before_state_creation(tmp_path):
    state = tmp_path / "live"
    assert main(["run", "--workflow", "repair", "--state", str(state), "--mode", "live"]) == 2
    assert not state.exists()


def test_live_configuration_uses_supplied_s04_template_without_provider_calls(tmp_path, monkeypatch):
    template = Path(__file__).parents[1] / "execution_live.template.json"
    if not template.is_file():
        pytest.skip("S04 provider template is integrated in the next session step")
    data = json.loads(template.read_text(encoding="utf-8"))
    if (data.get("budget_scope") != "credential_owner_no_bill_to_override"
            or any(data.get(name, {}).get("billing_scope") != "credential_owner" for name in ("jev", "hf"))):
        pytest.skip("S04 provider schema is not integrated on this worker base")
    assert data["authorized"] is False
    with pytest.raises(ExecutionBlocked, match="authorization"):
        _live_configuration(template)

    data["authorized"] = True
    config = tmp_path / "reviewed-config.json"
    config.write_text(json.dumps(data), encoding="utf-8")
    monkeypatch.setattr("grokcell.execution.cli.preflight", lambda: {
        "live_calls_made": 0, "typesafe_credential_present": True,
        "hf_credential_present": True, "docker_cli_present": False,
        "sandbox_image_configured": False, "independent_review_recorded": False,
    })
    limits, jev, hf = _live_configuration(config)
    assert limits.max_microusd == data["limits"]["max_microusd"]
    assert (jev.model, jev.billing_scope) == (data["jev"]["model"], "credential_owner")
    assert (hf.model, hf.billing_scope) == (data["hf"]["model"], "credential_owner")


def test_static_export_is_offline_allowlisted_and_has_only_upload_assets(tmp_path):
    run = {
        "workflow": "repair",
        "description": "untrusted description that is not published",
        "candidate": "private candidate source",
        "audit": {
            "live_execution_enabled": False,
            "calls": 2,
            "revision": 1,
            "journal": [{"step": "CHECK", "operation": "compare", "status": "pass",
                         "provider": {"token": "should never be exported"},
                         "private_path": "C:/private/state"}],
            "raw_provider_payload": "must not leak",
        },
        "replay_equal": True,
    }
    html = render_static_export([run])
    assert "private candidate source" not in html
    assert "should never be exported" not in html
    assert "C:/private/state" not in html
    assert "must not leak" not in html
    assert "RECORDED OFFLINE FIXTURES" in html
    assert "Component repair" in html

    export = tmp_path / "public"
    write_static_export(export, [run])
    assert sorted(path.name for path in export.iterdir()) == ["_headers", "index.html"]
    assert "Content-Security-Policy" in (export / "_headers").read_text(encoding="utf-8")


def test_static_export_refuses_live_or_unknown_workflows():
    live = {"workflow": "repair", "audit": {"live_execution_enabled": True}}
    with pytest.raises(ValueError, match="offline"):
        render_static_export([live])
    unknown = {"workflow": "unknown", "audit": {"live_execution_enabled": False}}
    with pytest.raises(ValueError, match="unsupported workflow"):
        render_static_export([unknown])


@pytest.mark.skipif(not shutil.which("docker") or not os.getenv("GROKCELL_SANDBOX_IMAGE"),
                    reason="actual Docker/image required; no host fallback")
def test_actual_isolation_checks_valid_and_wrong_behavior():
    image = os.environ["GROKCELL_SANDBOX_IMAGE"]
    verifier = IsolatedRepairVerifier(image)
    valid = candidate(REPAIRED_COMPONENT, "python_component")
    assert all(check.status == "pass" for check in verifier.verify(valid))
    wrong = candidate(REPAIRED_COMPONENT.replace(b"return on_hand - reserved", b"return on_hand + reserved"), "python_component")
    assert any(check.status == "fail" for check in verifier.verify(wrong))
    bool_result = candidate(REPAIRED_COMPONENT.replace(b"return on_hand - reserved", b"return False if on_hand == reserved else on_hand - reserved"), "python_component")
    assert any(check.status == "fail" for check in verifier.verify(bool_result))
    for attack in (b"import os\nos._exit(0)\n", b"def available(a,b):\n    print('completed: true')\n    return 0\n"):
        assert verifier.verify(candidate(attack, "python_component"))[0].status == "fail"


def test_narrow_language_rejects_shared_serializer_mutation_without_executing_it():
    from grokcell.repair_guard import validate_module
    attack = "import json\ndef fake(x):\n    return 'forged'\ndef available(a,b):\n    json.dumps = fake\n    return 0\n"
    validate_module(attack)  # Source-level gap in a broader language, not a live exploit claim.
    with pytest.raises(ValueError):
        validate_arithmetic_component(attack)
    validate_arithmetic_component(REPAIRED_COMPONENT.decode())


@pytest.mark.parametrize("source", [
    "def available(a,b):\n    while True: pass\n",
    "def available(a,b):\n    return type('X', (), {})\n",
    "def available(a,b=1):\n    return a-b\n",
    "def available(a,b):\n    return a.real-b\n"])
def test_arithmetic_language_rejects_unsupported_surface(source):
    with pytest.raises(ValueError):
        validate_arithmetic_component(source)
