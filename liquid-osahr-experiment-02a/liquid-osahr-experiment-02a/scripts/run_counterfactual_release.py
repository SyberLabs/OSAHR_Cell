from __future__ import annotations
from dataclasses import asdict
from pathlib import Path
import pandas as pd
from liquid_osahr02a.counterfactual import run_counterfactual, paired_scenarios
from liquid_osahr02a.field import HazardBounds
from liquid_osahr02a.twin import TwinConfig
from liquid_osahr02a.training import load_checkpoint
ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'artifacts'/'counterfactual_release.csv'
ROOT_SEED=912017
REGIMES=['id','high_mobility','high_stress']; N_SCENARIOS=6; REPLICATES=2; HORIZON=10.0
KINDS=['oracle','cfc_closed','cfc_nojump','gru_closed']; POLICIES=['throughput','semantic']
def main():
    models={n:load_checkpoint(ROOT/'artifacts'/f'{n}_seed260218.pt')[0] for n in ['cfc_closed','cfc_nojump','gru_closed']}
    done=set()
    if OUT.exists():
        old=pd.read_csv(OUT)
        for _,r in old.iterrows(): done.add((r.regime,int(r.scenario),int(r.replicate),r.model,r.policy))
        print('resuming',len(done),'rows',flush=True)
    bounds=HazardBounds(); cfg=TwinConfig(horizon=HORIZON)
    for ridx,regime in enumerate(REGIMES):
        scenarios=paired_scenarios(ROOT_SEED+113*ridx,N_SCENARIOS,regime)
        for sidx,sc in enumerate(scenarios):
            for rep in range(REPLICATES):
                for kind in KINDS:
                    for policy in POLICIES:
                        k=(regime,sidx,rep,kind,policy)
                        if k in done: continue
                        r=run_counterfactual(kind=kind,scenario=sc,regime=regime,scenario_id=sidx,replicate=rep,policy=policy,root_seed=ROOT_SEED,models=models,bounds=bounds,cfg=cfg,verify_incremental=(len(done)==0 and regime=='id' and sidx==0 and rep==0 and kind=='cfc_closed' and policy=='semantic'))
                        d=asdict(r); d.update({f'scenario_{name}':v for name,v in asdict(sc).items()})
                        pd.DataFrame([d]).to_csv(OUT,index=False,mode='a',header=not OUT.exists())
                        done.add(k)
                        print(f'{len(done):03d}/288 {regime} s{sidx} r{rep} {kind} {policy} U={r.goal_utility_ratio:.4f} C={r.critical_success_rate:.3f} ev={r.events}',flush=True)
    print('COMPLETE',len(done),OUT,flush=True)
if __name__=='__main__': main()
