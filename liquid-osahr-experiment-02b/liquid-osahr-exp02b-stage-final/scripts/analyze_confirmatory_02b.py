#!/usr/bin/env python3
"""Rebuild and analyze the frozen Experiment 02B confirmatory holdout.

The independent unit is a physical scenario. Two stochastic replicates per arm
are averaged before inference. All pairwise model comparisons use the same
scenario-level oracle policy effect.
"""
from __future__ import annotations

from pathlib import Path
import json
import math
import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
ART = ROOT / "artifacts"
REGIMES = ("id", "high_mobility", "high_stress", "weak_channel")
MODELS = ("oracle", "mechanistic_calibrated", "residual_quarter", "residual_idcal", "residual_predictive")
POLICIES = ("throughput", "semantic")
METRICS = ("goal_utility_ratio", "critical_success_rate", "mean_latency")


def bootstrap_mean(values, *, seed: int, n: int = 50_000):
    v = np.asarray(values, dtype=float)
    rng = np.random.default_rng(seed)
    draws = v[rng.integers(0, len(v), size=(n, len(v)))].mean(axis=1)
    return {"mean": float(v.mean()), "lo": float(np.quantile(draws, 0.025)), "hi": float(np.quantile(draws, 0.975))}


def stratified_bootstrap_mean(by_regime: dict[str, np.ndarray], *, seed: int, n: int = 50_000):
    rng = np.random.default_rng(seed)
    pieces = []
    obs = []
    for reg in REGIMES:
        v = np.asarray(by_regime[reg], dtype=float)
        obs.extend(v.tolist())
        pieces.append(v[rng.integers(0, len(v), size=(n, len(v)))])
    draws = np.concatenate(pieces, axis=1).mean(axis=1)
    return {"mean": float(np.mean(obs)), "lo": float(np.quantile(draws, 0.025)), "hi": float(np.quantile(draws, 0.975))}


def load_release():
    files = sorted(ART.glob("confirm_*.csv"))
    df = pd.concat([pd.read_csv(f) for f in files], ignore_index=True)
    df = df.sort_values(["regime", "scenario", "replicate", "model", "policy"]).reset_index(drop=True)
    expected = len(REGIMES) * 5 * 2 * len(MODELS) * len(POLICIES)
    assert len(df) == expected, (len(df), expected)
    assert set(df.regime) == set(REGIMES)
    assert set(df.model) == set(MODELS)
    assert set(df.policy) == set(POLICIES)
    assert df.duplicated(["regime", "scenario", "replicate", "model", "policy"]).sum() == 0
    assert all(df[df.regime == r].scenario.nunique() == 5 for r in REGIMES)
    assert all(df.groupby(["regime", "scenario", "model", "policy"]).size() == 2)
    assert df.final_hash.nunique() == len(df)
    df.to_csv(ART / "confirmatory_release.csv", index=False)
    return df


def analyze_metric(df: pd.DataFrame, metric: str):
    sm = df.groupby(["regime", "scenario", "model", "policy"], as_index=False)[metric].mean()
    piv = sm.pivot(index=["regime", "scenario", "model"], columns="policy", values=metric).reset_index()
    piv["effect"] = piv["semantic"] - piv["throughput"]
    out = {"metric": metric, "regimes": {}, "macro": {}}
    error_vectors: dict[str, dict[str, np.ndarray]] = {m: {} for m in MODELS if m != "oracle"}
    level_vectors: dict[str, dict[str, np.ndarray]] = {m: {} for m in MODELS if m != "oracle"}
    for ri, reg in enumerate(REGIMES):
        pr = piv[piv.regime == reg]
        oracle = pr[pr.model == "oracle"].set_index("scenario")["effect"].sort_index()
        levels_oracle = sm[(sm.regime == reg) & (sm.model == "oracle")].set_index(["scenario", "policy"])[metric].sort_index()
        block = {
            "oracle_effect": bootstrap_mean(oracle.values, seed=10_000 + ri + sum(map(ord, metric))),
            "models": {},
        }
        for mi, model in enumerate(MODELS[1:]):
            eff = pr[pr.model == model].set_index("scenario")["effect"].reindex(oracle.index)
            err = (eff - oracle).to_numpy(dtype=float)
            lev = sm[(sm.regime == reg) & (sm.model == model)].set_index(["scenario", "policy"])[metric].reindex(levels_oracle.index)
            lerr = (lev - levels_oracle).to_numpy(dtype=float)
            error_vectors[model][reg] = err
            level_vectors[model][reg] = lerr
            block["models"][model] = {
                "effect": bootstrap_mean(eff.values, seed=20_000 + 101*ri + mi),
                "effect_bias": bootstrap_mean(err, seed=30_000 + 101*ri + mi),
                "effect_mae": float(np.mean(np.abs(err))),
                "effect_rmse": float(np.sqrt(np.mean(err**2))),
                "sign_agreement": float(np.mean(np.sign(eff.values) == np.sign(oracle.values))),
                "level_mae": float(np.mean(np.abs(lerr))),
                "level_rmse": float(np.sqrt(np.mean(lerr**2))),
            }
        out["regimes"][reg] = block
    for mi, model in enumerate(MODELS[1:]):
        abs_by_reg = {r: np.abs(error_vectors[model][r]) for r in REGIMES}
        signed_by_reg = {r: error_vectors[model][r] for r in REGIMES}
        abs_level = {r: np.abs(level_vectors[model][r]) for r in REGIMES}
        out["macro"][model] = {
            "effect_mae": stratified_bootstrap_mean(abs_by_reg, seed=40_000 + mi),
            "effect_bias": stratified_bootstrap_mean(signed_by_reg, seed=41_000 + mi),
            "level_mae": stratified_bootstrap_mean(abs_level, seed=42_000 + mi),
        }
    return out, error_vectors


