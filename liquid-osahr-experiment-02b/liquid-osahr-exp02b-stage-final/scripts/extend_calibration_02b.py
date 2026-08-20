#!/usr/bin/env python3
from __future__ import annotations
import sys
from pathlib import Path as _BootstrapPath
_ROOT = _BootstrapPath(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path: sys.path.insert(0, str(_ROOT))
if str(_ROOT / "vendor") not in sys.path: sys.path.insert(0, str(_ROOT / "vendor"))
import argparse,json
from pathlib import Path
import numpy as np, torch
from liquid_osahr02b.field import HazardBounds
from liquid_osahr02b.ran import ResidualGraphCfC,RAN_STRUCT_DIM
from liquid_osahr02b.ran_experiment import paired_scenarios,run_counterfactual
ROOT_SEED=771177
REGIMES=('id','high_mobility','high_stress')
GRID=(0,.25,.5,.75,1.0)

def load_model(root):
 ck=torch.load(root/'artifacts/residual_cfc.pt',map_location='cpu',weights_only=False)
 m=ResidualGraphCfC(RAN_STRUCT_DIM,int(ck['config']['hidden_size']));m.load_state_dict(ck['state_dict']);m.eval();return m

def main():
 ap=argparse.ArgumentParser();ap.add_argument('--regime',required=True,choices=REGIMES);ap.add_argument('--scenario',type=int,required=True);ap.add_argument('--horizon',type=float,default=2.0);args=ap.parse_args()
 root=Path(__file__).resolve().parents[1];model=load_model(root);bounds=HazardBounds();ri=REGIMES.index(args.regime)
 sc=paired_scenarios(ROOT_SEED+1379*ri,args.scenario+1,args.regime)[args.scenario];sid=1000*ri+args.scenario
 out=root/'artifacts'/f'cal_extend_{args.regime}_{args.scenario}.json'
 payload={'regime':args.regime,'scenario':args.scenario,'scenario_params':sc.__dict__,'horizon':args.horizon,'oracle':{},'grid':{}}
 if out.exists(): payload=json.loads(out.read_text())
 def save():
  tmp=out.with_suffix('.tmp');tmp.write_text(json.dumps(payload,indent=2));tmp.replace(out)
 if not payload.get('oracle') or set(payload['oracle'])!={'throughput','semantic'}:
  payload['oracle']={}
  for pol in ('throughput','semantic'):
   print('RUN oracle',args.regime,args.scenario,pol,flush=True)
   payload['oracle'][pol]=run_counterfactual('oracle',sc,pol,scenario_id=sid,replicate=0,root_seed=ROOT_SEED,model=model,horizon=args.horizon,bounds=bounds)['goal_utility_ratio'];save()
 oracle_eff=payload['oracle']['semantic']-payload['oracle']['throughput']
 for a in GRID:
  key=f'{a:.2f}'
  if key in payload.get('grid',{}) and 'error' in payload['grid'][key]: continue
  vals={}
  for pol in ('throughput','semantic'):
   print('RUN',key,args.regime,args.scenario,pol,flush=True)
   vals[pol]=run_counterfactual(f'residual_{a:.2f}',sc,pol,scenario_id=sid,replicate=0,root_seed=ROOT_SEED,model=model,trust=a,horizon=args.horizon,bounds=bounds)['goal_utility_ratio']
  eff=vals['semantic']-vals['throughput']
  payload.setdefault('grid',{})[key]={'trust':a,'throughput':vals['throughput'],'semantic':vals['semantic'],'effect':eff,'error':abs(eff-oracle_eff)};save()
 print('WROTE',out)
if __name__=='__main__':main()
