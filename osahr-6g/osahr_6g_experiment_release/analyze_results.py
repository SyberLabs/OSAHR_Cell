from __future__ import annotations
import json, math
from pathlib import Path
import numpy as np
import pandas as pd
from scipy import stats

ROOT = Path(__file__).resolve().parent
RNG_SEED = 20260812
BOOTSTRAPS = 20000


def t_ci(x):
    x = np.asarray(x, dtype=float)
    n = len(x)
    mean = x.mean()
    sd = x.std(ddof=1)
    half = stats.t.ppf(0.975, n-1) * sd / math.sqrt(n)
    return {"n": n, "mean": float(mean), "sd": float(sd), "ci95_low": float(mean-half), "ci95_high": float(mean+half)}


def bootstrap_diff(a, b, seed):
    a = np.asarray(a, dtype=float)
    b = np.asarray(b, dtype=float)
    rng = np.random.default_rng(seed)
    ia = rng.integers(0, len(a), size=(BOOTSTRAPS, len(a)))
    ib = rng.integers(0, len(b), size=(BOOTSTRAPS, len(b)))
    vals = a[ia].mean(axis=1) - b[ib].mean(axis=1)
    lo, hi = np.quantile(vals, [0.025, 0.975])
    return {
        "mean_difference": float(a.mean()-b.mean()),
        "independent_bootstrap_ci95_low": float(lo),
        "independent_bootstrap_ci95_high": float(hi),
        "welch_p": float(stats.ttest_ind(a, b, equal_var=False).pvalue),
    }


def load_controls(patterns):
    frames=[]
    for p in patterns:
        frames.append(pd.read_csv(ROOT / "controls" / p))
    return pd.concat(frames, ignore_index=True)

main = pd.read_csv(ROOT / "main_replicates.csv")
no_thr = load_controls(["no_outage_throughput.csv", "no_outage_throughput_110.csv"])
no_sem = load_controls(["no_outage_semantic.csv", "no_outage_semantic_110.csv"])
sev_thr = load_controls(["severe_throughput.csv", "severe_throughput_210_5.csv", "severe_throughput_215_5.csv"])
sev_sem = load_controls(["severe_semantic.csv", "severe_semantic_210_5.csv", "severe_semantic_215_5.csv"])

conditions = {
    "no_outage": {"throughput": no_thr, "semantic": no_sem},
    "moderate_outage": {
        "throughput": main[main.policy == "throughput"].copy(),
        "qos": main[main.policy == "qos"].copy(),
        "semantic": main[main.policy == "semantic"].copy(),
    },
    "severe_outage": {"throughput": sev_thr, "semantic": sev_sem},
}
metrics = [
    "goal_utility_ratio", "critical_success_rate", "background_success_rate",
    "timely_task_rate", "semantic_efficiency", "mean_latency", "energy", "reroutes", "max_queued"
]
summary = {}
for cond, policies in conditions.items():
    summary[cond] = {}
    for policy, df in policies.items():
        summary[cond][policy] = {m: t_ci(df[m]) for m in metrics}

comparisons = {
    "moderate_semantic_minus_throughput": {},
    "moderate_semantic_minus_qos": {},
    "no_outage_semantic_minus_throughput": {},
    "severe_semantic_minus_throughput": {},
}
for j, m in enumerate(metrics):
    comparisons["moderate_semantic_minus_throughput"][m] = bootstrap_diff(
        conditions["moderate_outage"]["semantic"][m], conditions["moderate_outage"]["throughput"][m], RNG_SEED + 10*j)
    comparisons["moderate_semantic_minus_qos"][m] = bootstrap_diff(
        conditions["moderate_outage"]["semantic"][m], conditions["moderate_outage"]["qos"][m], RNG_SEED + 10*j + 1)
    comparisons["no_outage_semantic_minus_throughput"][m] = bootstrap_diff(
        no_sem[m], no_thr[m], RNG_SEED + 10*j + 2)
    comparisons["severe_semantic_minus_throughput"][m] = bootstrap_diff(
        sev_sem[m], sev_thr[m], RNG_SEED + 10*j + 3)

out = {"bootstrap_seed": RNG_SEED, "bootstrap_samples": BOOTSTRAPS, "summary": summary, "comparisons": comparisons}
(ROOT / "statistical_results.json").write_text(json.dumps(out, indent=2), encoding="utf-8")

rows=[]
for cond, policies in summary.items():
    for policy, md in policies.items():
        rows.append({
            "condition": cond,
            "policy": policy,
            "n": md["goal_utility_ratio"]["n"],
            "goal_utility_mean": md["goal_utility_ratio"]["mean"],
            "goal_utility_ci_low": md["goal_utility_ratio"]["ci95_low"],
            "goal_utility_ci_high": md["goal_utility_ratio"]["ci95_high"],
            "critical_success_mean": md["critical_success_rate"]["mean"],
            "critical_success_ci_low": md["critical_success_rate"]["ci95_low"],
            "critical_success_ci_high": md["critical_success_rate"]["ci95_high"],
            "mean_latency": md["mean_latency"]["mean"],
            "semantic_efficiency": md["semantic_efficiency"]["mean"],
            "energy": md["energy"]["mean"],
        })
pd.DataFrame(rows).to_csv(ROOT / "stress_summary.csv", index=False)
print("wrote statistical_results.json and stress_summary.csv")
