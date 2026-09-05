#!/usr/bin/env python3
from __future__ import annotations
import sys
from pathlib import Path as _BootstrapPath
_ROOT = _BootstrapPath(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path: sys.path.insert(0, str(_ROOT))
import argparse, json, csv
from pathlib import Path
import pandas as pd
import torch

from liquid_osahr02b.field import HazardBounds
from liquid_osahr02b.ran import ResidualGraphCfC, RAN_STRUCT_DIM
from liquid_osahr02b.ran_experiment import paired_scenarios, run_counterfactual

ROOT_SEED=620218
REGIME_OFFSET={"id":0,"high_mobility":1,"high_stress":2}

def load_model(root:Path):
    ck=torch.load(root/'artifacts/residual_cfc.pt', map_location='cpu', weights_only=False)
    hidden=int(ck['config']['hidden_size'])
    model=ResidualGraphCfC(RAN_STRUCT_DIM,hidden)
    model.load_state_dict(ck['state_dict']); model.eval()
    return model

def key(row):
    return (int(row['replicate']),str(row['model']),str(row['policy']))

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument('--regime',required=True,choices=list(REGIME_OFFSET))
    ap.add_argument('--scenario',required=True,type=int)
    ap.add_argument('--replicates',type=int,default=2)
    ap.add_argument('--horizon',type=float,default=3.0)
    args=ap.parse_args()
    root=Path(__file__).resolve().parents[1]
    model=load_model(root); bounds=HazardBounds()
    cal_id=json.loads((root/'artifacts/intervention_calibration.json').read_text())
    cal_rob=json.loads((root/'artifacts/intervention_calibration_multi.json').read_text())
    training=json.loads((root/'artifacts/training_summary.json').read_text())
    t_pred=float(training.get('predictive_trust',1.0)); t_int=float(cal_id['selected_trust']); t_rob=float(cal_rob['selected_trust'])
    ri=REGIME_OFFSET[args.regime]
    sc=paired_scenarios(ROOT_SEED+1003*ri,args.scenario+1,args.regime)[args.scenario]
    specs=[('oracle',1.0),('mechanistic',0.0),('residual_raw',1.0),('residual_predictive',t_pred),('residual_intervention',t_int),('residual_robust',t_rob)]
    out=root/'artifacts'/f'extend_{args.regime}_{args.scenario}.csv'
    existing=[]
    if out.exists() and out.stat().st_size:
        existing=pd.read_csv(out).to_dict('records')
    done={key(r) for r in existing}; rows=list(existing)
    sid=100*ri+args.scenario
    for rep in range(args.replicates):
        for kind,trust in specs:
            for pol in ('throughput','semantic'):
                if (rep,kind,pol) in done:
                    print(f'SKIP {args.regime} scenario={args.scenario} rep={rep} {kind} {pol}',flush=True); continue
                print(f'RUN {args.regime} scenario={args.scenario} rep={rep} {kind} {pol}',flush=True)
                d=run_counterfactual(kind,sc,pol,scenario_id=sid,replicate=rep,root_seed=ROOT_SEED,model=model,trust=trust,horizon=args.horizon,bounds=bounds,verify=False)
                d['regime']=args.regime
                for k,v in sc.__dict__.items(): d[f'scenario_{k}']=v
                rows.append(d); done.add((rep,kind,pol))
                # Atomic whole-file checkpoint after every completed arm.
                tmp=out.with_suffix('.tmp')
                pd.DataFrame(rows).to_csv(tmp,index=False)
                tmp.replace(out)
    print('WROTE',out,len(rows))
if __name__=='__main__': main()
