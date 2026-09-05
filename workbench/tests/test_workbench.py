"""Adversarial tests for the NetworkBrain decision packet.

These tests are the red team. A packet that grants a claim license on
hold_unresolved, recommends the illegal-edge MAE winner, or accepts
attacker-supplied ensembles is a product failure — not a missing feature.
"""
from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

from workbench.packet import (
    ALLOWED_SEED_MIX,
    WorkbenchError,
    assert_analysis_legal,
    build_packet,
    packet_checksum,
    render_html,
    replay_packet,
    require_complete_ensemble,
    validate_scenario,
)

REPO = Path(__file__).resolve().parents[2]
SCENARIOS = REPO / "workbench" / "scenarios"
ANALYSIS = REPO / "liquid-osahr-experiment-06" / "artifacts" / "analysis.json"
FREEZE = REPO / "liquid-osahr-experiment-06" / "artifacts" / "FROZEN.json"


def _load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _scenario(name: str) -> dict:
    return _load(SCENARIOS / name)


def test_identity_scenario_admits_negative_effect_and_keeps_baseline():
    packet = build_packet(_scenario("01-identity.json"), ANALYSIS, FREEZE)
    assert packet["comparison"]["claim"]["status"] == "admit"
    assert packet["comparison"]["claim"]["oracle_sign"] == -1
    assert packet["licenses"]["claim"]["granted"] is True
    assert packet["licenses"]["action"]["granted"] is True
    assert packet["recommendation"]["action"] == "keep_baseline"
    assert packet["recommendation"]["arm"] == "throughput"


def test_high_stress_recommends_vault_gated_not_scalar_mae_winner():
    packet = build_packet(_scenario("02-high-stress.json"), ANALYSIS, FREEZE)
    assert packet["comparison"]["claim"]["status"] == "admit"
    assert packet["comparison"]["claim"]["oracle_sign"] == 1
    assert packet["recommendation"]["action"] == "adopt_semantic"
    assert packet["recommendation"]["arm"] == "vault_gated"
    assert packet["recommendation"]["arm"] != "scalar_semantic"


def test_long_outage_licenses_action_and_denies_directed_claim():
    packet = build_packet(_scenario("03-long-outage.json"), ANALYSIS, FREEZE)
    assert packet["comparison"]["claim"]["status"] == "hold_unresolved"
    assert packet["licenses"]["action"]["granted"] is True
    assert packet["licenses"]["action"]["kind"] == "select"
    assert packet["licenses"]["claim"]["granted"] is False
    assert packet["licenses"]["claim"]["kind"] == "none"
    assert packet["recommendation"]["action"] == "act_under_hold"
    banned = " ".join(packet["recommendation"]["do_not_claim"]).lower()
    assert "directed" in banned or "sign" in banned


def test_attacker_cannot_force_claim_license_on_hold():
    scenario = _scenario("03-long-outage.json")
    packet = build_packet(scenario, ANALYSIS, FREEZE)
    forged = copy.deepcopy(packet)
    forged["licenses"]["claim"] = {
        "granted": True,
        "kind": "directed_effect",
        "reason": "point estimates are all negative",
    }
    forged["checksum"] = packet_checksum(forged)
    with pytest.raises(WorkbenchError, match="license"):
        replay_packet(forged, ANALYSIS, FREEZE)


def test_scalar_semantic_is_never_the_recommended_arm():
    for name in ("01-identity.json", "02-high-stress.json", "03-long-outage.json"):
        packet = build_packet(_scenario(name), ANALYSIS, FREEZE)
        assert packet["recommendation"]["arm"] != "scalar_semantic"


def test_real_network_calibration_cannot_be_measured():
    packet = build_packet(_scenario("01-identity.json"), ANALYSIS, FREEZE)
    assert packet["grades"]["real_network_calibration"] == "PROPOSED"
    forged = copy.deepcopy(packet)
    forged["grades"]["real_network_calibration"] = "MEASURED"
    forged["checksum"] = packet_checksum(forged)
    with pytest.raises(WorkbenchError):
        replay_packet(forged, ANALYSIS, FREEZE)


def test_policy_in_seed_mix_is_refused():
    scenario = _scenario("01-identity.json")
    scenario["seed_mix"] = ["root", "scenario", "replicate", "policy"]
    with pytest.raises(WorkbenchError, match="seed"):
        validate_scenario(scenario)
    assert ALLOWED_SEED_MIX == ("root", "scenario", "replicate")


