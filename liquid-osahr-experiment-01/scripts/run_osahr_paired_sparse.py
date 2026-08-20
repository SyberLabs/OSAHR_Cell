from pathlib import Path
import csv,time,torch,numpy as np,sys
from dataclasses import asdict
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from liquid_osahr.teacher import LinkTeacher,TeacherConfig
from liquid_osahr.data import DatasetSpec,generate_bundle,sparsify_trace
from liquid_osahr.models import ModelConfig,build_model,ConstantHazardModel
from liquid_osahr.metrics import predict_trace
from liquid_osahr.osahr_bridge import run_twin,TwinConfig

torch.set_num_threads(2)
bundle=generate_bundle(LinkTeacher(TeacherConfig(horizon=36)),DatasetSpec(72,16,20,20260817))
# Pair-preserving sparsification of ID traces.
paired=[sparsify_trace(t,keep_probability=.45,seed=99173+i,trace_id=f'paired-sparse-{i:04d}') for i,t in enumerate(bundle.tests['id'])]
models={}
for label,file,kind in [('cfc','cfc.pt','cfc'),('gru_dt','gru_dt.pt','gru_dt'),('gru_param_matched','gru_param_matched.pt','gru_dt')]:
 ck=torch.load(ROOT/f'artifacts/checkpoints/{file}',weights_only=False);m=build_model(kind,ModelConfig(**ck['model_config']),seed=ck['train_config']['seed']);m.load_state_dict(ck['state_dict']);m.eval();models[label]=(kind,m)
models['constant']=('constant',ConstantHazardModel.fit(bundle.train))
fast=[t for t in paired if t.profile=='fast'][:6];robust=[t for t in paired if t.profile=='robust'][:6]
rows=[]; total=5*2*6*2; count=0; st=time.perf_counter();part=ROOT/'artifacts/results/osahr_twin_paired_sparse.partial.csv'
for scenario,(ft,rt) in enumerate(zip(fast,robust)):
 for label in ['oracle','cfc','gru_dt','gru_param_matched','constant']:
  if label=='oracle': fr,rr=ft.true_avg_rates,rt.true_avg_rates
  else:
   kind,m=models[label];fr=predict_trace(kind,m,ft,bundle.normalizer);rr=predict_trace(kind,m,rt,bundle.normalizer)
  fr=np.clip(fr,1e-6,30);rr=np.clip(rr,1e-6,30)
  for policy in ['throughput','semantic']:
   for rep in range(2):
    met=run_twin(hazard_model=label,regime='paired_sparse',policy=policy,scenario=scenario,replicate=rep,fast_times=ft.times,fast_rates=fr,robust_times=rt.times,robust_rates=rr,root_seed=80219,cfg=TwinConfig(),verify_incremental=False,seed_context='id')
    rows.append(asdict(met));count+=1
    with part.open('w',newline='') as f:
     w=csv.DictWriter(f,fieldnames=list(rows[0]));w.writeheader();w.writerows(rows)
    print(count,'/',total,scenario,label,policy,rep,round(met.goal_utility_ratio,3),'elapsed',round(time.perf_counter()-st,1),flush=True)
part.replace(ROOT/'artifacts/results/osahr_twin_paired_sparse.csv');print('COMPLETE',len(rows),'elapsed',time.perf_counter()-st,flush=True)
