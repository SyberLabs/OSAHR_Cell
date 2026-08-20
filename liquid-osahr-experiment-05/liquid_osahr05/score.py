"""Score trajectory tables into claim-status records."""
from __future__ import annotations

import sys
from collections import Counter
from typing import Iterable

import numpy as np
import pandas as pd

from .claims import (
    ActivationCounts,
    InterventionClaim,
    illegal_promotion,
    point_direction,
    score_claim,
)
from .protocol import (
    ACTIVATION_COUNTS,
    ARM_BY_ALPHA,
    ESTIMANDS,
    EXP03,
    GRID,
    INTERVENTION,
    PRIMARY_ESTIMAND,
    T04_STRICT,
)

if str(EXP03) not in sys.path:
    sys.path.insert(0, str(EXP03))

from liquid_osahr03.statistics import bootstrap_mean, stratified_bootstrap_mean  # type: ignore

REQUIRED_COLUMNS = {
    "regime",
    "scenario",
    "replicate",
    "model",
    "policy",
    "trust",
    *ESTIMANDS,
    *ACTIVATION_COUNTS,
}

STATUS_SEED = {
    "admit": 0,
    "hold_unresolved": 1,
    "reject": 2,
    "outcome_unknown": 3,
}
FOIL_SEED = {"T04_strict": 0, "alpha1": 1}


def load_table(path) -> pd.DataFrame:
    df = pd.read_csv(path)
    missing = REQUIRED_COLUMNS - set(df.columns)
    if missing:
        raise ValueError(f"table missing columns: {sorted(missing)}")
    return df.sort_values(["regime", "scenario", "replicate", "model", "policy"]).reset_index(drop=True)


def _mean_by_policy(df: pd.DataFrame, columns: Iterable[str]) -> pd.DataFrame:
    cols = list(columns)
    sm = df.groupby(["regime", "scenario", "model", "policy"], as_index=False)[cols].mean()
    frames = []
    for col in cols:
        piv = sm.pivot_table(
            index=["regime", "scenario", "model"],
            columns="policy",
            values=col,
            aggfunc="mean",
        )
        if "semantic" not in piv.columns or "throughput" not in piv.columns:
            raise ValueError(f"missing policy columns for {col}")
        part = (piv["semantic"] - piv["throughput"]).rename(col)
        frames.append(part)
    return pd.concat(frames, axis=1).reset_index()


def score_table(
    df: pd.DataFrame,
    *,
    estimand: str,
    horizon: float,
    eps: float,
    hypotheses: tuple[float, ...] = GRID,
) -> list[InterventionClaim]:
    effects = _mean_by_policy(df, [estimand])
    counts = _mean_by_policy(df, ACTIVATION_COUNTS)
    oracle_e = effects[effects.model == "oracle"].set_index(["regime", "scenario"])
    oracle_c = counts[counts.model == "oracle"].set_index(["regime", "scenario"])
    by_alpha = {}
    for alpha, model in ARM_BY_ALPHA.items():
        arm = effects[effects.model == model].set_index(["regime", "scenario"])[estimand]
        missing = set(oracle_e.index) - set(arm.index)
        if missing:
            raise ValueError(f"arm {model} missing scenarios: {sorted(missing)[:8]}")
        by_alpha[alpha] = arm.reindex(oracle_e.index)

    claims: list[InterventionClaim] = []
    for key in oracle_e.index:
        regime, scenario = key
        activation_row = oracle_c.loc[key]
        activation = ActivationCounts(
            events=float(activation_row["events"]),
            outages=float(activation_row["outages"]),
            handovers=float(activation_row["handovers"]),
            reroutes=float(activation_row["reroutes"]),
        )
        ensemble = {alpha: float(by_alpha[alpha].loc[key]) for alpha in hypotheses}
        claims.append(
            score_claim(
                estimand=estimand,
                regime=str(regime),
                scenario=int(scenario),
                oracle_effect=float(oracle_e.loc[key, estimand]),
                effects_by_alpha=ensemble,
                activation=activation,
                horizon=horizon,
                eps=eps,
                intervention=INTERVENTION,
                hypotheses=hypotheses,
            )
        )
    return claims


