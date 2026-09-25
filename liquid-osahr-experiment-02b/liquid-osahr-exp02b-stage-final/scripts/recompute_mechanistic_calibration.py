#!/usr/bin/env python3
from __future__ import annotations
import sys
from pathlib import Path as _BootstrapPath
_ROOT = _BootstrapPath(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path: sys.path.insert(0, str(_ROOT))
import argparse,json
from pathlib import Path
import pandas as pd, torch
from liquid_osahr02b.field import HazardBounds
from liquid_osahr02b.ran import ResidualGraphCfC,RAN_STRUCT_DIM
from liquid_osahr02b.ran_experiment import paired_scenarios,run_counterfactual
ROOT=771177;REGIMES=('id','high_mobility','high_stress')

def load_model(root):
 ck=torch.load(root/'artifacts/residual_cfc.pt',map_location='cpu',weights_only=False);m=ResidualGraphCfC(RAN_STRUCT_DIM,int(ck['config']['hidden_size']));m.load_state_dict(ck['state_dict']);m.eval();return m

def main():
 ap=argparse.ArgumentParser();ap.add_argument('--regime',required=True,choices=REGIMES);ap.add_argument('--n',type=int,default=6);args=ap.parse_args()
 root=Path(__file__).resolve().parents[1];model=load_model(root);b=HazardBounds();ri=REGIMES.index(args.regime);out=root/'artifacts'/f'cal_mechanistic_exact_{args.regime}.csv'
 rows=pd.read_csv(out).to_dict('records') if out.exists() and out.stat().st_size else [];done={(int(r['scenario_local']),str(r['model']),str(r['policy'])) for r in rows}
 scenarios=paired_scenarios(ROOT+1379*ri,args.n,args.regime)
 for si,sc in enumerate(scenarios):
  sid=1000*ri+si
  for kind in ('oracle','mechanistic'):
   for pol in ('throughput','semantic'):
    if (si,kind,pol) in done: continue
    print('RUN',args.regime,si,kind,pol,flush=True)
    d=run_counterfactual(kind,sc,pol,scenario_id=sid,replicate=0,root_seed=ROOT,model=model,trust=0.0,horizon=2.0,bounds=b)
    d.update({'regime':args.regime,'scenario_local':si,'model':kind,'policy':pol});rows.append(d);done.add((si,kind,pol));tmp=out.with_suffix('.tmp');pd.DataFrame(rows).to_csv(tmp,index=False);tmp.replace(out)
 assert len(rows)==args.n*4
 print('WROTE',out,len(rows))
if __name__=='__main__':main()
