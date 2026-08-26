"""Frozen Experiment 06 protocol constants.

Confirmatory root seed 260826 is declared here before any confirmatory
trajectory is executed. Do not retune this file after freeze.
"""
from __future__ import annotations

from pathlib import Path

EXPERIMENT_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = EXPERIMENT_ROOT.parent
EXP05 = REPO_ROOT / "liquid-osahr-experiment-05"
G6_RELEASE = REPO_ROOT / "osahr-6g" / "osahr_6g_experiment_release"

CONCEPTS_DIR = EXPERIMENT_ROOT / "vault" / "concepts"
CLAIMS_NOTES_DIR = EXPERIMENT_ROOT / "vault" / "claims"
ART = EXPERIMENT_ROOT / "artifacts"
FROZEN_PATH = ART / "FROZEN.json"
CONF_JSON = ART / "confirmatory.json"
INSTRUMENT_JSON = ART / "instrument.json"

# Declared before confirmatory execution (YYYYMMDD of this formulation).
CONFIRMATORY_SEED = 260826
INSTRUMENT_SEED = 260825
HORIZON = 60.0
N_SCENARIOS = 3
REPLICATES = 2
EPS_ZERO = 0.0
EPS_SENSITIVITY = 0.02
HYPOTHESES = (0.0, 0.25, 0.5, 1.0)
PRIMARY_ESTIMAND = "goal_utility_ratio"
INTERVENTION = "semantic_vs_throughput"
CLAIM_GRAMMAR_VERSION = "osahr05_claim_v0"
JUNCTION_GRAMMAR_VERSION = "osahr06_junction_v0"
JUNCTION_RULE_ID = "route-task"
ANLF_LOAD_VERSION = "anlf.load.ema_v1"
ANLF_OUTAGE_VERSION = "anlf.outage.threshold_cusum_v1"
BRAIN_VERSION = "osahr06_brain_v1_deterministic"
MCP_SCHEMA_VERSION = "osahr06_mcp_v0"
BRAIN_LOAD_WEIGHT = 2.0
RESIDUAL_LOAD_WEIGHT = 1.75
ORACLE_CHOICE_BETA = 6.0

ARMS = (
    "throughput",
    "scalar_semantic",
    "vault_gated",
    "brain_at_hold",
    "oracle_vault_greedy",
)

SCENARIOS = (
    {"scenario": 1, "regime": "id", "overrides": {}},
    {
        "scenario": 2,
        "regime": "high_stress",
        "overrides": {
            "critical_rate_per_ue": 0.45,
            "background_rate_per_ue": 0.72,
        },
    },
    {
        "scenario": 3,
        "regime": "long_outage",
        "overrides": {
            "fast_outage_start": 10.0,
            "fast_outage_end": 45.0,
        },
    },
)

GRAMMAR_FILES = (
    EXPERIMENT_ROOT / "osahr_cell" / "protocol.py",
    EXPERIMENT_ROOT / "osahr_cell" / "vault.py",
    EXPERIMENT_ROOT / "osahr_cell" / "junction.py",
    EXPERIMENT_ROOT / "osahr_cell" / "anlf.py",
    EXPERIMENT_ROOT / "osahr_cell" / "brain.py",
    EXPERIMENT_ROOT / "osahr_cell" / "mcp_tools.py",
    EXP05 / "liquid_osahr05" / "claims.py",
)
