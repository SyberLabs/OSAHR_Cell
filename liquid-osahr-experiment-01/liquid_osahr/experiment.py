"""End-to-end orchestration for Liquid-OSAHR Experiment 01."""
from __future__ import annotations

from dataclasses import asdict
from pathlib import Path
import csv
import hashlib
import json
import random
import numpy as np
import torch

from .teacher import LinkTeacher, TeacherConfig, FEATURE_NAMES, MARKS
from .data import DatasetSpec, DatasetBundle, generate_bundle, save_bundle
from .models import ModelConfig, ConstantHazardModel
from .training import TrainConfig, train_model
from .metrics import evaluate_model, predict_trace
from .osahr_bridge import TwinConfig, TwinMetrics, run_twin


DEFAULT_MODELS = ("cfc", "gru_dt", "lstm_dt", "mlp_dt")
# Dense solver-based LTC is deliberately resource-capped in the release study.
# Use scripts/run_identification_release.py to reproduce that secondary baseline.


def seed_everything(seed: int) -> None:
    random.seed(seed)
    np.random.seed(seed)
    torch.manual_seed(seed)
    torch.set_num_threads(max(1, min(4, torch.get_num_threads())))


def write_csv(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not rows:
        return
    keys = []
    seen = set()
    for row in rows:
        for k in row:
            if k not in seen:
                keys.append(k); seen.add(k)
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=keys)
        w.writeheader(); w.writerows(rows)


def train_and_evaluate(
    out: Path,
    *,
    dataset_spec: DatasetSpec,
    teacher_cfg: TeacherConfig,
    train_cfg: TrainConfig,
    hidden_size: int = 32,
    models: tuple[str, ...] = DEFAULT_MODELS,
) -> tuple[DatasetBundle, dict[str, object], list[dict]]:
    seed_everything(dataset_spec.seed)
    teacher = LinkTeacher(teacher_cfg)
    bundle = generate_bundle(teacher, dataset_spec)
    save_bundle(bundle, out / "data" / "traces.npz")
    (out / "data" / "normalizer.json").write_text(json.dumps(bundle.normalizer.to_json(), indent=2))

    cfg = ModelConfig(input_size=len(FEATURE_NAMES), marks=len(MARKS), hidden_size=hidden_size)
    fitted: dict[str, object] = {}
    train_rows: list[dict] = []
    for i, name in enumerate(models):
        local_cfg = TrainConfig(**{**asdict(train_cfg), "seed": train_cfg.seed + 97*i})
        model, result = train_model(
            name, cfg, bundle.train, bundle.val, bundle.normalizer, local_cfg,
            checkpoint_path=out / "checkpoints" / f"{name}.pt",
        )
        fitted[name] = model
        row = asdict(result)
        row.pop("history", None)
        train_rows.append(row)
        (out / "training_history").mkdir(parents=True, exist_ok=True)
        (out / "training_history" / f"{name}.json").write_text(json.dumps(result.history, indent=2))
    constant = ConstantHazardModel.fit(bundle.train)
    fitted["constant"] = constant
    train_rows.append({"model_name":"constant","best_epoch":0,"best_val_nll_interval":None,"train_seconds":0.0,"parameter_count":constant.parameter_count(),"checkpoint":None})
    write_csv(out / "results" / "training_summary.csv", train_rows)

    metric_rows = []
    for regime, traces in bundle.tests.items():
        for name, model in fitted.items():
            m = evaluate_model(name, model, traces, bundle.normalizer, regime=regime, device=train_cfg.device)
            d = asdict(m)
            # JSON-encode nested dicts for flat CSV while retaining full JSON separately.
            d["mark_count_ratios"] = json.dumps(d["mark_count_ratios"], sort_keys=True)
            d["time_rescaling_ks"] = json.dumps(d["time_rescaling_ks"], sort_keys=True)
            d["time_rescaling_p"] = json.dumps(d["time_rescaling_p"], sort_keys=True)
            metric_rows.append(d)
    write_csv(out / "results" / "identification_metrics.csv", metric_rows)
    return bundle, fitted, metric_rows


def _pairs(traces, n_pairs: int):
    fast = [t for t in traces if t.profile == "fast"]
    robust = [t for t in traces if t.profile == "robust"]
    n = min(n_pairs, len(fast), len(robust))
    return list(zip(fast[:n], robust[:n]))


def run_osahr_study(
    out: Path,
    bundle: DatasetBundle,
    fitted: dict[str, object],
    *,
    regimes=("id", "sparse"),
    n_pairs: int = 6,
    stochastic_replicates: int = 2,
    root_seed: int = 80219,
    twin_cfg: TwinConfig | None = None,
) -> list[dict]:
    twin_cfg = twin_cfg or TwinConfig()
    rows: list[dict] = []
    for regime in regimes:
        for scenario, (fast_trace, robust_trace) in enumerate(_pairs(bundle.tests[regime], n_pairs)):
            schedule_models = {"oracle": None, **fitted}
            for model_name, model in schedule_models.items():
                if model_name == "oracle":
                    fast_rates = fast_trace.true_avg_rates
                    robust_rates = robust_trace.true_avg_rates
                else:
                    fast_rates = predict_trace(model_name, model, fast_trace, bundle.normalizer)
                    robust_rates = predict_trace(model_name, model, robust_trace, bundle.normalizer)
                # Guard the downstream simulator from pathological neural rate
                # explosions while recording that the model is evaluated before
                # clipping in identification metrics.
                fast_rates = np.clip(fast_rates, 1e-6, 30.0)
                robust_rates = np.clip(robust_rates, 1e-6, 30.0)
                for policy in ("throughput", "semantic"):
                    for rep in range(stochastic_replicates):
                        m = run_twin(
                            hazard_model=model_name, regime=regime, policy=policy,
                            scenario=scenario, replicate=rep,
                            fast_times=fast_trace.times, fast_rates=fast_rates,
                            robust_times=robust_trace.times, robust_rates=robust_rates,
                            root_seed=root_seed, cfg=twin_cfg,
                            verify_incremental=(regime == regimes[0] and scenario == 0 and rep == 0 and model_name == "cfc" and policy == "semantic"),
                        )
                        rows.append(asdict(m))
    write_csv(out / "results" / "osahr_twin_runs.csv", rows)
    return rows


