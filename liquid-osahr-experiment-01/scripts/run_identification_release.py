"""Reproduce the audited identification benchmark.

Matched tier: CfC / GRU-dt / LSTM-dt / MLP-dt, hidden width 32, full train split.
Secondary solver tier: dense LTC, hidden width 12, first 24 train traces, 10 epochs.
The LTC result is deliberately *not* treated as a matched-capacity leaderboard entry.
"""
from pathlib import Path
from dataclasses import asdict
import json
import sys
import torch
ROOT=Path(__file__).resolve().parents[1]; sys.path.insert(0,str(ROOT))
from liquid_osahr.teacher import LinkTeacher,TeacherConfig,FEATURE_NAMES,MARKS
from liquid_osahr.data import DatasetSpec,generate_bundle,save_bundle,sparsify_trace
from liquid_osahr.models import ModelConfig,ConstantHazardModel
from liquid_osahr.training import TrainConfig,train_model
from liquid_osahr.metrics import evaluate_model
from liquid_osahr.experiment import write_csv


def main():
    torch.set_num_threads(2)
    out=ROOT/'artifacts'
    bundle=generate_bundle(LinkTeacher(TeacherConfig(horizon=36)),DatasetSpec(72,16,20,20260817))
    save_bundle(bundle,out/'data/traces.npz')
    (out/'data/normalizer.json').write_text(json.dumps(bundle.normalizer.to_json(),indent=2))
    fitted={}; rows=[]
    base=ModelConfig(input_size=len(FEATURE_NAMES),marks=len(MARKS),hidden_size=32)
    for i,name in enumerate(['cfc','gru_dt','lstm_dt','mlp_dt']):
        cfg=TrainConfig(seed=1407+97*i)
        model,res=train_model(name,base,bundle.train,bundle.val,bundle.normalizer,cfg,checkpoint_path=out/f'checkpoints/{name}.pt')
        fitted[name]=model
        d=asdict(res); hist=d.pop('history'); d['comparison_tier']='equal_hidden_width'; rows.append(d)
        (out/'training_history').mkdir(exist_ok=True,parents=True)
        (out/f'training_history/{name}.json').write_text(json.dumps(hist,indent=2))
    # Parameter-budget sensitivity: GRU with approximately the same trainable
    # parameter count as the width-32 CfC (11,181 vs 11,235).
    pm_cfg=ModelConfig(input_size=len(FEATURE_NAMES),marks=len(MARKS),hidden_size=54)
    pm_train=TrainConfig(seed=1795)
    pm,res=train_model('gru_dt',pm_cfg,bundle.train,bundle.val,bundle.normalizer,pm_train,checkpoint_path=out/'checkpoints/gru_param_matched.pt')
    fitted['gru_param_matched']=pm
    d=asdict(res); d['model_name']='gru_param_matched'; hist=d.pop('history'); d['comparison_tier']='parameter_matched'; rows.append(d)
    (out/'training_history/gru_param_matched.json').write_text(json.dumps(hist,indent=2))

    ltc_cfg=ModelConfig(input_size=len(FEATURE_NAMES),marks=len(MARKS),hidden_size=12)
    ltc_train=TrainConfig(epochs=10,batch_size=6,patience=4,seed=1999)
    ltc,res=train_model('ltc',ltc_cfg,bundle.train[:24],bundle.val,bundle.normalizer,ltc_train,checkpoint_path=out/'checkpoints/ltc_capped.pt')
    fitted['ltc_capped']=ltc
    d=asdict(res); d['model_name']='ltc_capped'; d.pop('history'); d['comparison_tier']='resource_capped'; rows.append(d)
    const=ConstantHazardModel.fit(bundle.train); fitted['constant']=const
    rows.append({'model_name':'constant','best_epoch':0,'best_val_nll_interval':None,'train_seconds':0.0,'parameter_count':const.parameter_count(),'checkpoint':None,'comparison_tier':'analytic'})
    write_csv(out/'results/training_summary.csv',rows)
    metrics=[]
    eval_sets=dict(bundle.tests)
    eval_sets['paired_sparse']=[sparsify_trace(t,keep_probability=0.45,seed=99173+i,trace_id=f'paired-sparse-{i:04d}') for i,t in enumerate(bundle.tests['id'])]
    for regime,traces in eval_sets.items():
        for name,model in fitted.items():
            eval_name='ltc' if name=='ltc_capped' else ('gru_dt' if name=='gru_param_matched' else name)
            m=evaluate_model(eval_name,model,traces,bundle.normalizer,regime=regime)
            d=asdict(m); d['model']=name
            for k in ('mark_count_ratios','time_rescaling_ks','time_rescaling_p'): d[k]=json.dumps(d[k],sort_keys=True)
            metrics.append(d)
    write_csv(out/'results/identification_metrics.csv',metrics)

if __name__=='__main__': main()
