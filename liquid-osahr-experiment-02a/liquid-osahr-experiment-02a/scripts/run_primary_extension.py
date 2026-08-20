from __future__ import annotations
import argparse
from dataclasses import asdict
from pathlib import Path
import pandas as pd
from liquid_osahr02a.counterfactual import run_counterfactual,paired_scenarios
from liquid_osahr02a.field import HazardBounds
from liquid_osahr02a.twin import TwinConfig
from liquid_osahr02a.training import load_checkpoint
ROOT=Path(__file__).resolve().parents[1]; REGIMES=['id','high_mobility','high_stress']
def main():
 ap=argparse.ArgumentParser(); ap.add_argument('--regime',required=True,choices=REGIMES); ap.add_argument('--start',type=int,required=True); ap.add_argument('--stop',type=int,required=True); ap.add_argument('--output',type=Path,required=True); a=ap.parse_args(); a.output.parent.mkdir(parents=True,exist_ok=True)
 models={n:load_checkpoint(ROOT/'artifacts'/f'{n}_seed260218.pt')[0] for n in ['cfc_closed','gru_closed']}
 ridx=REGIMES.index(a.regime); scenarios=paired_scenarios(912017+113*ridx,12,a.regime); bounds=HazardBounds(); cfg=TwinConfig(horizon=10); rows=[]
 for sidx in range(a.start,a.stop):
  sc=scenarios[sidx]
  for kind in ['oracle','cfc_closed','cfc_openloop','gru_closed']:
   for policy in ['throughput','semantic']:
    r=run_counterfactual(kind=kind,scenario=sc,regime=a.regime,scenario_id=sidx,replicate=0,policy=policy,root_seed=912017,models=models,bounds=bounds,cfg=cfg)
    d=asdict(r); d.update({f'scenario_{k}':v for k,v in asdict(sc).items()}); rows.append(d); print(a.regime,sidx,kind,policy,f'U={r.goal_utility_ratio:.4f}',flush=True)
 pd.DataFrame(rows).to_csv(a.output,index=False); print('wrote',len(rows))
if __name__=='__main__': main()
