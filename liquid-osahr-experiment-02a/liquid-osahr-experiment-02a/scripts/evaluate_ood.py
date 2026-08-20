from pathlib import Path
import json, numpy as np
from liquid_osahr02a.data import sample_scenario,generate_oracle_trace
from liquid_osahr02a.field import HazardBounds
from liquid_osahr02a.twin import TwinConfig
from liquid_osahr02a.training import load_checkpoint,identification_metrics
root=Path(__file__).resolve().parents[1]; art=root/'artifacts'; bounds=HazardBounds(); seed=260218
models={name:load_checkpoint(art/f'{name}_seed{seed}.pt')[0] for name in ['cfc_closed','cfc_nojump','gru_closed']}
rng=np.random.default_rng(90902); out={name:{} for name in models}
for regime in ['high_mobility','high_stress']:
    traces=[]
    for i in range(6):
        sc=sample_scenario(rng,regime=regime); pol='throughput' if i%2==0 else 'semantic'
        traces.append(generate_oracle_trace(f'{regime}-{i}',sc,pol,root_seed=70700+i+1000*(regime=='high_stress'),cfg=TwinConfig(horizon=12.0),bounds=bounds))
    for name,model in models.items(): out[name][regime]=identification_metrics(model,traces,bounds,model_name=name)
with open(art/'identification_ood.json','w') as f: json.dump(out,f,indent=2)
for n in out:
    print(n,{r:(out[n][r]['normalized_mae'],out[n][r]['log_rmse']) for r in out[n]})
