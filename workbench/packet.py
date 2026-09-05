"""Licensed decision packets over the frozen Experiment 06 corpus.

Not the kernel. Not a second simulator. A packet is minted only from
freeze-pinned confirmatory artifacts. Action license and claim license
are separate. Replay recomputes both.
"""
from __future__ import annotations

import hashlib
import html
import json
import sys
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parent.parent
for _path in (REPO, REPO / "liquid-osahr-experiment-06", REPO / "liquid-osahr-experiment-05"):
    _text = str(_path)
    if _text not in sys.path:
        sys.path.insert(0, _text)

from liquid_osahr05.claims import ActivationCounts, score_claim
from osahr_cell.freeze import require_freeze

ALLOWED_SEED_MIX = ("root", "scenario", "replicate")
SCENARIO_SCHEMA = "osahr_workbench_scenario_v0"
PACKET_VERSION = "osahr_workbench_v0"
HYPOTHESIS_KEYS = ("0.00", "0.25", "0.50", "1.00")
REQUIRED_SCENARIO = (
    "schema",
    "id",
    "name",
    "operator_role",
    "decision",
    "horizon_s",
    "root_seed",
    "seed_mix",
    "baseline_policy",
    "semantic_policy",
    "estimand",
)

CORPUS_PATH = Path(__file__).resolve().parent / "corpus.json"

GRADES = {
    "kernel_semantics": "KNOWN",
    "ensemble_deltas": "MEASURED",
    "load_penalty_as_02B_residual": "INFERRED",
    "real_network_calibration": "PROPOSED",
    "semantic_advantage_without_triage": "KNOWN",
}
GRADES_NOTES = {
    "kernel_semantics": "OSAHR 0.2 contract: state is (G, B, R, parameters, memory, t, n).",
    "ensemble_deltas": "Experiment 06 confirmatory seed 260826, horizon 60 s.",
    "load_penalty_as_02B_residual": "H = {0, 0.25, 0.5, 1} is a load-penalty mix, not the 02B CfC field.",
    "real_network_calibration": "Surrogate twin. Not ns-3, srsRAN, or a live RAN.",
    "semantic_advantage_without_triage": (
        "6G no-outage control: 0.8778 vs 0.8783 goal utility. Semantic "
        "routing has no advantage unless capacity must be triaged."
    ),
}


class WorkbenchError(ValueError):
    """Fail loud. Do not mint a licensed packet."""


def _dumps(payload: Any) -> str:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path) -> str:
    return sha256_bytes(path.read_bytes())


def packet_checksum(packet: dict[str, Any]) -> str:
    body = {key: value for key, value in packet.items() if key != "checksum"}
    return sha256_bytes(_dumps(body).encode("utf-8"))


def validate_scenario(scenario: dict[str, Any]) -> dict[str, Any]:
    missing = [key for key in REQUIRED_SCENARIO if key not in scenario]
    if missing:
        raise WorkbenchError(f"scenario missing required fields: {missing}")
    if scenario["schema"] != SCENARIO_SCHEMA:
        raise WorkbenchError(f"unsupported scenario schema {scenario['schema']!r}")
    mix = tuple(scenario["seed_mix"])
    if mix != ALLOWED_SEED_MIX:
        raise WorkbenchError(
            f"seed mix {list(mix)} is refused; policy must not enter the seed"
        )
    if scenario["semantic_policy"] != "vault_gated":
        raise WorkbenchError("semantic_policy must be vault_gated; scalar_semantic is not an intervention policy")
    if scenario["baseline_policy"] != "throughput":
        raise WorkbenchError("baseline_policy must be throughput")
    if scenario["estimand"] != "goal_utility_ratio":
        raise WorkbenchError("estimand must be goal_utility_ratio")
    if float(scenario["horizon_s"]) <= 0:
        raise WorkbenchError("horizon_s must be positive")
    return scenario


def require_complete_ensemble(claim: dict[str, Any]) -> dict[str, float]:
    raw = claim.get("effects_by_alpha")
    if not isinstance(raw, dict):
        raise WorkbenchError("incomplete ensemble: effects_by_alpha missing")
    keys = tuple(sorted(raw, key=lambda item: float(item)))
    expected = HYPOTHESIS_KEYS
    if keys != expected:
        raise WorkbenchError(
            f"incomplete ensemble: expected alphas {expected}, got {keys}"
        )
    return {float(key): float(raw[key]) for key in expected}


def assert_analysis_legal(analysis: dict[str, Any]) -> None:
    if analysis.get("llm_in_confirmatory") is True:
        raise WorkbenchError("refusing packet: LLM in confirmatory")
    if int(analysis.get("seed", -1)) != 260826:
        raise WorkbenchError("analysis seed is not the declared confirmatory seed")
    if not analysis.get("scenarios"):
        raise WorkbenchError("analysis has no scenarios")


