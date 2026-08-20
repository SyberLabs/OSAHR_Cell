from pathlib import Path
import sys,json
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from liquid_osahr.experiment import run_full
from liquid_osahr.data import DatasetSpec
from liquid_osahr.teacher import TeacherConfig
from liquid_osahr.training import TrainConfig
out=ROOT/'artifacts_smoke'
res=run_full(out,dataset_spec=DatasetSpec(train_traces=8,val_traces=4,test_traces=4,seed=101),teacher_cfg=TeacherConfig(horizon=12.0),train_cfg=TrainConfig(epochs=2,batch_size=4,patience=2,seed=202),hidden_size=8,bridge_pairs=1,bridge_replicates=1)
print(json.dumps({'ok':True,'summary':str(out/'results'/'summary.json')},indent=2))
