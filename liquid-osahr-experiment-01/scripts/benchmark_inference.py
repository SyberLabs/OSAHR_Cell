from pathlib import Path
import sys,time,torch,pandas as pd
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from liquid_osahr.teacher import LinkTeacher,TeacherConfig
from liquid_osahr.data import DatasetSpec,generate_bundle
from liquid_osahr.models import ModelConfig,build_model
from liquid_osahr.metrics import predict_trace

torch.set_num_threads(2)
bundle=generate_bundle(LinkTeacher(TeacherConfig(horizon=36)),DatasetSpec(72,16,20,20260817));traces=bundle.tests['id']
settings=[('cfc','cfc.pt','cfc'),('gru_dt','gru_dt.pt','gru_dt'),('lstm_dt','lstm_dt.pt','lstm_dt'),('mlp_dt','mlp_dt.pt','mlp_dt'),('gru_param_matched','gru_param_matched.pt','gru_dt'),('ltc_capped','ltc_capped.pt','ltc')]
rows=[]
for label,file,kind in settings:
 ck=torch.load(ROOT/f'artifacts/checkpoints/{file}',weights_only=False);m=build_model(kind,ModelConfig(**ck['model_config']),seed=ck['train_config']['seed']);m.load_state_dict(ck['state_dict']);m.eval()
 for t in traces[:2]: predict_trace(kind,m,t,bundle.normalizer)
 times=[]
 for _ in range(5):
  st=time.perf_counter()
  for tr in traces: predict_trace(kind,m,tr,bundle.normalizer)
  times.append(time.perf_counter()-st)
 med=sorted(times)[len(times)//2]
 intervals=sum(len(t.times) for t in traces)
 rows.append({'model':label,'traces':len(traces),'intervals':intervals,'median_seconds_all_traces':med,'microseconds_per_interval':med/intervals*1e6})
 print(rows[-1])
pd.DataFrame(rows).to_csv(ROOT/'artifacts/results/inference_benchmark.csv',index=False)
