from __future__ import annotations
from pathlib import Path
import json
import numpy as np
import pandas as pd

ROOT=Path(__file__).resolve().parents[1]
IN=ROOT/'artifacts/results/osahr_twin_runs.csv'
OUT=ROOT/'artifacts/results'
RNG_SEED=20260817
B=20000

METRICS=['goal_utility_ratio','critical_success_rate','mean_latency','energy','outages','recoveries','reroutes','handovers','final_queued','final_inflight']

def ci_mean(x, *, seed=RNG_SEED, B=B):
    x=np.asarray(x,float)
    if len(x)==0: return (float('nan'),float('nan'),float('nan'))
    rng=np.random.default_rng(seed)
    means=np.mean(x[rng.integers(0,len(x),(B,len(x)))],axis=1)
    return float(np.mean(x)), float(np.quantile(means,.025)), float(np.quantile(means,.975))

def ci_mae(x, *, seed=RNG_SEED+1, B=B):
    x=np.asarray(x,float)
    if len(x)==0: return (float('nan'),float('nan'),float('nan'))
    rng=np.random.default_rng(seed)
    vals=np.mean(np.abs(x[rng.integers(0,len(x),(B,len(x)))]),axis=1)
    return float(np.mean(np.abs(x))), float(np.quantile(vals,.025)), float(np.quantile(vals,.975))

def main():
    df=pd.read_csv(IN)
    assert len(df)==96
    key=['regime','scenario','replicate']
    # CRN audit: seeds identical across model/policy for each experimental unit.
    seed_nunique=df.groupby(key)['seed'].nunique()
    assert int(seed_nunique.max())==1, 'CRN seed mismatch'

    agg=[]
    for (regime,model,policy),g in df.groupby(['regime','hazard_model','policy'],sort=True):
        row={'regime':regime,'hazard_model':model,'policy':policy,'n':len(g)}
        for metric in ['goal_utility_ratio','critical_success_rate','mean_latency','energy','outages','reroutes']:
            mean,lo,hi=ci_mean(g[metric].to_numpy(),seed=RNG_SEED+hash((regime,model,policy,metric))%100000)
            row[f'{metric}_mean']=mean; row[f'{metric}_ci_lo']=lo; row[f'{metric}_ci_hi']=hi
        agg.append(row)
    pd.DataFrame(agg).to_csv(OUT/'osahr_aggregate.csv',index=False)

    fidelity=[]
    policy=[]
    for regime in sorted(df.regime.unique()):
        sub=df[df.regime==regime]
        # Policy advantages paired within each model and experimental unit.
        advantages={}
        for model in sorted(sub.hazard_model.unique()):
            x=sub[sub.hazard_model==model].pivot_table(index=['scenario','replicate'],columns='policy',values='goal_utility_ratio',aggfunc='first')
            adv=(x['semantic']-x['throughput']).sort_index()
            advantages[model]=adv
            mean,lo,hi=ci_mean(adv.to_numpy(),seed=RNG_SEED+len(policy)*19)
            policy.append({'regime':regime,'hazard_model':model,'n_units':len(adv),'semantic_advantage_mean':mean,'semantic_advantage_ci_lo':lo,'semantic_advantage_ci_hi':hi})
        oracle_adv=advantages['oracle']
        for model,adv in advantages.items():
            if model=='oracle': continue
            common=oracle_adv.index.intersection(adv.index)
            err=(adv.loc[common]-oracle_adv.loc[common]).to_numpy()
            mae,mae_lo,mae_hi=ci_mae(err,seed=RNG_SEED+31+len(fidelity))
            bias,bias_lo,bias_hi=ci_mean(err,seed=RNG_SEED+47+len(fidelity))
            nz=(np.sign(oracle_adv.loc[common].to_numpy())!=0)
            sign_agree=float(np.mean(np.sign(adv.loc[common].to_numpy()[nz])==np.sign(oracle_adv.loc[common].to_numpy()[nz]))) if np.any(nz) else float('nan')
            for p in ['throughput','semantic']:
                mg=sub[(sub.hazard_model==model)&(sub.policy==p)].set_index(['scenario','replicate'])
                og=sub[(sub.hazard_model=='oracle')&(sub.policy==p)].set_index(['scenario','replicate'])
                idx=mg.index.intersection(og.index)
                row={'regime':regime,'hazard_model':model,'policy':p,'n_units':len(idx),
                     'policy_effect_error_mae':mae,'policy_effect_error_mae_ci_lo':mae_lo,'policy_effect_error_mae_ci_hi':mae_hi,
                     'policy_effect_error_bias':bias,'policy_effect_error_bias_ci_lo':bias_lo,'policy_effect_error_bias_ci_hi':bias_hi,
                     'policy_effect_sign_agreement':sign_agree}
                for metric in METRICS:
                    d=(mg.loc[idx,metric]-og.loc[idx,metric]).to_numpy(float)
                    row[f'{metric}_bias']=float(np.mean(d))
                    row[f'{metric}_mae']=float(np.mean(np.abs(d)))
                    row[f'{metric}_rmse']=float(np.sqrt(np.mean(d*d)))
                fidelity.append(row)
    pd.DataFrame(policy).to_csv(OUT/'policy_advantage.csv',index=False)
    pd.DataFrame(fidelity).to_csv(OUT/'oracle_fidelity.csv',index=False)

    # Compact model-level fidelity averaged over both policies for headline ranking.
    f=pd.DataFrame(fidelity)
    summary=[]
    for (regime,model),g in f.groupby(['regime','hazard_model'],sort=True):
        summary.append({
            'regime':regime,'hazard_model':model,
            'goal_utility_mae':float(g.goal_utility_ratio_mae.mean()),
            'critical_success_mae':float(g.critical_success_rate_mae.mean()),
            'latency_mae':float(g.mean_latency_mae.mean()),
            'outage_mae':float(g.outages_mae.mean()),
            'reroute_mae':float(g.reroutes_mae.mean()),
            'policy_effect_error_mae':float(g.policy_effect_error_mae.iloc[0]),
            'policy_effect_sign_agreement':float(g.policy_effect_sign_agreement.iloc[0]),
        })
    sm=pd.DataFrame(summary)
    sm.to_csv(OUT/'oracle_fidelity_summary.csv',index=False)

    audit={
        'rows':len(df),'regimes':sorted(df.regime.unique().tolist()),'models':sorted(df.hazard_model.unique().tolist()),
        'policies':sorted(df.policy.unique().tolist()),'units_per_regime':int(df[df.regime==df.regime.iloc[0]][['scenario','replicate']].drop_duplicates().shape[0]),
        'common_random_numbers_verified':bool(seed_nunique.max()==1),'bootstrap_replicates':B,'bootstrap_unit':'scenario x stochastic replicate',
        'notes':['Common root PRNG seeds are matched across hazard-model and policy arms within each regime/scenario/replicate unit.',
                 'Because policy/model changes alter event consumption and subsequent state, CRN reduces but does not eliminate pathwise Monte Carlo divergence.',
                 'Oracle-fidelity metrics describe this declared synthetic teacher/twin system, not a real 6G network.']
    }
    (OUT/'release_analysis.json').write_text(json.dumps(audit,indent=2))
    print(sm.to_string(index=False))
    print('\nPolicy advantages:')
    print(pd.DataFrame(policy).to_string(index=False))

if __name__=='__main__': main()
