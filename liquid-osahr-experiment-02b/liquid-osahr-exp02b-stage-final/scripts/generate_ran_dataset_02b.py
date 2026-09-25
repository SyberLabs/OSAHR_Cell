#!/usr/bin/env python3
"""Generate a reproducible Experiment-02B standards-informed oracle corpus."""
from __future__ import annotations
import sys
from pathlib import Path as _BootstrapPath
_ROOT = _BootstrapPath(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path: sys.path.insert(0, str(_ROOT))
import argparse, pickle
from pathlib import Path
from liquid_osahr02b.field import HazardBounds
from liquid_osahr02b.ran_experiment import RANDataConfig, generate_dataset

def main() -> None:
    p=argparse.ArgumentParser()
    p.add_argument('--output',type=Path,default=Path('artifacts/ran_dataset_rebuilt.pkl'))
    p.add_argument('--seed',type=int,default=26021802)
    p.add_argument('--horizon',type=float,default=3.0)
    p.add_argument('--period',type=float,default=0.3)
    p.add_argument('--train',type=int,default=14)
    p.add_argument('--val',type=int,default=5)
    p.add_argument('--test',type=int,default=5)
    a=p.parse_args()
    cfg=RANDataConfig(horizon=a.horizon,period=a.period,train=a.train,val=a.val,test=a.test,seed=a.seed)
    ds=generate_dataset(cfg,HazardBounds())
    a.output.parent.mkdir(parents=True,exist_ok=True)
    with a.output.open('wb') as f: pickle.dump(ds,f,protocol=pickle.HIGHEST_PROTOCOL)
    print({k:len(v) for k,v in ds.items()})
    print(a.output)
if __name__=='__main__': main()