def test_fabricated_ensemble_without_freeze_provenance_is_refused():
    scenario = _scenario("01-identity.json")
    fake_analysis = {
        "seed": 1,
        "llm_in_confirmatory": False,
        "scenarios": [
            {
                "scenario": 1,
                "regime": "id",
                "status": "admit",
                "oracle_delta": 0.9,
                "arm_deltas": {
                    "scalar_semantic": 0.9,
                    "vault_gated": 0.9,
                    "brain_at_hold": 0.9,
                },
                "claim": {
                    "status": "admit",
                    "oracle_sign": 1,
                    "oracle_effect": 0.9,
                    "effects_by_alpha": {
                        "0.00": 0.9,
                        "0.25": 0.9,
                        "0.50": 0.9,
                        "1.00": 0.9,
                    },
                    "notes": "attacker-supplied",
                },
            }
        ],
    }
    fake_path = SCENARIOS / "_forged_analysis.json"
    fake_path.write_text(json.dumps(fake_analysis), encoding="utf-8")
    try:
        with pytest.raises(WorkbenchError, match="provenance|freeze|checksum"):
            build_packet(scenario, fake_path, FREEZE)
    finally:
        fake_path.unlink(missing_ok=True)


def test_unknown_scenario_fails_loud_instead_of_minting_a_packet():
    scenario = _scenario("01-identity.json")
    scenario["id"] = 99
    scenario["name"] = "invented"
    with pytest.raises(WorkbenchError, match="corpus|unknown|underidentified"):
        build_packet(scenario, ANALYSIS, FREEZE)


def test_incomplete_ensemble_is_refused():
    with pytest.raises(WorkbenchError, match="ensemble|alpha|incomplete"):
        require_complete_ensemble({"effects_by_alpha": {"0.00": -0.01}})


def test_llm_in_confirmatory_refuses_the_packet():
    with pytest.raises(WorkbenchError, match="LLM"):
        assert_analysis_legal(
            {"llm_in_confirmatory": True, "seed": 260826, "scenarios": []}
        )


def test_missing_scenario_fields_fail_loud():
    with pytest.raises(WorkbenchError):
        validate_scenario({"id": 1})


def test_replay_accepts_untampered_packet():
    packet = build_packet(_scenario("02-high-stress.json"), ANALYSIS, FREEZE)
    replayed = replay_packet(packet, ANALYSIS, FREEZE)
    assert replayed["checksum"] == packet["checksum"]
    assert replayed["checksum"] == packet_checksum(packet)


def test_mutated_checksum_fails_replay():
    packet = build_packet(_scenario("01-identity.json"), ANALYSIS, FREEZE)
    packet["checksum"] = "0" * 64
    with pytest.raises(WorkbenchError, match="checksum"):
        replay_packet(packet, ANALYSIS, FREEZE)


def test_html_report_cannot_display_denied_claim_as_fact():
    packet = build_packet(_scenario("03-long-outage.json"), ANALYSIS, FREEZE)
    html = render_html(packet)
    assert "CLAIM LICENSE: DENIED" in html
    assert "<script>" not in html
    assert "licensed directed effect" not in html.lower() or "not a licensed" in html.lower()


def test_html_escapes_attacker_text():
    packet = build_packet(_scenario("01-identity.json"), ANALYSIS, FREEZE)
    packet["recommendation"]["rationale"] = "<script>alert(1)</script>"
    html = render_html(packet)
    assert "<script>alert(1)</script>" not in html
    assert "&lt;script&gt;" in html


def test_packet_separates_known_measured_inferred_proposed():
    packet = build_packet(_scenario("02-high-stress.json"), ANALYSIS, FREEZE)
    grades = packet["grades"]
    assert grades["kernel_semantics"] == "KNOWN"
    assert grades["ensemble_deltas"] == "MEASURED"
    assert grades["load_penalty_as_02B_residual"] == "INFERRED"
    assert grades["real_network_calibration"] == "PROPOSED"
    assert grades["semantic_advantage_without_triage"] == "KNOWN"
    note = packet["grades_notes"]["semantic_advantage_without_triage"].lower()
    assert "no advantage" in note or "triage" in note


def test_cli_writes_json_html_and_replays(tmp_path):
    from workbench.decide import main

    out = tmp_path / "packet"
    rc = main(
        [
            "decide",
            str(SCENARIOS / "03-long-outage.json"),
            "--out",
            str(out),
        ]
    )
    assert rc == 0
    payload = _load(out / "decision.json")
    assert payload["licenses"]["claim"]["granted"] is False
    html = (out / "decision.html").read_text(encoding="utf-8")
    assert "CLAIM LICENSE: DENIED" in html
    assert main(["replay", str(out / "decision.json")]) == 0
