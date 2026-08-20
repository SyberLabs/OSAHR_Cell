from __future__ import annotations
from pathlib import Path
import json, math
import numpy as np
import pandas as pd
from liquid_osahr02a.counterfactual import analyze_study, policy_effect_table

ROOT=Path(__file__).resolve().parents[1]
ART=ROOT/'artifacts'
df=pd.read_csv(ART/'counterfactual_release_full.csv')

metrics=['goal_utility_ratio','critical_success_rate','mean_latency','energy','events','outages','handovers','reroutes']
summary={}
for metric in metrics:
    summary[metric]=analyze_study(df,metric=metric,n_boot=50000)

# Scenario-level treatment effects and explicit paired differences to oracle.
rows=[]
for metric in ['goal_utility_ratio','critical_success_rate','mean_latency']:
    eff=policy_effect_table(df,metric)
    for regime in sorted(eff.regime.unique()):
        sub=eff[eff.regime==regime]
        oracle=sub[sub.model=='oracle'].set_index('scenario')['effect']
        for model in sorted(sub.model.unique()):
            e=sub[sub.model==model].set_index('scenario')['effect'].reindex(oracle.index)
            err=e-oracle
            rows.append({
                'metric':metric,'regime':regime,'model':model,
                'effect_mean':float(e.mean()),'oracle_effect_mean':float(oracle.mean()),
                'effect_bias':float(err.mean()),'effect_mae':float(np.abs(err).mean()),
                'effect_rmse':float(np.sqrt(np.mean(err**2))),
                'effect_sign_agreement':float(np.mean(np.sign(e)==np.sign(oracle))),
                'effect_rank_corr':float(e.corr(oracle,method='spearman')) if len(e)>1 else math.nan,
            })
pd.DataFrame(rows).to_csv(ART/'counterfactual_effect_fidelity.csv',index=False)

# Level fidelity and event-distribution fidelity after averaging replicates.
sm=df.groupby(['regime','scenario','model','policy'],as_index=False).mean(numeric_only=True)
level_rows=[]
for regime in sorted(sm.regime.unique()):
    sr=sm[sm.regime==regime]
    oracle=sr[sr.model=='oracle'].set_index(['scenario','policy'])
    for model in sorted(set(sr.model)-{'oracle'}):
        m=sr[sr.model==model].set_index(['scenario','policy']).reindex(oracle.index)
        d={'regime':regime,'model':model}
        for metric in ['goal_utility_ratio','critical_success_rate','mean_latency','events','outages','handovers','reroutes']:
            err=m[metric]-oracle[metric]
            d[metric+'_mae']=float(np.abs(err).mean())
            d[metric+'_rmse']=float(np.sqrt(np.mean(err**2)))
            d[metric+'_bias']=float(err.mean())
        level_rows.append(d)
pd.DataFrame(level_rows).to_csv(ART/'counterfactual_level_fidelity.csv',index=False)

# Bounded thinning audit.
bounds={
    'rows':int(len(df)),
    'max_events':int(df.events.max()),
    'max_thinning_rejections':int(df.thinning_rejections.max()),
    'total_thinning_rejections':int(df.thinning_rejections.sum()),
    'total_thinning_windows':int(df.thinning_windows.sum()),
    'rejection_per_event_mean':float((df.thinning_rejections/df.events.clip(lower=1)).mean()),
    'state_hash_unique':int(df.final_hash.nunique()),
}

# Bootstrap oracle effects and model effect errors directly at scenario level.
def boot(v,seed,n=50000):
    v=np.asarray(v,float); rng=np.random.default_rng(seed)
    draws=v[rng.integers(0,len(v),size=(n,len(v)))].mean(axis=1)
    return {'mean':float(v.mean()),'lo':float(np.quantile(draws,.025)),'hi':float(np.quantile(draws,.975))}
primary={}
for regime in sorted(df.regime.unique()):
    primary[regime]={}
    for metric in ['goal_utility_ratio','critical_success_rate']:
        eff=policy_effect_table(df[df.regime==regime],metric)
        oracle=eff[eff.model=='oracle'].set_index('scenario')['effect']
        block={'oracle_effect':boot(oracle.values,1000+sum(map(ord,regime+metric))),'models':{}}
        for model in ['cfc_closed','cfc_nojump','gru_closed']:
            e=eff[eff.model==model].set_index('scenario')['effect'].reindex(oracle.index)
            err=e-oracle
            block['models'][model]={
                'effect':boot(e.values,2000+sum(map(ord,model+regime+metric))),
                'effect_error':boot(err.values,3000+sum(map(ord,model+regime+metric))),
                'effect_mae':float(np.abs(err).mean()),
                'sign_agreement':float(np.mean(np.sign(e)==np.sign(oracle))),
            }
        primary[regime][metric]=block

(ART/'counterfactual_analysis.json').write_text(json.dumps({'primary':primary,'summary':summary,'audit':bounds},indent=2))
print(json.dumps(primary,indent=2))
print('AUDIT',json.dumps(bounds,indent=2))
