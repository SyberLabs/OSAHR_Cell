"""Paired trace-level identification inference and bridge clipping audit.

The trace is the independent unit for identification metrics. Comparisons pair
models on the exact same trace. The paired-sparse regime reuses the ID physical
event histories under a deterministically thinned observation grid, isolating
irregular-sampling sensitivity from a changed physical realization.
"""
from __future__ import annotations
from pathlib import Path
import hashlib, json, sys
import numpy as np
import pandas as pd
import torch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from liquid_osahr.teacher import LinkTeacher, TeacherConfig, FEATURE_NAMES, MARKS
from liquid_osahr.data import DatasetSpec, generate_bundle, sparsify_trace
from liquid_osahr.models import ModelConfig, build_model, ConstantHazardModel
from liquid_osahr.metrics import predict_trace

OUT = ROOT / "artifacts/results"
B = 30000
MASTER = 20260817


def stable_seed(*parts: object) -> int:
    h = hashlib.sha256("|".join(map(str, parts)).encode()).digest()
    return MASTER + int.from_bytes(h[:4], "big")


def load_checkpoint(name: str):
    ck = torch.load(ROOT / "artifacts/checkpoints" / f"{name}.pt", weights_only=False)
    model = build_model(ck["model_name"], ModelConfig(**ck["model_config"]), seed=ck["train_config"]["seed"])
    model.load_state_dict(ck["state_dict"]); model.eval()
    return ck["model_name"], model


def trace_nll(trace, rates: np.ndarray) -> float:
    exposure = trace.interval_dt[:, None].astype(np.float64)
    counts = trace.event_counts.astype(np.float64)
    return float((rates * exposure - counts * np.log(np.clip(rates, 1e-8, None))).sum())


def paired_bootstrap(diff: np.ndarray, *, seed: int):
    diff = np.asarray(diff, float); n = len(diff); rng = np.random.default_rng(seed)
    vals = diff[rng.integers(0, n, size=(B, n))].mean(axis=1)
    return float(diff.mean()), float(np.quantile(vals, .025)), float(np.quantile(vals, .975))


def main():
    torch.set_num_threads(2)
    bundle = generate_bundle(LinkTeacher(TeacherConfig(horizon=36)), DatasetSpec(72,16,20,20260817))
    regimes = {
        "id": bundle.tests["id"],
        "paired_sparse": [sparsify_trace(t, keep_probability=.45, seed=99173+i) for i,t in enumerate(bundle.tests["id"])],
        "high_mobility": bundle.tests["high_mobility"],
        "high_congestion": bundle.tests["high_congestion"],
    }
    models = {}
    for label in ["cfc","gru_dt","lstm_dt","mlp_dt","gru_param_matched"]:
        kind, model = load_checkpoint(label)
        models[label] = (kind, model)
    models["constant"] = ("constant", ConstantHazardModel.fit(bundle.train))

    per_trace=[]; clip=[]
    for regime,traces in regimes.items():
        for ti,trace in enumerate(traces):
            for label,(kind,model) in models.items():
                rates = predict_trace(kind, model, trace, bundle.normalizer)
                per_trace.append({
                    "regime":regime,"trace_index":ti,"trace_id":trace.trace_id,"profile":trace.profile,
                    "model":label,"intervals":len(trace.times),"events":int(trace.event_counts.sum()),
                    "nll_total":trace_nll(trace,rates),"nll_per_interval":trace_nll(trace,rates)/len(trace.times),
                })
                clip.append({
                    "regime":regime,"trace_index":ti,"model":label,"values":int(rates.size),
                    "above_30":int((rates>30).sum()),"above_20":int((rates>20).sum()),
                    "max_rate":float(rates.max()),"p999_rate":float(np.quantile(rates,.999)),
                })
    pt=pd.DataFrame(per_trace); pt.to_csv(OUT/'identification_per_trace.csv',index=False)
    cd=pd.DataFrame(clip); cd.to_csv(OUT/'hazard_clipping_audit_per_trace.csv',index=False)

    comps=[]
    for regime in regimes:
        p=pt[pt.regime==regime].pivot(index='trace_index',columns='model',values='nll_per_interval')
        for other in ["gru_dt","lstm_dt","mlp_dt","gru_param_matched","constant"]:
            diff=(p["cfc"]-p[other]).dropna().to_numpy(float)  # negative favors CfC
            m,lo,hi=paired_bootstrap(diff,seed=stable_seed(regime,other))
            comps.append({"regime":regime,"comparison":f"cfc-minus-{other}","n_traces":len(diff),
                          "mean_nll_difference":m,"ci_lo":lo,"ci_hi":hi,"cfc_better_fraction":float(np.mean(diff<0))})
    comp=pd.DataFrame(comps); comp.to_csv(OUT/'identification_paired_comparisons.csv',index=False)

    ca=(cd.groupby(['regime','model'],as_index=False)
          .agg(values=('values','sum'),above_30=('above_30','sum'),above_20=('above_20','sum'),max_rate=('max_rate','max'),p999_rate=('p999_rate','max')))
    ca['fraction_above_30']=ca.above_30/ca['values']; ca['fraction_above_20']=ca.above_20/ca['values']
    ca.to_csv(OUT/'hazard_clipping_audit.csv',index=False)

    sens=pd.read_csv(OUT/'training_seed_sensitivity.csv')
    ss=(sens.groupby(['model','regime'],as_index=False).agg(
        seeds=('train_seed','nunique'),mean_nll=('nll_per_interval','mean'),std_nll=('nll_per_interval','std'),
        min_nll=('nll_per_interval','min'),max_nll=('nll_per_interval','max')))
    ss.to_csv(OUT/'training_seed_sensitivity_summary.csv',index=False)
    audit={
        'bootstrap_replicates':B,'identification_independent_unit':'trace',
        'paired_sparse_reuses_id_physical_event_histories':True,
        'bridge_safety_cap':30.0,
        'clipping_total_above_30':int(ca.above_30.sum()),
        'clipping_total_values':int(ca['values'].sum()),
    }
    (OUT/'identification_analysis_audit.json').write_text(json.dumps(audit,indent=2))
    print(comp.to_string(index=False)); print('\nClipping\n',ca.to_string(index=False)); print('\nSeed sensitivity\n',ss.to_string(index=False)); print('\n',json.dumps(audit,indent=2))

if __name__=='__main__': main()
