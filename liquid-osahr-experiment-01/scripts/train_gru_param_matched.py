from pathlib import Path
from dataclasses import asdict
import json,sys,torch
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from liquid_osahr.teacher import LinkTeacher,TeacherConfig,FEATURE_NAMES,MARKS
from liquid_osahr.data import DatasetSpec,generate_bundle
from liquid_osahr.models import ModelConfig
from liquid_osahr.training import TrainConfig,train_model
from liquid_osahr.metrics import evaluate_model

torch.set_num_threads(2)
bundle=generate_bundle(LinkTeacher(TeacherConfig(horizon=36)),DatasetSpec(72,16,20,20260817))
cfg=ModelConfig(input_size=len(FEATURE_NAMES),marks=len(MARKS),hidden_size=54)
tcfg=TrainConfig(seed=1795)
model,res=train_model('gru_dt',cfg,bundle.train,bundle.val,bundle.normalizer,tcfg,checkpoint_path=ROOT/'artifacts/checkpoints/gru_param_matched.pt')
(ROOT/'artifacts/training_history/gru_param_matched.json').write_text(json.dumps(res.history,indent=2))
print('PARAMS',res.parameter_count,'BEST',res.best_epoch,res.best_val_nll_interval,'SECONDS',res.train_seconds,flush=True)
rows=[]
for regime,traces in bundle.tests.items():
    m=evaluate_model('gru_dt',model,traces,bundle.normalizer,regime=regime)
    d=asdict(m);d['model']='gru_param_matched';rows.append(d)
    print(regime,d['nll_per_interval'],d['rate_rmse'],flush=True)
(ROOT/'artifacts/results/gru_param_matched_metrics.json').write_text(json.dumps(rows,indent=2))
