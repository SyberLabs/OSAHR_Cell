"""Trajectory generation and tensor datasets for Experiment 02B."""
from __future__ import annotations

from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Iterable
import json
import math

import numpy as np
import torch
from torch.utils.data import Dataset, DataLoader

from osahr import RuntimeConfig, SchedulerKind  # type: ignore
from osahr.events import StepStatus  # type: ignore
from osahr.rng import derive_seed  # type: ignore

from .field import (
    EVENTS, EVENT_INDEX, HazardBounds, OracleField, PersistentIndex, Scenario,
    applicable_head_mask, graph_view,
)
from .hybrid import HybridLiquidRuntime
from .twin import TwinConfig, build_model


@dataclass
class HybridTrace:
    trace_id: str
    scenario: Scenario
    policy: str
    times: np.ndarray              # (L,)
    structural: np.ndarray         # (L,N,F)
    adjacency: np.ndarray          # (L,R,N,N)
    event_code: np.ndarray         # (L,)
    affected: np.ndarray           # (L,N)
    target_rates: np.ndarray       # (L,N,K)
    rate_mask: np.ndarray          # (L,N,K)
    oracle_state: np.ndarray       # (L,N,D)
    rule_names: tuple[str, ...]
    outcome: dict[str,float]

    @property
    def length(self)->int: return int(len(self.times))


@dataclass(frozen=True)
class DataConfig:
    horizon: float = 18.0
    train_traces: int = 28
    val_traces: int = 6
    test_traces: int = 8
    dataset_seed: int = 260218


def sample_scenario(rng:np.random.Generator, *, regime:str="id")->Scenario:
    if regime=="id":
        return Scenario(
            mobility=float(rng.uniform(.72,1.28)), stress=float(rng.uniform(.72,1.28)),
            channel=float(rng.uniform(.82,1.18)), demand=float(rng.uniform(.78,1.22)),
        )
    if regime=="high_mobility":
        return Scenario(mobility=float(rng.uniform(1.55,2.05)),stress=float(rng.uniform(.8,1.3)),channel=float(rng.uniform(.82,1.18)),demand=float(rng.uniform(.8,1.22)))
    if regime=="high_stress":
        return Scenario(mobility=float(rng.uniform(.8,1.3)),stress=float(rng.uniform(1.55,2.05)),channel=float(rng.uniform(.75,1.1)),demand=float(rng.uniform(1.05,1.45)))
    raise ValueError(regime)


def _metrics(runtime:HybridLiquidRuntime)->dict[str,float]:
    z=runtime.memory
    generated=max(float(z["generated_utility"]),1e-12)
    crit=max(int(z["generated_critical"]),1)
    delivered=max(int(z["delivered"]),1)
    return {
        "goal_utility_ratio":float(z["timely_semantic_utility"])/generated,
        "critical_success_rate":float(z["timely_critical"])/crit,
        "mean_latency":float(z["latency_sum"])/delivered,
        "energy":float(z["energy"]),"generated":float(z["generated"]),"delivered":float(z["delivered"]),
        "outages":float(z["outages"]),"recoveries":float(z["recoveries"]),"handovers":float(z["handovers"]),"reroutes":float(z["reroutes"]),
    }


def _capture(runtime:HybridLiquidRuntime,index:PersistentIndex,scenario:Scenario,rule_name:str,affected:np.ndarray)->tuple:
    view=graph_view(runtime.graph,index,scenario)
    rates=runtime.field.base_rates_at(runtime.time,runtime.graph).astype(np.float32)
    mask=applicable_head_mask(runtime.graph,index).astype(np.float32)
    state=runtime.field.state_at(runtime.time,runtime.graph).astype(np.float32)
    return (float(runtime.time),view.structural.astype(np.float32),view.adjacency.astype(np.float32),EVENT_INDEX.get(rule_name,0),affected.astype(np.float32),rates,mask,state,rule_name)


def generate_oracle_trace(
    trace_id:str,scenario:Scenario,policy:str,*,root_seed:int,cfg:TwinConfig|None=None,bounds:HazardBounds|None=None,verify_incremental:bool=False,
)->HybridTrace:
    cfg=cfg or TwinConfig(); bounds=bounds or HazardBounds()
    # Override the experiment horizon without altering other task parameters.
    model,index=build_model(policy,scenario,cfg,bounds)
    field=OracleField(index,scenario,bounds,seed=derive_seed(root_seed,f"oracle-field:{trace_id}"),initial_noise=0.0)
    runtime=HybridLiquidRuntime(model,field=field,root_seed=derive_seed(root_seed,f"oracle-runtime:{trace_id}"),config=RuntimeConfig(
        scheduler=SchedulerKind.THINNING,matcher_backend="incremental",incremental_verify=verify_incremental,
        max_simulation_time=cfg.horizon,thinning_window=.55,max_events=120_000,max_thinning_windows_per_plan=200_000,
    ))
    rows=[_capture(runtime,index,scenario,"init",np.zeros(index.n,dtype=np.float32))]
    while runtime.time < cfg.horizon-1e-12:
        nxt=runtime.peek_next_event_time()
        if nxt is None or nxt > cfg.horizon:
            runtime.run_until_time(cfg.horizon); break
        result=runtime.step()
        if result.event is not None:
            jump=result.event.cause.get("liquid_jump",{})
            affected=np.asarray(jump.get("affected",np.zeros(index.n)),dtype=np.float32)
            rule=str(result.event.cause.get("rule_id","init"))
            rows.append(_capture(runtime,index,scenario,rule,affected))
        if result.status is StepStatus.ABSORBED:
            break
    times=np.asarray([r[0] for r in rows],dtype=np.float32)
    if np.any(np.diff(times)<-1e-8): raise RuntimeError("nonmonotone trace")
    return HybridTrace(
        trace_id=trace_id,scenario=scenario,policy=policy,times=times,
        structural=np.stack([r[1] for r in rows]),adjacency=np.stack([r[2] for r in rows]),event_code=np.asarray([r[3] for r in rows],dtype=np.int64),
        affected=np.stack([r[4] for r in rows]),target_rates=np.stack([r[5] for r in rows]),rate_mask=np.stack([r[6] for r in rows]),oracle_state=np.stack([r[7] for r in rows]),
        rule_names=tuple(r[8] for r in rows),outcome=_metrics(runtime),
    )


