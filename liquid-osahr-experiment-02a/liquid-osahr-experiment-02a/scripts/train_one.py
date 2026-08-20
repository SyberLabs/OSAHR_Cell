import sys,json
from pathlib import Path
from liquid_osahr02a.data import load_dataset
from liquid_osahr02a.field import HazardBounds
from liquid_osahr02a.training import TrainConfig,train_model,identification_metrics
root=Path(__file__).resolve().parents[1]; art=root/'artifacts'; name=sys.argv[1]; seed=int(sys.argv[2]) if len(sys.argv)>2 else 260218
ds=load_dataset(art/'dataset_id.npz'); bounds=HazardBounds()
model,res=train_model(name,ds['train'],ds['val'],bounds,TrainConfig(epochs=12,batch_size=5,patience=4,seed=seed),checkpoint=art/f'{name}_seed{seed}.pt')
met=identification_metrics(model,ds['test'],bounds,model_name=name)
with open(art/f'{name}_seed{seed}_train.json','w') as f: json.dump(res.__dict__,f,indent=2)
with open(art/f'{name}_seed{seed}_id.json','w') as f: json.dump(met,f,indent=2)
print(name,seed,'params',res.parameter_count,'best',res.best_epoch,res.best_val_loss,'ID nmae',met['normalized_mae'],'logrmse',met['log_rmse'])
