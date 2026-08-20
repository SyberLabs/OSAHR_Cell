from __future__ import annotations
import argparse
from dataclasses import asdict
from pathlib import Path
import pandas as pd

from liquid_osahr02a.counterfactual import run_counterfactual, paired_scenarios
from liquid_osahr02a.field import HazardBounds
from liquid_osahr02a.twin import TwinConfig
from liquid_osahr02a.training import load_checkpoint

ROOT=Path(__file__).resolve().parents[1]
REGIMES=['id','high_mobility','high_stress']

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument('--regime',choices=REGIMES,required=True)
    ap.add_argument('--start',type=int,required=True)
    ap.add_argument('--stop',type=int,required=True)
    ap.add_argument('--n-scenarios',type=int,default=6)
    ap.add_argument('--replicates',type=int,default=2)
    ap.add_argument('--horizon',type=float,default=12.0)
    ap.add_argument('--root-seed',type=int,default=912017)
    ap.add_argument('--output',type=Path,required=True)
    ap.add_argument('--resume',action='store_true')
    args=ap.parse_args()
    args.output.parent.mkdir(parents=True,exist_ok=True)
    models={}
    for name in ['cfc_closed','cfc_nojump','gru_closed']:
        models[name]=load_checkpoint(ROOT/'artifacts'/f'{name}_seed260218.pt')[0]
    ridx=REGIMES.index(args.regime)
    scenarios=paired_scenarios(args.root_seed+113*ridx,args.n_scenarios,args.regime)
    rows=[]; bounds=HazardBounds(); cfg=TwinConfig(horizon=args.horizon)
    done=set()
    if args.output.exists() and args.resume:
        old=pd.read_csv(args.output)
        for _,r in old.iterrows(): done.add((r.regime,int(r.scenario),int(r.replicate),r.model,r.policy))
    elif args.output.exists(): args.output.unlink()
    for sidx in range(args.start,args.stop):
        sc=scenarios[sidx]
        for rep in range(args.replicates):
            for kind in ['oracle','cfc_closed','cfc_nojump','gru_closed']:
                for policy in ['throughput','semantic']:
                    if (args.regime,sidx,rep,kind,policy) in done: continue
                    r=run_counterfactual(kind=kind,scenario=sc,regime=args.regime,scenario_id=sidx,replicate=rep,policy=policy,root_seed=args.root_seed,models=models,bounds=bounds,cfg=cfg,verify_incremental=(args.regime=='id' and sidx==0 and rep==0 and kind=='cfc_closed' and policy=='semantic'))
                    d=asdict(r); d.update({f'scenario_{k}':v for k,v in asdict(sc).items()}); rows.append(d)
                    pd.DataFrame([d]).to_csv(args.output,index=False,mode='a',header=not args.output.exists())
                    print(args.regime,sidx,rep,kind,policy,f'U={r.goal_utility_ratio:.4f}',f'E={r.events}',flush=True)
    args.output.parent.mkdir(parents=True,exist_ok=True)
    print('wrote',args.output,'rows',len(rows))
if __name__=='__main__': main()
