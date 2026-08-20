from pathlib import Path
from dataclasses import asdict
import json,sys,torch,pandas as pd
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from liquid_osahr.teacher import LinkTeacher,TeacherConfig
from liquid_osahr.data import DatasetSpec,generate_bundle,sparsify_trace
from liquid_osahr.models import ModelConfig,build_model,ConstantHazardModel
from liquid_osahr.metrics import evaluate_model

torch.set_num_threads(2)
bundle=generate_bundle(LinkTeacher(TeacherConfig(horizon=36)),DatasetSpec(72,16,20,20260817))
paired=[sparsify_trace(t,keep_probability=0.45,seed=99173+i,trace_id=f'paired-sparse-{i:04d}') for i,t in enumerate(bundle.tests['id'])]
models={}
for label,file,kind in [
 ('cfc','cfc.pt','cfc'),('gru_dt','gru_dt.pt','gru_dt'),('lstm_dt','lstm_dt.pt','lstm_dt'),('mlp_dt','mlp_dt.pt','mlp_dt'),
 ('ltc_capped','ltc_capped.pt','ltc'),('gru_param_matched','gru_param_matched.pt','gru_dt')]:
 ck=torch.load(ROOT/f'artifacts/checkpoints/{file}',weights_only=False)
 m=build_model(kind,ModelConfig(**ck['model_config']),seed=ck['train_config']['seed']);m.load_state_dict(ck['state_dict']);m.eval();models[label]=(kind,m)
models['constant']=('constant',ConstantHazardModel.fit(bundle.train))
rows=[]
for label,(kind,m) in models.items():
 d=asdict(evaluate_model(kind,m,paired,bundle.normalizer,regime='paired_sparse'))
 d['model']=label
 for k in ['mark_count_ratios','time_rescaling_ks','time_rescaling_p']: d[k]=json.dumps(d[k],sort_keys=True)
 rows.append(d)
 print(label,d['nll_per_interval'],d['rate_rmse'])
p='artifacts/results/identification_metrics.csv';df=pd.read_csv(p);df=df[df.regime!='paired_sparse'];df=pd.concat([df,pd.DataFrame(rows)],ignore_index=True);df.to_csv(p,index=False)
