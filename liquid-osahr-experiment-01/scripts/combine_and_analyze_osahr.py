"""Combine release bridge shards and perform scenario-clustered analysis.

A scenario (paired fast/robust telemetry traces) is the independent unit. Two
OSAHR stochastic replicates within a scenario are averaged before bootstrap or
paired error computation, avoiding pseudoreplication.
"""
from __future__ import annotations
from pathlib import Path
import hashlib,json
import numpy as np
import pandas as pd
ROOT=Path(__file__).resolve().parents[1]; OUT=ROOT/'artifacts/results'
B=20000; MASTER=20260817
METRICS=['goal_utility_ratio','critical_success_rate','mean_latency','energy','outages','recoveries','reroutes','handovers','final_queued','final_inflight']

def stable_seed(*parts):
    b='|'.join(map(str,parts)).encode(); return MASTER + int.from_bytes(hashlib.sha256(b).digest()[:4],'big')

def boot_stat(x, fn=np.mean, seed=MASTER):
    x=np.asarray(x,float); n=len(x)
    if n==0:return (np.nan,np.nan,np.nan)
    rng=np.random.default_rng(seed)
    samples=x[rng.integers(0,n,size=(B,n))]
    # All release statistics are either a mean or a mean absolute error.
    if fn is np.mean:
        vals=samples.mean(axis=1); point=float(x.mean())
    else:
        vals=np.mean(np.abs(samples),axis=1); point=float(np.mean(np.abs(x)))
    return point,float(np.quantile(vals,.025)),float(np.quantile(vals,.975))

def load():
    paths=[OUT/'osahr_twin_runs.csv',OUT/'osahr_twin_extension.csv',OUT/'osahr_twin_param_matched.csv',OUT/'osahr_twin_paired_sparse.csv']
    dfs=[pd.read_csv(p) for p in paths if p.exists()]
    if not dfs: raise FileNotFoundError('no bridge shards')
    d=pd.concat(dfs,ignore_index=True)
    # Deduplicate exact arm key, preferring later shards.
    arm=['regime','hazard_model','policy','scenario','replicate']
    d=d.drop_duplicates(arm,keep='last').sort_values(arm).reset_index(drop=True)
    return d

