from pathlib import Path
import csv,time,torch,numpy as np,sys
from dataclasses import asdict
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from liquid_osahr.teacher import LinkTeacher,TeacherConfig
from liquid_osahr.data import DatasetSpec,generate_bundle
from liquid_osahr.models import ModelConfig,build_model,ConstantHazardModel
from liquid_osahr.metrics import predict_trace
from liquid_osahr.osahr_bridge import run_twin,TwinConfig

torch.set_num_threads(2)
teacher=LinkTeacher(TeacherConfig(horizon=36)); bundle=generate_bundle(teacher,DatasetSpec(72,16,20,20260817))
fitted={}
for name in ['cfc','gru_dt']:
    ck=torch.load(ROOT/f'artifacts/checkpoints/{name}.pt',weights_only=False)
    m=build_model(name,ModelConfig(**ck['model_config']),seed=ck['train_config']['seed'])
    m.load_state_dict(ck['state_dict']);m.eval();fitted[name]=m
fitted['constant']=ConstantHazardModel.fit(bundle.train)
models=['oracle','cfc','gru_dt','constant']; policies=['throughput','semantic']; regimes=['id','sparse']; scenario_ids=range(3,6); reps=2
rows=[];total=len(models)*len(policies)*len(regimes)*len(scenario_ids)*reps;count=0;st=time.perf_counter()
checkpoint=ROOT/'artifacts/results/osahr_twin_extension.partial.csv';checkpoint.parent.mkdir(parents=True,exist_ok=True)
for regime in regimes:
    fast=[t for t in bundle.tests[regime] if t.profile=='fast']
    robust=[t for t in bundle.tests[regime] if t.profile=='robust']
    for scenario in scenario_ids:
        ft,rt=fast[scenario],robust[scenario]
        for mn in models:
            if mn=='oracle': fr=ft.true_avg_rates; rr=rt.true_avg_rates
            else:
                fr=predict_trace(mn,fitted[mn],ft,bundle.normalizer)
                rr=predict_trace(mn,fitted[mn],rt,bundle.normalizer)
            fr=np.clip(fr,1e-6,30); rr=np.clip(rr,1e-6,30)
            for policy in policies:
                for rep in range(reps):
                    m=run_twin(hazard_model=mn,regime=regime,policy=policy,scenario=scenario,replicate=rep,
                        fast_times=ft.times,fast_rates=fr,robust_times=rt.times,robust_rates=rr,
                        root_seed=80219,cfg=TwinConfig(),verify_incremental=False)
                    rows.append(asdict(m)); count+=1
                    with checkpoint.open('w',newline='') as f:
                        w=csv.DictWriter(f,fieldnames=list(rows[0]));w.writeheader();w.writerows(rows)
                    print(count,'/',total,regime,scenario,mn,policy,'rep',rep,'goal',round(m.goal_utility_ratio,3),'elapsed',round(time.perf_counter()-st,1),flush=True)
out=ROOT/'artifacts/results/osahr_twin_extension.csv';checkpoint.replace(out)
print('COMPLETE',len(rows),'elapsed',time.perf_counter()-st,flush=True)
