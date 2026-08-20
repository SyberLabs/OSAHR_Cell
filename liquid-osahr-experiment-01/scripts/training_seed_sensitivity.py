from pathlib import Path
from dataclasses import asdict
import json,sys,torch,pandas as pd
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from liquid_osahr.teacher import LinkTeacher,TeacherConfig,FEATURE_NAMES,MARKS
from liquid_osahr.data import DatasetSpec,generate_bundle,sparsify_trace
from liquid_osahr.models import ModelConfig
from liquid_osahr.training import TrainConfig,train_model
from liquid_osahr.metrics import evaluate_model

torch.set_num_threads(2)
bundle=generate_bundle(LinkTeacher(TeacherConfig(horizon=36)),DatasetSpec(72,16,20,20260817))
paired=[sparsify_trace(t,keep_probability=.45,seed=99173+i) for i,t in enumerate(bundle.tests['id'])]
rows=[]
for label,kind,width,seeds in [('cfc','cfc',32,[1407,2407,3407]),('gru_param_matched','gru_dt',54,[1795,2795,3795])]:
    for seed in seeds:
        # Reuse audited checkpoint for the already-completed seed; train only the additional seeds.
        if (label=='cfc' and seed==1407) or (label=='gru_param_matched' and seed==1795):
            file='cfc.pt' if label=='cfc' else 'gru_param_matched.pt'; ck=torch.load(ROOT/f'artifacts/checkpoints/{file}',weights_only=False)
            from liquid_osahr.models import build_model
            m=build_model(kind,ModelConfig(**ck['model_config']),seed=ck['train_config']['seed']);m.load_state_dict(ck['state_dict']);m.eval();best=ck['best_val_nll_interval'];epoch=ck['best_epoch']
        else:
            m,res=train_model(kind,ModelConfig(input_size=len(FEATURE_NAMES),marks=len(MARKS),hidden_size=width),bundle.train,bundle.val,bundle.normalizer,TrainConfig(seed=seed),checkpoint_path=None)
            best=res.best_val_nll_interval;epoch=res.best_epoch
        for regime,traces in [('id',bundle.tests['id']),('paired_sparse',paired),('high_mobility',bundle.tests['high_mobility']),('high_congestion',bundle.tests['high_congestion'])]:
            e=evaluate_model(kind,m,traces,bundle.normalizer,regime=regime)
            rows.append({'model':label,'train_seed':seed,'best_epoch':epoch,'best_val_nll_interval':best,'regime':regime,'nll_per_interval':e.nll_per_interval,'rate_rmse':e.rate_rmse,'rate_spearman':e.rate_spearman})
            print(label,seed,regime,round(e.nll_per_interval,6),flush=True)
pd.DataFrame(rows).to_csv(ROOT/'artifacts/results/training_seed_sensitivity.csv',index=False)
