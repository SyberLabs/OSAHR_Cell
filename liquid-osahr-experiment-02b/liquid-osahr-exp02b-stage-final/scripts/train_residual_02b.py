#!/usr/bin/env python3
"""Train/re-evaluate the bounded graph-CfC residual used by Experiment 02B."""
from __future__ import annotations
import sys
from pathlib import Path as _BootstrapPath
_ROOT = _BootstrapPath(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path: sys.path.insert(0, str(_ROOT))
if str(_ROOT / "vendor") not in sys.path: sys.path.insert(0, str(_ROOT / "vendor"))
import argparse, json, pickle
from pathlib import Path
from liquid_osahr02b.field import HazardBounds
from liquid_osahr02b.ran_experiment import ResidualTrainConfig, train_residual, eval_hazard, trust_predictive_grid

def main() -> None:
    p=argparse.ArgumentParser()
    p.add_argument('--dataset',type=Path,default=Path('artifacts/ran_dataset.pkl'))
    p.add_argument('--checkpoint',type=Path,default=Path('artifacts/residual_cfc_rebuilt.pt'))
    p.add_argument('--summary',type=Path,default=Path('artifacts/training_summary_rebuilt.json'))
    p.add_argument('--seed',type=int,default=260218)
    p.add_argument('--epochs',type=int,default=55)
    p.add_argument('--hidden-size',type=int,default=20)
    a=p.parse_args()
    with a.dataset.open('rb') as f: ds=pickle.load(f)
    cfg=ResidualTrainConfig(epochs=a.epochs,hidden_size=a.hidden_size,seed=a.seed)
    b=HazardBounds(); model,payload=train_residual(ds['train'],ds['val'],b,cfg,a.checkpoint)
    pred_alpha,grid=trust_predictive_grid(model,ds['val'],b)
    out={
      'checkpoint':str(a.checkpoint),'parameter_count':payload['parameter_count'],'best_val':payload['best_val'],
      'elapsed_seconds':payload['elapsed'],'predictive_trust':pred_alpha,'predictive_grid':grid,
      'test':eval_hazard(model,ds['test'],b,pred_alpha),
    }
    a.summary.parent.mkdir(parents=True,exist_ok=True); a.summary.write_text(json.dumps(out,indent=2))
    print(json.dumps(out,indent=2))
if __name__=='__main__': main()
