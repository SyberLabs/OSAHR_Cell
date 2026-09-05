#!/usr/bin/env python3
"""Row-checkpointed confirmatory Experiment 02B holdout.

The protocol/trust calibration was frozen before this root seed was evaluated.
"""
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

ROOT_SEED=920218
REGIMES=('id','high_mobility','high_stress','weak_channel')

def load_model(root):
    ck=torch.load(root/'artifacts/residual_cfc.pt',map_location='cpu',weights_only=False)
    m=ResidualGraphCfC(RAN_STRUCT_DIM,int(ck['config']['hidden_size']));m.load_state_dict(ck['state_dict']);m.eval();return m

def main():
    ap=argparse.ArgumentParser();ap.add_argument('--regime',required=True,choices=REGIMES);ap.add_argument('--scenario',type=int,required=True);ap.add_argument('--replicates',type=int,default=2);ap.add_argument('--horizon',type=float,default=3.0);args=ap.parse_args()
    root=Path(__file__).resolve().parents[1];model=load_model(root);bounds=HazardBounds();ri=REGIMES.index(args.regime)
    pred=float(json.loads((root/'artifacts/training_summary.json').read_text())['predictive_trust'])
    idcal=float(json.loads((root/'artifacts/intervention_calibration.json').read_text())['selected_trust'])
    robust=float(json.loads((root/'artifacts/intervention_calibration_multi.json').read_text())['selected_trust'])
    assert robust==0.0, 'confirmatory protocol expects frozen robust trust alpha=0'
    sc=paired_scenarios(ROOT_SEED+1003*ri,args.scenario+1,args.regime)[args.scenario]
    sid=5000+100*ri+args.scenario
    # The robust-calibrated arm is exactly the mechanistic arm (alpha=0), so it
    # is represented once.  Alpha=.25 is retained as a predeclared sensitivity
    # arm because it was the provisional trust in the pilot analysis.
    specs=[('oracle',1.0),('mechanistic_calibrated',0.0),('residual_quarter',0.25),('residual_idcal',idcal),('residual_predictive',pred)]
    out=root/'artifacts'/f'confirm_{args.regime}_{args.scenario}.csv'
    rows=pd.read_csv(out).to_dict('records') if out.exists() and out.stat().st_size else []
    done={(int(r['replicate']),str(r['model']),str(r['policy'])) for r in rows}
    for rep in range(args.replicates):
        for kind,trust in specs:
            for pol in ('throughput','semantic'):
                k=(rep,kind,pol)
                if k in done: print('SKIP',args.regime,args.scenario,*k,flush=True);continue
                field_kind='mechanistic' if kind=='mechanistic_calibrated' else kind
                print('RUN',args.regime,args.scenario,rep,kind,pol,flush=True)
                d=run_counterfactual(field_kind,sc,pol,scenario_id=sid,replicate=rep,root_seed=ROOT_SEED,model=model,trust=trust,horizon=args.horizon,bounds=bounds,verify=(args.regime=='id' and args.scenario==0 and rep==0 and kind=='residual_predictive' and pol=='semantic'))
                d['model']=kind;d['trust']=trust;d['regime']=args.regime
                for kk,v in sc.__dict__.items(): d[f'scenario_{kk}']=v
                rows.append(d);done.add(k)
                tmp=out.with_suffix('.tmp');pd.DataFrame(rows).to_csv(tmp,index=False);tmp.replace(out)
    assert len(rows)==args.replicates*len(specs)*2
    print('WROTE',out,len(rows))
if __name__=='__main__':main()
