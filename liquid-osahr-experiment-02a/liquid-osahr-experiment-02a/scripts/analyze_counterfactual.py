#!/usr/bin/env python3
from pathlib import Path
import json, sys
import pandas as pd
ROOT=Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path: sys.path.insert(0,str(ROOT))
from liquid_osahr02a.counterfactual import analyze_study,policy_effect_table

files=[
'artifacts/cf_id_00.csv','artifacts/cf_id_02.csv','artifacts/cf_id_03_parts1.csv','artifacts/cf_id_03_parts2.csv','artifacts/cf_id_04a.csv','artifacts/cf_id_04b.csv',
'artifacts/cf_hm_00a.csv','artifacts/cf_hm_00b.csv','artifacts/cf_hm_02a.csv','artifacts/cf_hm_02b.csv','artifacts/cf_hm_04a.csv','artifacts/cf_hm_04b.csv','artifacts/cf_hm_05b.csv',
'artifacts/cf_hs_00a.csv','artifacts/cf_hs_00b.csv','artifacts/cf_hs_02a.csv','artifacts/cf_hs_02b.csv','artifacts/cf_hs_03b.csv','artifacts/cf_hs_04a.csv','artifacts/cf_hs_04b.csv',
'artifacts/cf2_id_00a.csv','artifacts/cf2_id_00b.csv','artifacts/cf2_id_02a.csv','artifacts/cf2_id_02b.csv','artifacts/cf2_id_04a.csv','artifacts/cf2_id_04b.csv',
'artifacts/cf2_hm_00a.csv','artifacts/cf2_hm_00b.csv','artifacts/cf2_hm_02a.csv','artifacts/cf2_hm_02b.csv','artifacts/cf2_hm_03b.csv','artifacts/cf2_hm_04a.csv','artifacts/cf2_hm_04b.csv',
'artifacts/cf2_hs_00a.csv','artifacts/cf2_hs_00b.csv','artifacts/cf2_hs_02a.csv','artifacts/cf2_hs_02b.csv','artifacts/cf2_hs_04a.csv','artifacts/cf2_hs_04b.csv'
]
df=pd.concat([pd.read_csv(ROOT/f) for f in files],ignore_index=True)
keys=['regime','scenario','replicate','model','policy']
dups=df.duplicated(keys,keep=False)
if dups.any():
    print(df.loc[dups,keys].sort_values(keys).to_string(index=False)); raise SystemExit('duplicates')
expected=3*6*2*4*2
if len(df)!=expected: raise SystemExit(f'row mismatch {len(df)} != {expected}')
# Validate complete factorial
sizes=df.groupby(['regime','scenario']).size()
assert (sizes==16).all(),sizes
# common RNG seed within scenario replicate across model/policy
assert (df.groupby(['regime','scenario','replicate']).seed.nunique()==1).all()

df=df.sort_values(keys).reset_index(drop=True)
df.to_csv(ROOT/'artifacts/counterfactual_study.csv',index=False)
analysis={
 'design':{'rows':len(df),'regimes':3,'independent_scenarios_per_regime':6,'replicates_per_arm':2,'models':4,'policies':2,'horizon_seconds':12.0},
 'goal_utility':analyze_study(df,metric='goal_utility_ratio',n_boot=30000),
 'critical_success':analyze_study(df,metric='critical_success_rate',n_boot=30000),
 'latency':analyze_study(df,metric='mean_latency',n_boot=30000),
}
# enrich raw means, thinning stats, event count fidelity
for regime in sorted(df.regime.unique()):
    analysis.setdefault('descriptives',{})[regime]={}
    for model in sorted(df.model.unique()):
        p=df[(df.regime==regime)&(df.model==model)]
        analysis['descriptives'][regime][model]={
            pol:{
                'goal_utility_mean':float(q.goal_utility_ratio.mean()),
                'critical_success_mean':float(q.critical_success_rate.mean()),
                'mean_latency':float(q.mean_latency.mean()),
                'events_mean':float(q.events.mean()),
                'thinning_rejections_mean':float(q.thinning_rejections.mean()),
                'thinning_windows_mean':float(q.thinning_windows.mean()),
            } for pol,q in p.groupby('policy')
        }
# effect table
policy_effect_table(df).to_csv(ROOT/'artifacts/policy_effects.csv',index=False)
(ROOT/'artifacts/counterfactual_analysis.json').write_text(json.dumps(analysis,indent=2))
print(json.dumps(analysis['goal_utility'],indent=2))
print('ROWS',len(df))
