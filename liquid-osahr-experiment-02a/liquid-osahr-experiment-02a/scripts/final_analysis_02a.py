from __future__ import annotations
from pathlib import Path
import json
import numpy as np
import pandas as pd
from scipy import stats

ROOT=Path(__file__).resolve().parents[1]; A=ROOT/'artifacts'
df=pd.read_csv(A/'counterfactual_release_extended.csv')
METRICS=['goal_utility_ratio','critical_success_rate','mean_latency']
PRIMARY=['cfc_closed','cfc_openloop','gru_closed']

def scenario_means(metric):
 return df.groupby(['regime','scenario','model','policy'],as_index=False)[metric].mean()
def effects(metric):
 m=scenario_means(metric); p=m.pivot_table(index=['regime','scenario','model'],columns='policy',values=metric).reset_index(); p['effect']=p['semantic']-p['throughput']; return p

def boot(v,seed,n=100000):
 v=np.asarray(v,float); v=v[np.isfinite(v)]; rng=np.random.default_rng(seed); draws=v[rng.integers(0,len(v),size=(n,len(v)))].mean(axis=1)
 return {'n':int(len(v)),'mean':float(v.mean()),'lo':float(np.quantile(draws,.025)),'hi':float(np.quantile(draws,.975)),'sd':float(v.std(ddof=1)) if len(v)>1 else 0.0}

def paired_abs_error_comparison(oracle, a, b, seed):
 common=sorted(set(oracle.index)&set(a.index)&set(b.index)); o=oracle.reindex(common).values; av=a.reindex(common).values; bv=b.reindex(common).values
 diff=np.abs(av-o)-np.abs(bv-o) # positive => b has lower absolute error
 out=boot(diff,seed)
 try: out['wilcoxon_p']=float(stats.wilcoxon(diff,zero_method='wilcox',alternative='two-sided').pvalue)
 except Exception: out['wilcoxon_p']=None
 return out

result={'design':{},'metrics':{},'feedback_ablation':{},'jump_ablation':{}}
result['design']={
 'total_rows':int(len(df)),
 'independent_scenarios_per_regime_primary':12,
 'scenarios_with_two_replicates':6,
 'scenarios_with_one_replicate':6,
 'jump_ablation_scenarios':6,
 'horizon':10.0,
 'models':sorted(df.model.unique().tolist()),
 'regimes':sorted(df.regime.unique().tolist()),
 'max_events':int(df.events.max()),
 'total_events':int(df.events.sum()),
 'total_thinning_rejections':int(df.thinning_rejections.sum()),
 'unique_final_hashes':int(df.final_hash.nunique()),
}
for metric in METRICS:
 eff=effects(metric); sm=scenario_means(metric); result['metrics'][metric]={}
 for regime in sorted(df.regime.unique()):
  ep=eff[eff.regime==regime]; oracle=ep[ep.model=='oracle'].set_index('scenario')['effect']; sr=sm[sm.regime==regime]; oracle_levels=sr[sr.model=='oracle'].set_index(['scenario','policy'])[metric]
  reg={'oracle_effect':boot(oracle.values,1000+sum(map(ord,metric+regime))),'models':{}}
  for model in sorted(set(ep.model)-{'oracle'}):
   e=ep[ep.model==model].set_index('scenario')['effect']; common=sorted(set(e.index)&set(oracle.index)); err=e.reindex(common)-oracle.reindex(common)
   levels=sr[sr.model==model].set_index(['scenario','policy'])[metric]; common_level=levels.index.intersection(oracle_levels.index); le=levels.reindex(common_level)-oracle_levels.reindex(common_level)
   reg['models'][model]={
    'effect':boot(e.reindex(common).values,2000+sum(map(ord,metric+regime+model))),
    'effect_error':boot(err.values,3000+sum(map(ord,metric+regime+model))),
    'effect_mae':float(np.abs(err).mean()),
    'effect_rmse':float(np.sqrt(np.mean(err**2))),
    'effect_sign_agreement':float(np.mean(np.sign(e.reindex(common))==np.sign(oracle.reindex(common)))),
    'level_mae':float(np.abs(le).mean()),
    'level_rmse':float(np.sqrt(np.mean(le**2))),
   }
  result['metrics'][metric][regime]=reg

# Does closed-loop feedback improve absolute policy-effect fidelity over open-loop?
for metric in ['goal_utility_ratio','critical_success_rate']:
 ep=effects(metric); result['feedback_ablation'][metric]={}
 for regime in sorted(df.regime.unique()):
  p=ep[ep.regime==regime]; o=p[p.model=='oracle'].set_index('scenario')['effect']; c=p[p.model=='cfc_closed'].set_index('scenario')['effect']; op=p[p.model=='cfc_openloop'].set_index('scenario')['effect']; g=p[p.model=='gru_closed'].set_index('scenario')['effect']
  result['feedback_ablation'][metric][regime]={
   'closed_minus_open_abs_error':paired_abs_error_comparison(o,c,op,4000+sum(map(ord,metric+regime))),
   'closed_minus_gru_abs_error':paired_abs_error_comparison(o,c,g,5000+sum(map(ord,metric+regime))),
  }
# Does learned jump feedback improve over topology-coupled no-jump CfC on first six scenarios?
for metric in ['goal_utility_ratio','critical_success_rate']:
 ep=effects(metric); result['jump_ablation'][metric]={}
 for regime in sorted(df.regime.unique()):
  p=ep[(ep.regime==regime)&(ep.scenario<6)]; o=p[p.model=='oracle'].set_index('scenario')['effect']; c=p[p.model=='cfc_closed'].set_index('scenario')['effect']; nj=p[p.model=='cfc_nojump'].set_index('scenario')['effect']
  result['jump_ablation'][metric][regime]=paired_abs_error_comparison(o,c,nj,6000+sum(map(ord,metric+regime)))

(A/'final_analysis_02a.json').write_text(json.dumps(result,indent=2))
# Flat summary tables for easy audit.
rows=[]
for metric,regs in result['metrics'].items():
 for regime,block in regs.items():
  rows.append({'metric':metric,'regime':regime,'model':'oracle',**{'effect_mean':block['oracle_effect']['mean'],'effect_lo':block['oracle_effect']['lo'],'effect_hi':block['oracle_effect']['hi'],'n_scenarios':block['oracle_effect']['n']}})
  for model,x in block['models'].items():
   rows.append({'metric':metric,'regime':regime,'model':model,'effect_mean':x['effect']['mean'],'effect_lo':x['effect']['lo'],'effect_hi':x['effect']['hi'],'n_scenarios':x['effect']['n'],'effect_error_mean':x['effect_error']['mean'],'effect_error_lo':x['effect_error']['lo'],'effect_error_hi':x['effect_error']['hi'],'effect_mae':x['effect_mae'],'level_mae':x['level_mae'],'sign_agreement':x['effect_sign_agreement']})
pd.DataFrame(rows).to_csv(A/'final_policy_effect_summary.csv',index=False)
print(json.dumps(result['design'],indent=2))
for metric in ['goal_utility_ratio','critical_success_rate']:
 print('\n###',metric)
 for regime,b in result['metrics'][metric].items():
  print(regime,'oracle',b['oracle_effect'])
  for model,x in b['models'].items(): print(model,'eff',x['effect']['mean'],'errMAE',x['effect_mae'],'levelMAE',x['level_mae'],'sign',x['effect_sign_agreement'])
 print('feedback',json.dumps(result['feedback_ablation'][metric],indent=2))
 print('jump',json.dumps(result['jump_ablation'][metric],indent=2))