def generate_dataset(cfg:DataConfig,bounds:HazardBounds|None=None)->dict[str,list[HybridTrace]]:
    bounds=bounds or HazardBounds(); rng=np.random.default_rng(cfg.dataset_seed)
    total=cfg.train_traces+cfg.val_traces+cfg.test_traces
    traces=[]
    for i in range(total):
        scenario=sample_scenario(rng,regime="id")
        policy="throughput" if i%2==0 else "semantic"
        twin_cfg=TwinConfig(horizon=cfg.horizon)
        traces.append(generate_oracle_trace(f"id-{i:03d}",scenario,policy,root_seed=cfg.dataset_seed+1009*i,cfg=twin_cfg,bounds=bounds,verify_incremental=False))
    return {"train":traces[:cfg.train_traces],"val":traces[cfg.train_traces:cfg.train_traces+cfg.val_traces],"test":traces[-cfg.test_traces:]}


class TraceDataset(Dataset):
    def __init__(self,traces:list[HybridTrace]): self.traces=traces
    def __len__(self): return len(self.traces)
    def __getitem__(self,i): return self.traces[i]


def collate_traces(traces:list[HybridTrace])->dict[str,torch.Tensor]:
    B=len(traces); L=max(t.length for t in traces); N=traces[0].structural.shape[1]; F=traces[0].structural.shape[2]; R=traces[0].adjacency.shape[1]; K=traces[0].target_rates.shape[2]
    structural=torch.zeros(B,L,N,F); adjacency=torch.zeros(B,L,R,N,N); times=torch.zeros(B,L); event_code=torch.zeros(B,L,dtype=torch.long); affected=torch.zeros(B,L,N); target=torch.zeros(B,L,N,K); rate_mask=torch.zeros(B,L,N,K); frame_mask=torch.zeros(B,L,dtype=torch.bool)
    for b,t in enumerate(traces):
        n=t.length; structural[b,:n]=torch.from_numpy(t.structural); adjacency[b,:n]=torch.from_numpy(t.adjacency); times[b,:n]=torch.from_numpy(t.times); event_code[b,:n]=torch.from_numpy(t.event_code); affected[b,:n]=torch.from_numpy(t.affected); target[b,:n]=torch.from_numpy(t.target_rates); rate_mask[b,:n]=torch.from_numpy(t.rate_mask); frame_mask[b,:n]=True
        if n<L:
            # repeat terminal structural state to avoid pathological padded inputs
            structural[b,n:]=structural[b,n-1]; adjacency[b,n:]=adjacency[b,n-1]; times[b,n:]=times[b,n-1]
    return {"structural":structural,"adjacency":adjacency,"times":times,"event_code":event_code,"affected":affected,"target_rates":target,"rate_mask":rate_mask,"frame_mask":frame_mask}


def make_loader(traces:list[HybridTrace],*,batch_size:int,shuffle:bool,seed:int)->DataLoader:
    gen=torch.Generator().manual_seed(seed)
    return DataLoader(TraceDataset(traces),batch_size=batch_size,shuffle=shuffle,collate_fn=collate_traces,generator=gen,num_workers=0)


def save_dataset(dataset:dict[str,list[HybridTrace]],path:Path)->None:
    path.parent.mkdir(parents=True,exist_ok=True)
    payload={}
    meta={}
    counter=0
    for split,traces in dataset.items():
        meta[split]=[]
        for t in traces:
            prefix=f"t{counter}"; counter+=1
            for name in ("times","structural","adjacency","event_code","affected","target_rates","rate_mask","oracle_state"):
                payload[f"{prefix}_{name}"]=getattr(t,name)
            meta[split].append({"prefix":prefix,"trace_id":t.trace_id,"scenario":asdict(t.scenario),"policy":t.policy,"rule_names":list(t.rule_names),"outcome":t.outcome})
    payload["__meta_json__"]=np.asarray(json.dumps(meta))
    np.savez_compressed(path,**payload)


def load_dataset(path:Path)->dict[str,list[HybridTrace]]:
    data=np.load(path,allow_pickle=False); meta=json.loads(str(data["__meta_json__"]))
    out={}
    for split,items in meta.items():
        out[split]=[]
        for item in items:
            p=item["prefix"]
            out[split].append(HybridTrace(trace_id=item["trace_id"],scenario=Scenario(**item["scenario"]),policy=item["policy"],times=data[f"{p}_times"],structural=data[f"{p}_structural"],adjacency=data[f"{p}_adjacency"],event_code=data[f"{p}_event_code"],affected=data[f"{p}_affected"],target_rates=data[f"{p}_target_rates"],rate_mask=data[f"{p}_rate_mask"],oracle_state=data[f"{p}_oracle_state"],rule_names=tuple(item["rule_names"]),outcome=item["outcome"]))
    return out
