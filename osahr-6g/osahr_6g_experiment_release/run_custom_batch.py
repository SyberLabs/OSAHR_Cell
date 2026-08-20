import argparse,csv,sys
from dataclasses import asdict
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parent))
from examples.semantic_6g_twin_experiment import run_one, ExperimentConfig
p=argparse.ArgumentParser(); p.add_argument('--policy'); p.add_argument('--start',type=int); p.add_argument('--count',type=int); p.add_argument('--out'); p.add_argument('--mode',choices=['no_outage','severe'],required=True); p.add_argument('--root-seed',type=int,default=0x6A602026); a=p.parse_args()
if a.mode=='no_outage': cfg=ExperimentConfig(fast_outage_start=100.0,fast_outage_end=101.0)
else: cfg=ExperimentConfig(fast_outage_start=15.0,fast_outage_end=42.0)
rows=[run_one(a.policy,i,a.root_seed,cfg) for i in range(a.start,a.start+a.count)]
path=Path(a.out); path.parent.mkdir(parents=True,exist_ok=True)
with path.open('w',newline='',encoding='utf-8') as f:
 w=csv.DictWriter(f,fieldnames=list(asdict(rows[0]).keys())); w.writeheader(); [w.writerow(asdict(r)) for r in rows]
print(a.mode,a.policy,'goal',sum(r.goal_utility_ratio for r in rows)/len(rows),'crit',sum(r.critical_success_rate for r in rows)/len(rows),'lat',sum(r.mean_latency for r in rows)/len(rows))
