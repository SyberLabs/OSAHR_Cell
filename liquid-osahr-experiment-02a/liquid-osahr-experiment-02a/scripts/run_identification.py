from pathlib import Path
import json
import numpy as np

from liquid_osahr02a.data import DataConfig,generate_dataset,save_dataset,generate_oracle_trace,sample_scenario
from liquid_osahr02a.field import HazardBounds
from liquid_osahr02a.twin import TwinConfig
from liquid_osahr02a.training import TrainConfig,train_model,identification_metrics

ROOT=Path(__file__).resolve().parents[1]
ART=ROOT/'artifacts'; ART.mkdir(exist_ok=True)
bounds=HazardBounds()
cfg=DataConfig(horizon=12.0,train_traces=24,val_traces=6,test_traces=8,dataset_seed=260218)
print('generating ID dataset',flush=True)
ds=generate_dataset(cfg,bounds); save_dataset(ds,ART/'dataset_id.npz')
print({k:(len(v),sum(t.length for t in v)) for k,v in ds.items()},flush=True)
models={}; results={}; metrics={}
for name in ['cfc_closed','cfc_nojump','gru_closed']:
    print('training',name,flush=True)
    model,res=train_model(name,ds['train'],ds['val'],bounds,TrainConfig(epochs=32,batch_size=4,patience=7,seed=260218),checkpoint=ART/f'{name}.pt')
    models[name]=model; results[name]=res.__dict__; metrics[name]={'id':identification_metrics(model,ds['test'],bounds,model_name=name)}
    print(name,'best',res.best_epoch,res.best_val_loss,'test',metrics[name]['id']['normalized_mae'],flush=True)

rng=np.random.default_rng(99917)
for regime in ['high_mobility','high_stress']:
    traces=[]
    print('generating',regime,flush=True)
    for i in range(8):
        sc=sample_scenario(rng,regime=regime); policy='throughput' if i%2==0 else 'semantic'
        traces.append(generate_oracle_trace(f'{regime}-{i:02d}',sc,policy,root_seed=77000+i+1000*(regime=='high_stress'),cfg=TwinConfig(horizon=12.0),bounds=bounds))
    for name,model in models.items(): metrics[name][regime]=identification_metrics(model,traces,bounds,model_name=name)

with open(ART/'training_results.json','w') as f: json.dump(results,f,indent=2)
with open(ART/'identification_metrics.json','w') as f: json.dump(metrics,f,indent=2)
print('DONE',flush=True)
