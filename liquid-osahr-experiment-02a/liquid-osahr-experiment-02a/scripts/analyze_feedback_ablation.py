from __future__ import annotations
from pathlib import Path
import json
import numpy as np
import pandas as pd

ROOT=Path(__file__).resolve().parents[1]
ART=ROOT/'artifacts'
df=pd.read_csv(ART/'counterfactual_release_full.csv')
METRICS=['goal_utility_ratio','critical_success_rate','mean_latency']
COMPARATORS=['cfc_nojump','cfc_openloop','gru_closed']

# Average stochastic replicates first: telemetry scenario is the independent unit.
sm=df.groupby(['regime','scenario','model','policy'],as_index=False).mean(numeric_only=True)

def bootstrap(v:np.ndarray, seed:int, n:int=50000):
    v=np.asarray(v,float); rng=np.random.default_rng(seed)
    draws=v[rng.integers(0,len(v),size=(n,len(v)))].mean(axis=1)
    return float(v.mean()),float(np.quantile(draws,.025)),float(np.quantile(draws,.975))

rows=[]
for metric in METRICS:
    for regime in sorted(sm.regime.unique()):
        s=sm[sm.regime==regime]
        # Policy effect by scenario/model.
        eff=s.pivot_table(index=['scenario','model'],columns='policy',values=metric)
        eff['effect']=eff['semantic']-eff['throughput']
        oracle_eff=eff.xs('oracle',level='model')['effect']
        closed_eff=eff.xs('cfc_closed',level='model')['effect'].reindex(oracle_eff.index)
        closed_abs=np.abs(closed_eff-oracle_eff)

        # Level errors pool two policy levels *within scenario* then average so
        # scenario remains the independent sampling unit.
        oracle_levels=s[s.model=='oracle'].set_index(['scenario','policy'])[metric]
        closed_levels=s[s.model=='cfc_closed'].set_index(['scenario','policy'])[metric].reindex(oracle_levels.index)
        closed_level_abs=(closed_levels-oracle_levels).abs().groupby(level='scenario').mean()

        for comp in COMPARATORS:
            comp_eff=eff.xs(comp,level='model')['effect'].reindex(oracle_eff.index)
            comp_abs=np.abs(comp_eff-oracle_eff)
            # negative = closed loop has lower oracle effect error
            d_effect=(closed_abs-comp_abs).to_numpy()
            emean,elo,ehi=bootstrap(d_effect,seed=7100+sum(map(ord,metric+regime+comp)))

            comp_levels=s[s.model==comp].set_index(['scenario','policy'])[metric].reindex(oracle_levels.index)
            comp_level_abs=(comp_levels-oracle_levels).abs().groupby(level='scenario').mean()
            d_level=(closed_level_abs-comp_level_abs).to_numpy()
            lmean,llo,lhi=bootstrap(d_level,seed=9100+sum(map(ord,metric+regime+comp)))
            rows.append({
                'metric':metric,'regime':regime,'comparison':f'cfc_closed - {comp}',
                'effect_abs_error_difference':emean,'effect_abs_error_lo':elo,'effect_abs_error_hi':ehi,
                'level_abs_error_difference':lmean,'level_abs_error_lo':llo,'level_abs_error_hi':lhi,
                'closed_effect_mae':float(closed_abs.mean()),'comparator_effect_mae':float(comp_abs.mean()),
                'closed_level_mae':float(closed_level_abs.mean()),'comparator_level_mae':float(comp_level_abs.mean()),
            })
out=pd.DataFrame(rows)
out.to_csv(ART/'feedback_ablation.csv',index=False)
(ART/'feedback_ablation.json').write_text(json.dumps(out.to_dict(orient='records'),indent=2))
print(out.to_string(index=False))