def claims_frame(claims: list[InterventionClaim]) -> pd.DataFrame:
    return pd.DataFrame([c.to_json() for c in claims])


def foil_alpha(estimand: str, regime: str, foil: str) -> float:
    if foil == "alpha1":
        return 1.0
    if foil == "T04_strict":
        return float(T04_STRICT[(estimand, regime)])
    raise ValueError(f"unknown foil {foil}")


def annotate_foils(claims: list[InterventionClaim]) -> pd.DataFrame:
    rows = []
    for claim in claims:
        row = claim.to_json()
        for foil in ("T04_strict", "alpha1"):
            alpha = foil_alpha(claim.estimand, claim.regime, foil)
            point = claim.effects_by_alpha[f"{alpha:.2f}"]
            direction = point_direction(claim.oracle_effect, point, claim.eps)
            row[f"{foil}_alpha"] = alpha
            row[f"{foil}_direction"] = direction
            row[f"{foil}_illegal_promotion"] = illegal_promotion(claim.status, direction)
        rows.append(row)
    return pd.DataFrame(rows)


def _indicators(frame: pd.DataFrame, column: str, value) -> dict[str, list[int]]:
    by_regime: dict[str, list[int]] = {}
    for regime, sub in frame.groupby("regime"):
        by_regime[str(regime)] = [int(v == value) for v in sub[column].tolist()]
    return by_regime


def _boot_block(by_regime: dict[str, list[int]], *, seed: int) -> dict:
    arrays = {k: np.asarray(v, dtype=float) for k, v in by_regime.items()}
    return {
        "macro": stratified_bootstrap_mean(arrays, seed=seed),
        "regimes": {
            regime: bootstrap_mean(vals, seed=seed + 100 + i)
            for i, (regime, vals) in enumerate(sorted(by_regime.items()))
        },
    }


def summarize_claims(frame: pd.DataFrame, *, seed: int) -> dict:
    n = len(frame)
    counts = Counter(frame["status"].tolist())
    statuses = ("admit", "hold_unresolved", "reject", "outcome_unknown")
    rates = {}
    for status in statuses:
        by_regime = _indicators(frame, "status", status)
        block = _boot_block(by_regime, seed=seed + 1000 * STATUS_SEED[status])
        block["count"] = int(counts[status])
        rates[status] = block
    expressed = frame[frame.effect_expressed].copy()
    expressed_n = int(len(expressed))
    expressed_rates = {}
    if expressed_n:
        for status in ("admit", "hold_unresolved", "reject"):
            by_regime = _indicators(expressed, "status", status)
            block = _boot_block(by_regime, seed=seed + 4000 + 1000 * STATUS_SEED[status])
            block["count"] = int((expressed.status == status).sum())
            expressed_rates[status] = block
    foils = {}
    for foil in ("T04_strict", "alpha1"):
        col = f"{foil}_illegal_promotion"
        if col not in frame.columns:
            continue
        by_regime = {r: sub[col].astype(int).tolist() for r, sub in frame.groupby("regime")}
        block = _boot_block(by_regime, seed=seed + 8000 + 100 * FOIL_SEED[foil])
        expressed_illegal = expressed[col].astype(int).tolist() if expressed_n else []
        foils[foil] = {
            "illegal_count": int(frame[col].sum()),
            "all": block,
            "among_expressed": bootstrap_mean(expressed_illegal, seed=seed + 8100 + FOIL_SEED[foil])
            if expressed_illegal
            else {"mean": 0.0, "lo": 0.0, "hi": 0.0, "n": 0},
        }
    activation_wo = frame["activation_without_effect"].astype(int).tolist()
    return {
        "n": n,
        "expressed_n": expressed_n,
        "status_counts": {s: int(counts[s]) for s in statuses},
        "rates": rates,
        "expressed_rates": expressed_rates,
        "foils": foils,
        "activation_without_effect": bootstrap_mean(activation_wo, seed=seed + 9000),
        "mean_spread": bootstrap_mean(frame["spread"].tolist(), seed=seed + 9100)
        if n
        else {"mean": 0.0, "lo": 0.0, "hi": 0.0, "n": 0},
        "primary_estimand": PRIMARY_ESTIMAND,
    }
