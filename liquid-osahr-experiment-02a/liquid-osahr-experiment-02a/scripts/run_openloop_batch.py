from __future__ import annotations
import argparse
from dataclasses import asdict
from pathlib import Path
import pandas as pd
from liquid_osahr02a.counterfactual import run_counterfactual,paired_scenarios
from liquid_osahr02a.field import HazardBounds
from liquid_osahr02a.twin import TwinConfig
from liquid_osahr02a.training import load_checkpoint
ROOT=Path(__file__).resolve().parents[1]
REGIMES=['id','high_mobility','high_stress']
def main():
 ap=argparse.ArgumentParser(); ap.add_argument('--regime',required=True,choices=REGIMES); ap.add_argument('--start',type=int,required=True); ap.add_argument('--stop',type=int,required=True); ap.add_argument('--output',type=Path,required=True); a=ap.parse_args()
 a.output.parent.mkdir(parents=True,exist_ok=True)
 models={'cfc_closed':load_checkpoint(ROOT/'artifacts'/'cfc_closed_seed260218.pt')[0]}
 ridx=REGIMES.index(a.regime); scenarios=paired_scenarios(912017+113*ridx,6,a.regime); bounds=HazardBounds(); cfg=TwinConfig(horizon=10)
 rows=[]
 for sidx in range(a.start,a.stop):
  sc=scenarios[sidx]
  for rep in range(2):
   for policy in ['throughput','semantic']:
    r=run_counterfactual(kind='cfc_openloop',scenario=sc,regime=a.regime,scenario_id=sidx,replicate=rep,policy=policy,root_seed=912017,models=models,bounds=bounds,cfg=cfg)
    d=asdict(r); d.update({f'scenario_{k}':v for k,v in asdict(sc).items()}); rows.append(d); print(a.regime,sidx,rep,policy,r.goal_utility_ratio,flush=True)
 pd.DataFrame(rows).to_csv(a.output,index=False); print('wrote',len(rows))
if __name__=='__main__': main()
