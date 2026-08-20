"""Evaluate frozen T on 02B confirmatory trajectories by arm selection."""
from __future__ import annotations

from typing import Iterable

import pandas as pd

from .statistics import bootstrap_mean, paired_delta, stratified_bootstrap_mean
from .trust import DEFAULT_INTERVENTION, QueryContext, TrustField

ESTIMANDS = ("goal_utility_ratio", "critical_success_rate", "mean_latency")
REGIMES = ("id", "high_mobility", "high_stress", "weak_channel")
ARM_BY_ALPHA = {
    0.0: "mechanistic_calibrated",
    0.25: "residual_quarter",
    0.5: "residual_idcal",
    1.0: "residual_predictive",
}


def load_confirmatory(path) -> pd.DataFrame:
    df = pd.read_csv(path)
    required = {
        "regime", "scenario", "replicate", "model", "policy", "trust",
        *ESTIMANDS,
    }
    missing = required - set(df.columns)
    if missing:
        raise ValueError(f"confirmatory table missing columns: {sorted(missing)}")
    return df.sort_values(["regime", "scenario", "replicate", "model", "policy"]).reset_index(drop=True)


def scenario_effects(df: pd.DataFrame, estimand: str) -> pd.DataFrame:
    sm = df.groupby(["regime", "scenario", "model", "trust", "policy"], as_index=False)[estimand].mean()
    piv = sm.pivot_table(
        index=["regime", "scenario", "model", "trust"],
        columns="policy",
        values=estimand,
        aggfunc="mean",
    ).reset_index()
    piv["effect"] = piv["semantic"] - piv["throughput"]
    return piv


def oracle_effects(effects: pd.DataFrame) -> pd.DataFrame:
    return effects[effects.model == "oracle"][["regime", "scenario", "effect"]].rename(columns={"effect": "oracle_effect"})


def arm_abs_error(effects: pd.DataFrame, alpha: float) -> pd.DataFrame:
    model = ARM_BY_ALPHA[alpha]
    hat = effects[effects.model == model][["regime", "scenario", "effect"]]
    merged = hat.merge(oracle_effects(effects), on=["regime", "scenario"], how="inner")
    merged["abs_error"] = (merged["effect"] - merged["oracle_effect"]).abs()
    merged["alpha"] = alpha
    return merged.sort_values(["regime", "scenario"]).reset_index(drop=True)


def field_abs_error(effects: pd.DataFrame, field: TrustField, estimand: str) -> pd.DataFrame:
    rows = []
    oracle = oracle_effects(effects).set_index(["regime", "scenario"])["oracle_effect"]
    for (regime, scenario), grp in effects.groupby(["regime", "scenario"]):
        decision = field.select(QueryContext(estimand, DEFAULT_INTERVENTION, str(regime), field.calibration_horizon))
        if decision.alpha not in ARM_BY_ALPHA:
            raise ValueError(f"selected alpha {decision.alpha} has no confirmatory arm")
        model = ARM_BY_ALPHA[decision.alpha]
        hit = grp[grp.model == model]
        if len(hit) != 1:
            raise ValueError(f"expected one arm row for {model} at {(regime, scenario)}; got {len(hit)}")
        hat = float(hit["effect"].iloc[0])
        err = abs(hat - float(oracle.loc[(regime, scenario)]))
        rows.append({
            "regime": regime,
            "scenario": int(scenario),
            "alpha": decision.alpha,
            "source": decision.source,
            "model": model,
            "effect": hat,
            "oracle_effect": float(oracle.loc[(regime, scenario)]),
            "abs_error": err,
        })
    return pd.DataFrame(rows).sort_values(["regime", "scenario"]).reset_index(drop=True)


def summarize_errors(err: pd.DataFrame, *, seed: int) -> dict:
    by_regime = {}
    for i, regime in enumerate(REGIMES):
        part = err[err.regime == regime]
        if part.empty:
            continue
        sources = part.source.value_counts().to_dict() if "source" in part.columns else {}
        by_regime[regime] = {
            "mae": bootstrap_mean(part.abs_error.to_numpy(), seed=seed + i),
            "mean_selected_alpha": float(part.alpha.mean()),
            "sources": sources,
        }
    grouped = {r: err[err.regime == r].abs_error.to_numpy() for r in REGIMES if (err.regime == r).any()}
    return {
        "regimes": by_regime,
        "macro": stratified_bootstrap_mean(grouped, seed=seed + 99),
    }


def compare_fields(a: pd.DataFrame, b: pd.DataFrame, *, seed: int) -> dict:
    merged = a.merge(b, on=["regime", "scenario"], suffixes=("_a", "_b"))
    out = {"regimes": {}, "macro": paired_delta(merged.abs_error_a, merged.abs_error_b, seed=seed)}
    for i, regime in enumerate(REGIMES):
        part = merged[merged.regime == regime]
        if part.empty:
            continue
        out["regimes"][regime] = paired_delta(part.abs_error_a, part.abs_error_b, seed=seed + 17 * (i + 1))
    return out


def loso_selector_errors(effects: pd.DataFrame, *, lam: float, grid: tuple[float, ...]) -> pd.DataFrame:
    """Exploratory: fit T(q, r) by LOSO inside each confirmatory regime.

    This uses confirmatory scenarios and is not a frozen-protocol result.
    """
    from .trust import cell_objective, select_alpha

    oracle = oracle_effects(effects).set_index(["regime", "scenario"])["oracle_effect"]
    rows = []
    for regime, g in effects.groupby("regime"):
        scenarios = sorted(g.scenario.unique())
        err_by_alpha = {}
        for alpha in grid:
            arm = arm_abs_error(g, alpha).set_index("scenario")["abs_error"]
            err_by_alpha[alpha] = [float(arm.loc[s]) for s in scenarios]
        n = len(scenarios)
        for i, scenario in enumerate(scenarios):
            mae = {a: (sum(v) - v[i]) / (n - 1) for a, v in err_by_alpha.items()}
            alpha = select_alpha(cell_objective(mae, predictive_nmae=None, lam=0.0, grid=grid))
            rows.append({
                "regime": regime,
                "scenario": int(scenario),
                "alpha": alpha,
                "abs_error": err_by_alpha[alpha][i],
                "oracle_effect": float(oracle.loc[(regime, scenario)]),
            })
    return pd.DataFrame(rows)


def oracle_cell_errors(effects: pd.DataFrame, *, grid: tuple[float, ...]) -> pd.DataFrame:
    """Infeasible ceiling: choose the best executed alpha per scenario."""
    rows = []
    for (regime, scenario), g in effects.groupby(["regime", "scenario"]):
        best = None
        for alpha in grid:
            arm = g[g.model == ARM_BY_ALPHA[alpha]]
            oracle = float(g[g.model == "oracle"]["effect"].iloc[0])
            err = abs(float(arm["effect"].iloc[0]) - oracle)
            if best is None or err < best["abs_error"] - 1e-15 or (
                abs(err - best["abs_error"]) <= 1e-15 and alpha < best["alpha"]
            ):
                best = {
                    "regime": regime,
                    "scenario": int(scenario),
                    "alpha": alpha,
                    "abs_error": err,
                    "oracle_effect": oracle,
                }
        rows.append(best)
    return pd.DataFrame(rows)


def global_alpha_table(effects: pd.DataFrame, alphas: Iterable[float], *, seed: int) -> dict[str, dict]:
    return {f"{a:.2f}": summarize_errors(arm_abs_error(effects, a), seed=seed + int(1000 * a)) for a in alphas}