def main():
    d=load(); arm=['regime','hazard_model','policy','scenario','replicate']
    # Common-root-random-number contract.
    seed_n=d.groupby(['regime','scenario','replicate']).seed.nunique()
    if int(seed_n.max()) != 1: raise AssertionError('CRN root seed mismatch')
    d.to_csv(OUT/'osahr_twin_runs_combined.csv',index=False)

    # Average stochastic replicates within independent telemetry scenario.
    numeric=[c for c in d.columns if c not in ['hazard_model','regime','policy','state_hash']]
    scen=d.groupby(['regime','hazard_model','policy','scenario'],as_index=False)[numeric].mean(numeric_only=True)
    scen.to_csv(OUT/'osahr_scenario_means.csv',index=False)

    agg=[]
    for (reg,model,pol),g in scen.groupby(['regime','hazard_model','policy'],sort=True):
        row={'regime':reg,'hazard_model':model,'policy':pol,'n_scenarios':len(g),'replicates_per_scenario':int(d[(d.regime==reg)&(d.hazard_model==model)&(d.policy==pol)].groupby('scenario').size().median())}
        for metric in ['goal_utility_ratio','critical_success_rate','mean_latency','energy','outages','reroutes']:
            m,lo,hi=boot_stat(g[metric],seed=stable_seed(reg,model,pol,metric))
            row[f'{metric}_mean']=m;row[f'{metric}_ci_lo']=lo;row[f'{metric}_ci_hi']=hi
        agg.append(row)
    pd.DataFrame(agg).to_csv(OUT/'osahr_aggregate_clustered.csv',index=False)

    fidelity=[]; effects=[]
    for reg in sorted(scen.regime.unique()):
        sr=scen[scen.regime==reg]
        # Scenario-level policy effects.
        adv_by={}
        for model in sorted(sr.hazard_model.unique()):
            p=sr[sr.hazard_model==model].pivot(index='scenario',columns='policy',values='goal_utility_ratio').dropna()
            adv=p['semantic']-p['throughput']; adv_by[model]=adv
            m,lo,hi=boot_stat(adv,seed=stable_seed('adv',reg,model))
            effects.append({'regime':reg,'hazard_model':model,'n_scenarios':len(adv),'semantic_advantage_mean':m,'semantic_advantage_ci_lo':lo,'semantic_advantage_ci_hi':hi})
        oa=adv_by.get('oracle')
        for model in sorted(sr.hazard_model.unique()):
            if model=='oracle':continue
            for pol in ['throughput','semantic']:
                mg=sr[(sr.hazard_model==model)&(sr.policy==pol)].set_index('scenario')
                og=sr[(sr.hazard_model=='oracle')&(sr.policy==pol)].set_index('scenario')
                idx=mg.index.intersection(og.index)
                row={'regime':reg,'hazard_model':model,'policy':pol,'n_scenarios':len(idx)}
                for metric in METRICS:
                    e=(mg.loc[idx,metric]-og.loc[idx,metric]).to_numpy(float)
                    row[f'{metric}_bias']=float(e.mean()); row[f'{metric}_mae']=float(np.abs(e).mean()); row[f'{metric}_rmse']=float(np.sqrt(np.mean(e*e)))
                if oa is not None and model in adv_by:
                    common=oa.index.intersection(adv_by[model].index)
                    pe=(adv_by[model].loc[common]-oa.loc[common]).to_numpy(float)
                    mae,lo,hi=boot_stat(pe,fn=lambda z:np.mean(np.abs(z)),seed=stable_seed('pe',reg,model))
                    row['policy_effect_error_mae']=mae; row['policy_effect_error_mae_ci_lo']=lo;row['policy_effect_error_mae_ci_hi']=hi
                    row['policy_effect_error_bias']=float(pe.mean())
                    ovals=oa.loc[common].to_numpy(); mvals=adv_by[model].loc[common].to_numpy(); nz=np.abs(ovals)>1e-12
                    row['policy_effect_sign_agreement']=float(np.mean(np.sign(ovals[nz])==np.sign(mvals[nz]))) if nz.any() else np.nan
                fidelity.append(row)
    pd.DataFrame(effects).to_csv(OUT/'policy_advantage_clustered.csv',index=False)
    f=pd.DataFrame(fidelity);f.to_csv(OUT/'oracle_fidelity_clustered.csv',index=False)
    compact=[]
    for (reg,model),g in f.groupby(['regime','hazard_model']):
        compact.append({'regime':reg,'hazard_model':model,'goal_utility_mae':float(g.goal_utility_ratio_mae.mean()),'critical_success_mae':float(g.critical_success_rate_mae.mean()),'latency_mae':float(g.mean_latency_mae.mean()),'outage_mae':float(g.outages_mae.mean()),'reroute_mae':float(g.reroutes_mae.mean()),'policy_effect_error_mae':float(g.policy_effect_error_mae.iloc[0]),'policy_effect_sign_agreement':float(g.policy_effect_sign_agreement.iloc[0])})
    c=pd.DataFrame(compact).sort_values(['regime','goal_utility_mae']); c.to_csv(OUT/'oracle_fidelity_summary_clustered.csv',index=False)
    audit={'rows':len(d),'unique_arms':len(d.drop_duplicates(arm)),'scenarios_by_regime':{r:int(scen[scen.regime==r].scenario.nunique()) for r in scen.regime.unique()},'bootstrap_replicates':B,'independent_unit':'paired fast/robust telemetry scenario','stochastic_replicates_averaged_within_scenario':True,'common_root_seed_verified':bool(seed_n.max()==1)}
    (OUT/'osahr_analysis_audit.json').write_text(json.dumps(audit,indent=2))
    print(json.dumps(audit,indent=2));print('\nFidelity\n',c.to_string(index=False));print('\nEffects\n',pd.DataFrame(effects).to_string(index=False))
if __name__=='__main__':main()
