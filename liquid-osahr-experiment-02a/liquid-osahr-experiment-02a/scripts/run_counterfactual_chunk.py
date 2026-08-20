#!/usr/bin/env python3
from __future__ import annotations
import argparse, json
from dataclasses import asdict
from pathlib import Path
import sys
import torch
import pandas as pd

ROOT=Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path: sys.path.insert(0,str(ROOT))
from liquid_osahr02a.field import HazardBounds
from liquid_osahr02a.training import build_field_model
from liquid_osahr02a.counterfactual import paired_scenarios, run_counterfactual
from liquid_osahr02a.twin import TwinConfig

PARSER=argparse.ArgumentParser()
PARSER.add_argument('--regime',choices=['id','high_mobility','high_stress'],required=True)
PARSER.add_argument('--start',type=int,required=True)
PARSER.add_argument('--count',type=int,default=2)
PARSER.add_argument('--n-scenarios',type=int,default=6)
PARSER.add_argument('--replicates',type=int,default=1)
PARSER.add_argument('--rep-start',type=int,default=0)
PARSER.add_argument('--horizon',type=float,default=12.0)
PARSER.add_argument('--root-seed',type=int,default=912017)
PARSER.add_argument('--output',type=Path,required=True)
PARSER.add_argument('--verify-first',action='store_true')
PARSER.add_argument('--kinds',nargs='+',default=['oracle','cfc_closed','cfc_nojump','gru_closed'])
PARSER.add_argument('--policies',nargs='+',default=['throughput','semantic'])
args=PARSER.parse_args()

models={}
for kind in [k for k in args.kinds if k!='oracle']:
    model=build_field_model(kind)
    ck=ROOT/'artifacts'/f'{kind}_seed260218.pt'
    payload=torch.load(ck,map_location='cpu',weights_only=False)
    state=(payload['state_dict'] if isinstance(payload,dict) and 'state_dict' in payload else (payload['model_state'] if isinstance(payload,dict) and 'model_state' in payload else payload))
    model.load_state_dict(state)
    model.eval(); models[kind]=model

regime_i={'id':0,'high_mobility':1,'high_stress':2}[args.regime]
scenarios=paired_scenarios(args.root_seed+113*regime_i,args.n_scenarios,args.regime)
bounds=HazardBounds(); cfg=TwinConfig(horizon=args.horizon)
rows=[]
for sidx in range(args.start,min(args.start+args.count,args.n_scenarios)):
    sc=scenarios[sidx]
    for rep in range(args.rep_start,args.rep_start+args.replicates):
        for kind in args.kinds:
            for policy in args.policies:
                row=run_counterfactual(kind=kind,scenario=sc,regime=args.regime,scenario_id=sidx,replicate=rep,policy=policy,root_seed=args.root_seed,models=models,bounds=bounds,cfg=cfg,
                    verify_incremental=args.verify_first and sidx==args.start and rep==0 and kind=='cfc_closed' and policy=='semantic')
                d=asdict(row); d.update({f'scenario_{k}':v for k,v in asdict(sc).items()}); rows.append(d)
                print(json.dumps({'regime':args.regime,'scenario':sidx,'rep':rep,'kind':kind,'policy':policy,'goal':d['goal_utility_ratio'],'events':d['events']}),flush=True)
args.output.parent.mkdir(parents=True,exist_ok=True)
pd.DataFrame(rows).to_csv(args.output,index=False)
print(f'WROTE {args.output} rows={len(rows)}',flush=True)
