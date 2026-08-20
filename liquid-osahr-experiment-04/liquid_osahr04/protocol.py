"""Frozen Experiment 04 protocol constants."""
from __future__ import annotations

from pathlib import Path

EXPERIMENT_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = EXPERIMENT_ROOT.parent
EXP02B = REPO_ROOT / "liquid-osahr-experiment-02b" / "liquid-osahr-exp02b-stage-final"
EXP03 = REPO_ROOT / "liquid-osahr-experiment-03"

CALIBRATION_SEED = 440318
CONFIRMATORY_SEED = 880419
HORIZON = 3.0
GRID = (0.0, 0.25, 0.5, 1.0)
LAMBDA = 0.1
CAL_REGIMES = ("id", "high_mobility", "high_stress")
CONF_REGIMES = ("id", "high_mobility", "high_stress", "weak_channel")
ESTIMANDS = ("goal_utility_ratio", "critical_success_rate", "mean_latency")
POLICIES = ("throughput", "semantic")
CAL_SCENARIOS = 6
CONF_SCENARIOS = 5
REPLICATES = 2

ARM_SPECS = (
    ("oracle", "oracle", 1.0),
    ("mechanistic_calibrated", "mechanistic", 0.0),
    ("residual_quarter", "residual_quarter", 0.25),
    ("residual_idcal", "residual_idcal", 0.5),
    ("residual_predictive", "residual_predictive", 1.0),
)

ART = EXPERIMENT_ROOT / "artifacts"
CAL_CSV = ART / "calibration_release.csv"
CONF_CSV = ART / "confirmatory_release.csv"
FROZEN_PATH = ART / "FROZEN.json"


def calibration_scenario_seed_offset(regime_index: int) -> int:
    return CALIBRATION_SEED + 2113 * regime_index


def confirmatory_scenario_seed_offset(regime_index: int) -> int:
    return CONFIRMATORY_SEED + 4229 * regime_index


def calibration_scenario_id(regime_index: int, scenario: int) -> int:
    return 20000 + 100 * regime_index + scenario


def confirmatory_scenario_id(regime_index: int, scenario: int) -> int:
    return 90000 + 100 * regime_index + scenario