def paired_against_mechanistic(analyses, errors_by_metric):
    rows = []
    for metric in METRICS:
        errv = errors_by_metric[metric]
        base = errv["mechanistic_calibrated"]
        for model in ("residual_quarter", "residual_idcal", "residual_predictive"):
            by_reg = {}
            for reg in REGIMES:
                diff = np.abs(errv[model][reg]) - np.abs(base[reg])
                by_reg[reg] = diff
                ci = bootstrap_mean(diff, seed=50_000 + sum(map(ord, metric+reg+model)))
                rows.append({"metric": metric, "scope": reg, "model": model, "delta_abs_effect_error_vs_mechanistic": ci["mean"], "ci_lo": ci["lo"], "ci_hi": ci["hi"]})
            ci = stratified_bootstrap_mean(by_reg, seed=60_000 + sum(map(ord, metric+model)))
            rows.append({"metric": metric, "scope": "macro", "model": model, "delta_abs_effect_error_vs_mechanistic": ci["mean"], "ci_lo": ci["lo"], "ci_hi": ci["hi"]})
    return pd.DataFrame(rows)


def main():
    df = load_release()
    analyses = {}
    error_vectors = {}
    for metric in METRICS:
        analyses[metric], error_vectors[metric] = analyze_metric(df, metric)
        (ART / f"confirmatory_analysis_{metric}.json").write_text(json.dumps(analyses[metric], indent=2))
    paired = paired_against_mechanistic(analyses, error_vectors)
    paired.to_csv(ART / "confirmatory_paired_comparisons.csv", index=False)

    macro_rows = []
    for metric, result in analyses.items():
        for model, vals in result["macro"].items():
            macro_rows.append({
                "metric": metric,
                "model": model,
                "effect_mae": vals["effect_mae"]["mean"],
                "effect_mae_lo": vals["effect_mae"]["lo"],
                "effect_mae_hi": vals["effect_mae"]["hi"],
                "effect_bias": vals["effect_bias"]["mean"],
                "level_mae": vals["level_mae"]["mean"],
            })
    macro = pd.DataFrame(macro_rows)
    macro.to_csv(ART / "confirmatory_macro_summary.csv", index=False)

    audit = {
        "rows": int(len(df)),
        "regimes": list(REGIMES),
        "scenarios_per_regime": 5,
        "replicates_per_arm": 2,
        "models": list(MODELS),
        "policies": list(POLICIES),
        "duplicate_arm_keys": int(df.duplicated(["regime", "scenario", "replicate", "model", "policy"]).sum()),
        "unique_state_hashes": int(df.final_hash.nunique()),
        "accepted_events": int(df.events.sum()),
        "thinning_rejections": int(df.thinning_rejections.sum()),
        "bootstrap_resamples": 50_000,
    }
    (ART / "confirmatory_audit.json").write_text(json.dumps(audit, indent=2))

    # Ex-post ranking is deliberately labeled as such: it is descriptive and
    # must not be confused with the preselected robust trust alpha=0.
    goal = macro[macro.metric == "goal_utility_ratio"].sort_values("effect_mae")
    print("CONFIRMATORY AUDIT", json.dumps(audit, indent=2))
    print("\nEX-POST MACRO GOAL-UTILITY RANKING")
    print(goal[["model", "effect_mae", "effect_mae_lo", "effect_mae_hi", "level_mae"]].to_string(index=False))
    print("\nPAIRED VS PRESELECTED MECHANISTIC")
    print(paired[(paired.metric == "goal_utility_ratio") & (paired.scope == "macro")].to_string(index=False))


if __name__ == "__main__":
    main()
