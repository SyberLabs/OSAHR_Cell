from pathlib import Path
import argparse, json, sys
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from liquid_osahr.experiment import run_full
from liquid_osahr.data import DatasetSpec
from liquid_osahr.teacher import TeacherConfig
from liquid_osahr.training import TrainConfig

p=argparse.ArgumentParser()
p.add_argument('--out',type=Path,default=ROOT/'artifacts')
p.add_argument('--epochs',type=int,default=45)
p.add_argument('--train-traces',type=int,default=72)
p.add_argument('--val-traces',type=int,default=16)
p.add_argument('--test-traces',type=int,default=20)
p.add_argument('--bridge-pairs',type=int,default=6)
p.add_argument('--bridge-replicates',type=int,default=2)
p.add_argument('--hidden-size',type=int,default=32)
a=p.parse_args()
res=run_full(a.out,dataset_spec=DatasetSpec(a.train_traces,a.val_traces,a.test_traces),teacher_cfg=TeacherConfig(),train_cfg=TrainConfig(epochs=a.epochs),hidden_size=a.hidden_size,bridge_pairs=a.bridge_pairs,bridge_replicates=a.bridge_replicates)
print(json.dumps({'summary':str(a.out/'results'/'summary.json'),'models':len(set(r['model'] for r in res['identification_metrics']))},indent=2))
