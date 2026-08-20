"""Frozen Experiment 05 protocol constants."""
from __future__ import annotations

from pathlib import Path

EXPERIMENT_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = EXPERIMENT_ROOT.parent
EXP02B = REPO_ROOT / "liquid-osahr-experiment-02b" / "liquid-osahr-exp02b-stage-final"
EXP03 = REPO_ROOT / "liquid-osahr-experiment-03"
EXP04 = REPO_ROOT / "liquid-osahr-experiment-04"

CLAIM_GRAMMAR_VERSION = "osahr05_claim_v0"
CONFIRMATORY_SEED = 110518
HORIZON = 22.0
GRID = (0.0, 0.25, 0.5, 1.0)
EPS_ZERO = 0.0
EPS_SENSITIVITY = 0.02
REGIMES = ("id", "high_mobility", "high_stress", "weak_channel")
ESTIMANDS = ("goal_utility_ratio", "critical_success_rate", "mean_latency")
POLICIES = ("throughput", "semantic")
N_SCENARIOS = 6
REPLICATES = 2
ACTIVATION_COUNTS = ("events", "outages", "handovers", "reroutes")
INTERVENTION = "semantic_vs_throughput"
PRIMARY_ESTIMAND = "goal_utility_ratio"

ARM_SPECS = (
    ("oracle", "oracle", 1.0),
    ("mechanistic_calibrated", "mechanistic", 0.0),
    ("residual_quarter", "residual_quarter", 0.25),
    ("residual_idcal", "residual_idcal", 0.5),
    ("residual_predictive", "residual_predictive", 1.0),
)

ARM_BY_ALPHA = {
    0.0: "mechanistic_calibrated",
    0.25: "residual_quarter",
    0.5: "residual_idcal",
    1.0: "residual_predictive",
}

# Frozen 04 T_strict cells, used only as an illegal-promotion foil.
T04_STRICT = {
    ("goal_utility_ratio", "id"): 0.0,
    ("goal_utility_ratio", "high_mobility"): 1.0,
    ("goal_utility_ratio", "high_stress"): 0.25,
    ("goal_utility_ratio", "weak_channel"): 0.0,
    ("critical_success_rate", "id"): 0.5,
    ("critical_success_rate", "high_mobility"): 1.0,
    ("critical_success_rate", "high_stress"): 0.5,
    ("critical_success_rate", "weak_channel"): 0.0,
    ("mean_latency", "id"): 1.0,
    ("mean_latency", "high_mobility"): 1.0,
    ("mean_latency", "high_stress"): 0.25,
    ("mean_latency", "weak_channel"): 0.0,
}

ART = EXPERIMENT_ROOT / "artifacts"
CONF_CSV = ART / "confirmatory_release.csv"
FROZEN_PATH = ART / "FROZEN.json"
INSTRUMENT_04_CSV = EXP04 / "artifacts" / "confirmatory_release.csv"

GRAMMAR_FILES = (
    EXPERIMENT_ROOT / "liquid_osahr05" / "protocol.py",
    EXPERIMENT_ROOT / "liquid_osahr05" / "claims.py",
)


def confirmatory_scenario_seed_offset(regime_index: int) -> int:
    return CONFIRMATORY_SEED + 5227 * regime_index


def confirmatory_scenario_id(regime_index: int, scenario: int) -> int:
    return 150000 + 100 * regime_index + scenario
