from pathlib import Path
import sys,pandas as pd,numpy as np
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from liquid_osahr.teacher import LinkTeacher,TeacherConfig,MARKS
from liquid_osahr.data import DatasetSpec,generate_bundle
b=generate_bundle(LinkTeacher(TeacherConfig(horizon=36)),DatasetSpec(72,16,20,20260817))
sets={'train':b.train,'val':b.val,**b.tests}
rows=[]
for name,traces in sets.items():
    obs=np.zeros(3); exp=np.zeros(3)
    for t in traces:
        obs += t.event_counts.sum(axis=0)
        exp += (t.true_avg_rates*t.interval_dt[:,None]).sum(axis=0)
    for k,mark in enumerate(MARKS):
        rows.append({'split':name,'mark':mark,'traces':len(traces),'observed_events':float(obs[k]),'integrated_teacher_hazard':float(exp[k]),'observed_over_expected':float(obs[k]/exp[k]) if exp[k]>0 else np.nan})
pd.DataFrame(rows).to_csv(ROOT/'artifacts/results/teacher_validation.csv',index=False)
print(pd.DataFrame(rows).to_string(index=False))