def _rescore(claim: dict[str, Any]) -> None:
    effects = require_complete_ensemble(claim)
    scored = score_claim(
        estimand=str(claim.get("estimand", "goal_utility_ratio")),
        regime=str(claim["regime"]),
        scenario=int(claim["scenario"]),
        oracle_effect=float(claim["oracle_effect"]),
        effects_by_alpha=effects,
        activation=ActivationCounts(1.0, 0.0, 0.0, 0.0),
        horizon=float(claim["horizon"]),
        eps=float(claim.get("eps", 0.0)),
        intervention=str(claim.get("intervention", "semantic_vs_throughput")),
    )
    if scored.status != claim["status"]:
        raise WorkbenchError("claim status does not match the ensemble grammar")
    if int(scored.oracle_sign) != int(claim["oracle_sign"]):
        raise WorkbenchError("oracle sign does not match the ensemble grammar")


def _licenses(status: str) -> tuple[dict[str, Any], dict[str, Any]]:
    if status == "admit":
        return (
            {
                "granted": True,
                "kind": "kernel",
                "reason": "admit: kernel fires the vault-legal match",
            },
            {
                "granted": True,
                "kind": "directed_effect",
                "reason": "ensemble and oracle agree",
            },
        )
    if status == "hold_unresolved":
        return (
            {
                "granted": True,
                "kind": "select",
                "reason": "hold: Brain may select among vault-legal matches",
            },
            {
                "granted": False,
                "kind": "none",
                "reason": "residual signs disagree; directed effect is not licensed",
            },
        )
    return (
        {
            "granted": False,
            "kind": "withhold",
            "reason": f"{status}: park must refuse a rewrite",
        },
        {
            "granted": False,
            "kind": "none",
            "reason": f"{status}: no directed-effect license",
        },
    )


def _recommend(status: str, oracle_sign: int) -> dict[str, Any]:
    if status == "admit" and oracle_sign < 0:
        return {
            "action": "keep_baseline",
            "arm": "throughput",
            "rationale": (
                "Licensed directed effect: semantic contrast vs throughput is "
                "negative. Keep the baseline policy."
            ),
            "do_not_claim": ["real-network calibration"],
        }
    if status == "admit" and oracle_sign > 0:
        return {
            "action": "adopt_semantic",
            "arm": "vault_gated",
            "rationale": (
                "Licensed directed effect: vault-gated semantic beats throughput. "
                "Do not treat scalar_semantic as the intervention policy; it uses "
                "degraded-fidelity edges the vault forbids for critical tasks."
            ),
            "do_not_claim": [
                "scalar_semantic is the intervention policy",
                "real-network calibration",
            ],
        }
    if status == "hold_unresolved":
        return {
            "action": "act_under_hold",
            "arm": "brain_at_hold",
            "rationale": (
                "Action license only. Select among vault-legal matches. "
                "Point-estimate signs are not a licensed directed effect."
            ),
            "do_not_claim": [
                "directed effect sign of semantic vs throughput",
                "MAE-lowest arm as the intervention policy",
                "real-network calibration",
            ],
        }
    return {
        "action": "withhold",
        "arm": None,
        "rationale": "Neither action nor claim is licensed.",
        "do_not_claim": ["any directed effect", "real-network calibration"],
    }


def _load_corpus() -> dict[str, Any]:
    return json.loads(CORPUS_PATH.read_text(encoding="utf-8"))


def verify_corpus(analysis_path: Path, freeze_path: Path) -> dict[str, Any]:
    corpus = _load_corpus()
    analysis_hash = sha256_file(analysis_path)
    freeze_hash = sha256_file(freeze_path)
    if analysis_hash != corpus["analysis_sha256"]:
        raise WorkbenchError("analysis checksum failed provenance pin")
    if freeze_hash != corpus["freeze_sha256"]:
        raise WorkbenchError("freeze checksum failed provenance pin")
    try:
        require_freeze(freeze_path)
    except SystemExit as exc:
        raise WorkbenchError(f"freeze invalid: {exc}") from exc
    return corpus


def _row_for_scenario(analysis: dict[str, Any], scenario_id: int) -> dict[str, Any]:
    for row in analysis["scenarios"]:
        if int(row["scenario"]) == int(scenario_id):
            return row
    raise WorkbenchError(
        f"underidentified: scenario {scenario_id} is not in the evaluation corpus"
    )