def summarize_osahr(rows: list[dict]) -> dict:
    # Aggregate by regime/model/policy.
    agg: dict[tuple[str,str,str], list[dict]] = {}
    for r in rows:
        agg.setdefault((r["regime"], r["hazard_model"], r["policy"]), []).append(r)
    summaries = []
    for key, rs in sorted(agg.items()):
        regime, model, policy = key
        summaries.append({
            "regime": regime, "hazard_model": model, "policy": policy, "n": len(rs),
            "goal_utility_mean": float(np.mean([r["goal_utility_ratio"] for r in rs])),
            "goal_utility_sd": float(np.std([r["goal_utility_ratio"] for r in rs], ddof=1)) if len(rs)>1 else 0.0,
            "critical_success_mean": float(np.mean([r["critical_success_rate"] for r in rs])),
            "latency_mean": float(np.mean([r["mean_latency"] for r in rs])),
            "outages_mean": float(np.mean([r["outages"] for r in rs])),
            "reroutes_mean": float(np.mean([r["reroutes"] for r in rs])),
        })

    # Policy advantage and twin fidelity against oracle.
    advantages = []
    fidelity = []
    regimes = sorted(set(r["regime"] for r in rows))
    models = sorted(set(r["hazard_model"] for r in rows))
    for regime in regimes:
        oracle = {(r["scenario"],r["replicate"],r["policy"]):r for r in rows if r["regime"]==regime and r["hazard_model"]=="oracle"}
        for model in models:
            subset = [r for r in rows if r["regime"]==regime and r["hazard_model"]==model]
            sem = {(r["scenario"],r["replicate"]):r for r in subset if r["policy"]=="semantic"}
            thr = {(r["scenario"],r["replicate"]):r for r in subset if r["policy"]=="throughput"}
            common = sorted(set(sem)&set(thr))
            adv = [sem[k]["goal_utility_ratio"] - thr[k]["goal_utility_ratio"] for k in common]
            advantages.append({"regime":regime,"hazard_model":model,"n":len(adv),"semantic_advantage_mean":float(np.mean(adv)) if adv else float("nan"),"semantic_advantage_sd":float(np.std(adv,ddof=1)) if len(adv)>1 else 0.0})
            if model != "oracle":
                diffs=[]; crit=[]; out=[]
                for r in subset:
                    o=oracle.get((r["scenario"],r["replicate"],r["policy"]))
                    if o:
                        diffs.append(r["goal_utility_ratio"]-o["goal_utility_ratio"])
                        crit.append(r["critical_success_rate"]-o["critical_success_rate"])
                        out.append(r["outages"]-o["outages"])
                fidelity.append({
                    "regime":regime,"hazard_model":model,"n":len(diffs),
                    "goal_utility_bias":float(np.mean(diffs)),
                    "goal_utility_mae":float(np.mean(np.abs(diffs))),
                    "critical_success_mae":float(np.mean(np.abs(crit))),
                    "outage_count_mae":float(np.mean(np.abs(out))),
                })
    return {"aggregate":summaries,"policy_advantage":advantages,"oracle_fidelity":fidelity}


def sha256_manifest(root: Path, files: list[Path]) -> str:
    lines=[]
    for p in files:
        h=hashlib.sha256(p.read_bytes()).hexdigest()
        lines.append(f"{h}  {p.relative_to(root)}")
    return "\n".join(lines)+"\n"


def run_full(
    out: Path,
    *,
    dataset_spec: DatasetSpec | None = None,
    teacher_cfg: TeacherConfig | None = None,
    train_cfg: TrainConfig | None = None,
    hidden_size: int = 32,
    bridge_pairs: int = 6,
    bridge_replicates: int = 2,
) -> dict:
    out.mkdir(parents=True, exist_ok=True)
    dataset_spec = dataset_spec or DatasetSpec()
    teacher_cfg = teacher_cfg or TeacherConfig()
    train_cfg = train_cfg or TrainConfig()
    bundle, fitted, id_rows = train_and_evaluate(out, dataset_spec=dataset_spec, teacher_cfg=teacher_cfg, train_cfg=train_cfg, hidden_size=hidden_size)
    twin_rows = run_osahr_study(out, bundle, fitted, n_pairs=bridge_pairs, stochastic_replicates=bridge_replicates)
    summary = summarize_osahr(twin_rows)
    result = {
        "experiment":"Liquid-OSAHR Experiment 01",
        "dataset_spec":asdict(dataset_spec), "teacher_config":asdict(teacher_cfg), "train_config":asdict(train_cfg),
        "hidden_size":hidden_size,
        "identification_metrics":id_rows,
        "osahr_summary":summary,
    }
    (out/"results"/"summary.json").write_text(json.dumps(result, indent=2, allow_nan=True))
    write_csv(out/"results"/"osahr_aggregate.csv", summary["aggregate"])
    write_csv(out/"results"/"policy_advantage.csv", summary["policy_advantage"])
    write_csv(out/"results"/"oracle_fidelity.csv", summary["oracle_fidelity"])
    return result
