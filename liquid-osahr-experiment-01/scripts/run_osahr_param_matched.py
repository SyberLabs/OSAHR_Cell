from pathlib import Path
import csv,time,torch,numpy as np,sys
from dataclasses import asdict
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from liquid_osahr.teacher import LinkTeacher,TeacherConfig
from liquid_osahr.data import DatasetSpec,generate_bundle
from liquid_osahr.models import ModelConfig,build_model
from liquid_osahr.metrics import predict_trace
from liquid_osahr.osahr_bridge import run_twin,TwinConfig

torch.set_num_threads(2)
bundle=generate_bundle(LinkTeacher(TeacherConfig(horizon=36)),DatasetSpec(72,16,20,20260817))
ck=torch.load(ROOT/'artifacts/checkpoints/gru_param_matched.pt',weights_only=False)
model=build_model('gru_dt',ModelConfig(**ck['model_config']),seed=ck['train_config']['seed']); model.load_state_dict(ck['state_dict']); model.eval()
rows=[];total=2*6*2*2;count=0;st=time.perf_counter(); part=ROOT/'artifacts/results/osahr_twin_param_matched.partial.csv'
for regime in ['id','sparse']:
    fast=[t for t in bundle.tests[regime] if t.profile=='fast'][:6]; robust=[t for t in bundle.tests[regime] if t.profile=='robust'][:6]
    for scenario,(ft,rt) in enumerate(zip(fast,robust)):
        fr=np.clip(predict_trace('gru_dt',model,ft,bundle.normalizer),1e-6,30); rr=np.clip(predict_trace('gru_dt',model,rt,bundle.normalizer),1e-6,30)
        for policy in ['throughput','semantic']:
            for rep in range(2):
                m=run_twin(hazard_model='gru_param_matched',regime=regime,policy=policy,scenario=scenario,replicate=rep,fast_times=ft.times,fast_rates=fr,robust_times=rt.times,robust_rates=rr,root_seed=80219,cfg=TwinConfig())
                rows.append(asdict(m));count+=1
                with part.open('w',newline='') as f:
                    w=csv.DictWriter(f,fieldnames=list(rows[0]));w.writeheader();w.writerows(rows)
                print(count,'/',total,regime,scenario,policy,rep,round(m.goal_utility_ratio,3),'elapsed',round(time.perf_counter()-st,1),flush=True)
part.replace(ROOT/'artifacts/results/osahr_twin_param_matched.csv')
print('COMPLETE',len(rows),'elapsed',time.perf_counter()-st,flush=True)
