import sys, json
from pathlib import Path
import numpy as np
from liquid_osahr02a.data import sample_scenario,generate_oracle_trace,save_dataset
from liquid_osahr02a.field import HazardBounds
from liquid_osahr02a.twin import TwinConfig
start=int(sys.argv[1]); count=int(sys.argv[2]); total=32; seed=260218
rng=np.random.default_rng(seed)
scenarios=[sample_scenario(rng,regime='id') for _ in range(total)]
tr=[]
for i in range(start,min(start+count,total)):
    pol='throughput' if i%2==0 else 'semantic'
    tr.append(generate_oracle_trace(f'id-{i:03d}',scenarios[i],pol,root_seed=seed+1009*i,cfg=TwinConfig(horizon=12.0),bounds=HazardBounds(),verify_incremental=False))
path=Path(__file__).resolve().parents[1]/'artifacts'/f'dataset_chunk_{start:02d}.npz'
path.parent.mkdir(exist_ok=True)
save_dataset({'all':tr},path)
print(path,[(x.trace_id,x.length) for x in tr])