def build_packet(
    scenario: dict[str, Any],
    analysis_path: Path | str,
    freeze_path: Path | str,
) -> dict[str, Any]:
    scenario = validate_scenario(dict(scenario))
    analysis_path = Path(analysis_path)
    freeze_path = Path(freeze_path)
    corpus = verify_corpus(analysis_path, freeze_path)
    analysis = json.loads(analysis_path.read_text(encoding="utf-8"))
    assert_analysis_legal(analysis)
    if int(scenario["root_seed"]) != int(corpus["confirmatory_seed"]):
        raise WorkbenchError("scenario root_seed is not the confirmatory seed")
    if int(analysis["seed"]) != int(scenario["root_seed"]):
        raise WorkbenchError("analysis seed does not match scenario root_seed")
    row = _row_for_scenario(analysis, int(scenario["id"]))
    claim = dict(row["claim"])
    _rescore(claim)
    status = str(claim["status"])
    oracle_sign = int(claim["oracle_sign"])
    action_license, claim_license = _licenses(status)
    recommendation = _recommend(status, oracle_sign)
    if recommendation["arm"] == "scalar_semantic":
        raise WorkbenchError("scalar_semantic cannot be the recommended arm")
    packet = {
        "packet_version": PACKET_VERSION,
        "job": {
            "operator": scenario["operator_role"],
            "decision": scenario["decision"],
            "horizon_s": scenario["horizon_s"],
        },
        "scenario": scenario,
        "provenance": {
            "root_seed": scenario["root_seed"],
            "seed_mix": list(ALLOWED_SEED_MIX),
            "analysis_sha256": corpus["analysis_sha256"],
            "freeze_sha256": corpus["freeze_sha256"],
            "llm_in_run": False,
            "model_scope": "abstraction; not a calibrated real network",
            "corpus": str(CORPUS_PATH.relative_to(REPO)),
        },
        "grades": dict(GRADES),
        "grades_notes": dict(GRADES_NOTES),
        "comparison": {
            "baseline": scenario["baseline_policy"],
            "semantic": scenario["semantic_policy"],
            "oracle": "oracle_vault_greedy",
            "estimand": scenario["estimand"],
            "oracle_delta": row["oracle_delta"],
            "arm_deltas": row["arm_deltas"],
            "claim": claim,
        },
        "licenses": {"action": action_license, "claim": claim_license},
        "recommendation": recommendation,
        "human_approval": {"required": True, "status": "pending"},
    }
    packet["checksum"] = packet_checksum(packet)
    return packet


def replay_packet(
    packet: dict[str, Any],
    analysis_path: Path | str,
    freeze_path: Path | str,
) -> dict[str, Any]:
    stored = packet.get("checksum")
    if stored != packet_checksum(packet):
        raise WorkbenchError("packet checksum mismatch")
    expected = build_packet(packet["scenario"], analysis_path, freeze_path)
    if packet["licenses"] != expected["licenses"]:
        raise WorkbenchError("stored licenses do not recompute")
    if packet["grades"] != expected["grades"]:
        raise WorkbenchError("stored grades do not recompute")
    if packet["recommendation"]["arm"] != expected["recommendation"]["arm"]:
        raise WorkbenchError("stored recommendation does not recompute")
    if packet["recommendation"]["action"] != expected["recommendation"]["action"]:
        raise WorkbenchError("stored recommendation does not recompute")
    return expected


def render_html(packet: dict[str, Any]) -> str:
    claim_ok = packet["licenses"]["claim"]["granted"]
    action_ok = packet["licenses"]["action"]["granted"]
    claim_banner = "CLAIM LICENSE: GRANTED" if claim_ok else "CLAIM LICENSE: DENIED"
    action_banner = "ACTION LICENSE: GRANTED" if action_ok else "ACTION LICENSE: DENIED"
    rec = packet["recommendation"]
    claim = packet["comparison"]["claim"]
    hold_note = ""
    if not claim_ok:
        hold_note = (
            "<p>Action may proceed only under the action license. "
            "This is not a licensed directed effect.</p>"
        )
    do_not = "".join(f"<li>{html.escape(str(item))}</li>" for item in rec["do_not_claim"])
    grades = "".join(
        f"<tr><td>{html.escape(key)}</td><td>{html.escape(value)}</td>"
        f"<td>{html.escape(packet['grades_notes'][key])}</td></tr>"
        for key, value in packet["grades"].items()
    )
    return (
        "<!DOCTYPE html><html lang=\"en\"><head><meta charset=\"utf-8\">"
        "<title>OSAHR decision packet</title>"
        "<style>body{font-family:sans-serif;max-width:52rem;margin:2rem auto;}"
        f".denied{{background:#4a0000;color:#fff;padding:0.75rem}}"
        f".granted{{background:#063;color:#fff;padding:0.75rem}}</style></head><body>"
        f"<h1>OSAHR decision packet</h1>"
        f"<p class=\"{'granted' if action_ok else 'denied'}\">{html.escape(action_banner)}</p>"
        f"<p class=\"{'granted' if claim_ok else 'denied'}\">{html.escape(claim_banner)}</p>"
        f"{hold_note}"
        f"<h2>Recommendation</h2>"
        f"<p><strong>{html.escape(str(rec['action']))}</strong> "
        f"arm={html.escape(str(rec['arm']))}</p>"
        f"<p>{html.escape(str(rec['rationale']))}</p>"
        f"<h2>Do not claim</h2><ul>{do_not}</ul>"
        f"<h2>Claim grammar</h2>"
        f"<p>status={html.escape(str(claim['status']))} "
        f"oracle_sign={html.escape(str(claim['oracle_sign']))}</p>"
        f"<h2>Grades</h2>"
        f"<table><thead><tr><th>Item</th><th>Grade</th><th>Note</th></tr></thead>"
        f"<tbody>{grades}</tbody></table>"
        f"<p>checksum {html.escape(packet.get('checksum', ''))}</p>"
        f"<p>Human approval: pending. Replay with "
        f"<code>python -m workbench replay decision.json</code>.</p>"
        "</body></html>\n"
    )
