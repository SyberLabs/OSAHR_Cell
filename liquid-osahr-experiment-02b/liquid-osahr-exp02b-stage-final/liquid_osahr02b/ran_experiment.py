"""Training, intervention calibration, and counterfactual evaluation for 02B."""
from __future__ import annotations
from dataclasses import dataclass, asdict
from pathlib import Path
import copy, json, math, time
import numpy as np
import pandas as pd
import torch

from .field import Scenario,HazardBounds,graph_view,applicable_head_mask,parameter_count
from .ran import RANConfig,RANOracleField,RANMechanisticField,ResidualGraphCfC,ResidualRANField,RAN_STRUCT_DIM
from .hybrid import HybridLiquidRuntime
from .twin import TwinConfig,build_model

from osahr import RuntimeConfig,SchedulerKind
from osahr.rng import derive_seed

@dataclass
class RANTrace:
    trace_id:str; scenario:Scenario; policy:str; times:np.ndarray; x:np.ndarray; adjacency:np.ndarray; mechanism:np.ndarray; target:np.ndarray; mask:np.ndarray

@dataclass(frozen=True)
class RANDataConfig:
    horizon:float=10.0; period:float=.25; train:int=18; val:int=6; test:int=8; seed:int=26021802

@dataclass(frozen=True)
class ResidualTrainConfig:
    epochs:int=55; lr:float=2e-3; weight_decay:float=1e-5; patience:int=10; hidden_size:int=20; seed:int=260218


def sample_scenario(rng,regime="id"):
    if regime=="id": return Scenario(float(rng.uniform(.75,1.25)),float(rng.uniform(.75,1.25)),float(rng.uniform(.88,1.12)),float(rng.uniform(.82,1.18)))
    if regime=="high_mobility": return Scenario(float(rng.uniform(1.55,2.0)),float(rng.uniform(.8,1.25)),float(rng.uniform(.85,1.12)),float(rng.uniform(.85,1.2)))
    if regime=="high_stress": return Scenario(float(rng.uniform(.8,1.25)),float(rng.uniform(1.55,2.0)),float(rng.uniform(.78,1.05)),float(rng.uniform(1.12,1.45)))
    if regime=="weak_channel": return Scenario(float(rng.uniform(.85,1.3)),float(rng.uniform(.85,1.3)),float(rng.uniform(.62,.82)),float(rng.uniform(.9,1.25)))
    raise ValueError(regime)


def _runtime(policy,scenario,bounds,field,seed,horizon,verify=False):
    model,index=build_model(policy,scenario,TwinConfig(horizon=horizon),bounds)
    rt=HybridLiquidRuntime(model,field=field(index,model.graph),root_seed=seed,config=RuntimeConfig(
        scheduler=SchedulerKind.THINNING,matcher_backend="incremental",incremental_verify=verify,max_simulation_time=horizon,
        thinning_window=.35,max_events=100000,max_thinning_windows_per_plan=250000))
    return rt,index


def generate_trace(trace_id,scenario,policy,*,root_seed,horizon=10.,period=.25,bounds=None,verify=False):
    bounds=bounds or HazardBounds(); model,index=build_model(policy,scenario,TwinConfig(horizon=horizon),bounds)
    phys_seed=derive_seed(root_seed,f"physics:{trace_id}")
    field=RANOracleField(index,scenario,bounds,seed=phys_seed)
    rt=HybridLiquidRuntime(model,field=field,root_seed=derive_seed(root_seed,f"runtime:{trace_id}"),config=RuntimeConfig(
        scheduler=SchedulerKind.THINNING,matcher_backend="incremental",incremental_verify=verify,max_simulation_time=horizon,
        thinning_window=.35,max_events=100000,max_thinning_windows_per_plan=250000))
    times=np.arange(0,horizon+1e-9,period,dtype=float); xs=[]; As=[]; ms=[]; ys=[]; masks=[]
    for t in times:
        rt.run_until_time(float(t))
        xs.append(field.physics.telemetry(float(t),rt.graph)); As.append(graph_view(rt.graph,index,scenario).adjacency)
        ms.append(field.physics.mechanistic_rates(float(t),rt.graph,bounds)); ys.append(field.base_rates_at(float(t),rt.graph)); masks.append(applicable_head_mask(rt.graph,index))
    return RANTrace(trace_id,scenario,policy,times.astype(np.float32),np.stack(xs).astype(np.float32),np.stack(As).astype(np.float32),np.stack(ms).astype(np.float32),np.stack(ys).astype(np.float32),np.stack(masks).astype(np.float32))


def generate_dataset(cfg=RANDataConfig(),bounds=None):
    bounds=bounds or HazardBounds(); rng=np.random.default_rng(cfg.seed); traces=[]
    total=cfg.train+cfg.val+cfg.test
    for i in range(total):
        sc=sample_scenario(rng,"id"); pol="throughput" if i%2==0 else "semantic"
        traces.append(generate_trace(f"ran-{i:03d}",sc,pol,root_seed=cfg.seed+1009*i,horizon=cfg.horizon,period=cfg.period,bounds=bounds,verify=False))
    return {"train":traces[:cfg.train],"val":traces[cfg.train:cfg.train+cfg.val],"test":traces[-cfg.test:]}


def _rollout(model,tr:RANTrace,bounds:HazardBounds,trust=1.0,device="cpu"):
    x=torch.from_numpy(tr.x).to(device); A=torch.from_numpy(tr.adjacency).to(device); mech=torch.from_numpy(tr.mechanism).to(device)
    b=torch.tensor(bounds.vector(),dtype=x.dtype,device=device); h=model.initial_state(x[0:1])[0]
    outs=[]; prev=float(tr.times[0]);
    for j,tv in enumerate(tr.times):
        if j>0:
            dt=torch.tensor([[float(tv-prev)]],dtype=x.dtype,device=device); h=model.flow(h.unsqueeze(0),x[j:j+1],A[j:j+1],dt)[0]
        r=model.rates(h.unsqueeze(0),x[j:j+1],mech[j:j+1],b,bounds.floor,trust)[0]; outs.append(r); prev=float(tv)
    return torch.stack(outs)


def _loss_for_trace(model,tr,bounds,trust=1.0,device="cpu"):
    pred=_rollout(model,tr,bounds,trust,device); y=torch.from_numpy(tr.target).to(device); mask=torch.from_numpy(tr.mask).to(device)
    scale=torch.tensor(bounds.vector(),dtype=pred.dtype,device=device).view(1,1,-1)
    # Robust log-intensity + normalized absolute term. Mechanism anchoring makes
    # the target well-conditioned even for rare failure/recovery channels.
    logerr=(torch.log(pred+1e-5)-torch.log(y+1e-5))**2
    nabs=torch.abs(pred-y)/scale
    return ((.65*logerr+.35*nabs)*mask).sum()/mask.sum().clamp_min(1.)


def eval_hazard(model,traces,bounds,trust=1.0,device="cpu"):
    rows=[]
    with torch.inference_mode():
        for tr in traces:
            p=_rollout(model,tr,bounds,trust,device).cpu().numpy(); m=tr.mask.astype(bool); y=tr.target
            scale=np.broadcast_to(bounds.vector(),y.shape)
            rows.append({"trace_id":tr.trace_id,"nmae":float(np.mean(np.abs(p[m]-y[m])/scale[m])),"log_rmse":float(np.sqrt(np.mean((np.log(p[m]+1e-5)-np.log(y[m]+1e-5))**2)))})
    return {"nmae":float(np.mean([r["nmae"] for r in rows])),"log_rmse":float(np.mean([r["log_rmse"] for r in rows])),"per_trace":rows}


def train_residual(train,val,bounds=None,cfg=ResidualTrainConfig(),checkpoint=None,device="cpu"):
    bounds=bounds or HazardBounds(); torch.manual_seed(cfg.seed); np.random.seed(cfg.seed)
    model=ResidualGraphCfC(RAN_STRUCT_DIM,cfg.hidden_size).to(device); opt=torch.optim.AdamW(model.parameters(),lr=cfg.lr,weight_decay=cfg.weight_decay)
    best=None; bestv=float("inf"); left=cfg.patience; hist=[]; start=time.perf_counter()
    rng=np.random.default_rng(cfg.seed)
    for ep in range(cfg.epochs):
        model.train(); order=rng.permutation(len(train)); losses=[]
        for i in order:
            opt.zero_grad(); loss=_loss_for_trace(model,train[int(i)],bounds,1.0,device); loss.backward(); torch.nn.utils.clip_grad_norm_(model.parameters(),3.0); opt.step(); losses.append(float(loss.detach()))
        model.eval();
        with torch.inference_mode(): v=float(np.mean([float(_loss_for_trace(model,tr,bounds,1.0,device)) for tr in val]))
        hist.append({"epoch":ep,"train":float(np.mean(losses)),"val":v})
        if v<bestv-1e-5: bestv=v; best=copy.deepcopy(model.state_dict()); left=cfg.patience
        else:
            left-=1
            if left<=0: break
    model.load_state_dict(best); model.eval(); elapsed=time.perf_counter()-start
    payload={"state_dict":best,"config":asdict(cfg),"best_val":bestv,"history":hist,"parameter_count":parameter_count(model),"elapsed":elapsed}
    if checkpoint:
        Path(checkpoint).parent.mkdir(parents=True,exist_ok=True); torch.save(payload,checkpoint)
    return model,payload


def _metrics(rt):
    z=rt.memory; return {"goal_utility_ratio":float(z["timely_semantic_utility"])/max(float(z["generated_utility"]),1e-12),"critical_success_rate":float(z["timely_critical"])/max(int(z["generated_critical"]),1),"mean_latency":float(z["latency_sum"])/max(int(z["delivered"]),1),"energy":float(z["energy"]),"events":int(rt.event_index),"outages":int(z["outages"]),"handovers":int(z["handovers"]),"reroutes":int(z["reroutes"])}


def run_counterfactual(kind,scenario,policy,*,scenario_id,replicate,root_seed,model=None,trust=1.0,horizon=9.,bounds=None,verify=False):
    bounds=bounds or HazardBounds(); tm,index=build_model(policy,scenario,TwinConfig(horizon=horizon),bounds)
    # Crucially the physical seed is model/policy independent within scenario.
    phys_seed=derive_seed(root_seed,f"02b-physics:{scenario_id}:{replicate}"); run_seed=derive_seed(root_seed,f"02b-run:{scenario_id}:{replicate}")
    if kind=="oracle": field=RANOracleField(index,scenario,bounds,seed=phys_seed)
    elif kind=="mechanistic": field=RANMechanisticField(index,scenario,bounds,seed=phys_seed)
    else: field=ResidualRANField(model,index,scenario,bounds,seed=phys_seed,trust=trust,name=kind)
    rt=HybridLiquidRuntime(tm,field=field,root_seed=run_seed,config=RuntimeConfig(scheduler=SchedulerKind.THINNING,matcher_backend="incremental",incremental_verify=verify,max_simulation_time=horizon,thinning_window=.35,max_events=100000,max_thinning_windows_per_plan=250000))
    rt.run_until_time(horizon); d=_metrics(rt); d.update({"model":kind,"trust":float(trust),"policy":policy,"scenario":scenario_id,"replicate":replicate,"seed":run_seed,"final_hash":rt.state_hash,"thinning_rejections":int(rt.thinning_audit.rejected_candidates)}); return d


def paired_scenarios(seed,n,regime):
    rng=np.random.default_rng(seed); return [sample_scenario(rng,regime) for _ in range(n)]


def trust_predictive_grid(model,val,bounds=None,grid=(0,.25,.5,.75,1.0)):
    bounds=bounds or HazardBounds(); rows=[]
    for a in grid:
        m=eval_hazard(model,val,bounds,a); rows.append({"trust":float(a),"nmae":m["nmae"],"log_rmse":m["log_rmse"]})
    best=min(rows,key=lambda r:(r["nmae"],r["log_rmse"])); return best["trust"],rows


def trust_intervention_grid(model,*,root_seed=99117,n_scenarios=3,replicates=1,horizon=7.,grid=(0,.25,.5,.75,1.0),bounds=None):
    bounds=bounds or HazardBounds(); scenarios=paired_scenarios(root_seed+41,n_scenarios,"id"); rows=[]
    # Oracle effects only once.
    oracle={}
    for i,sc in enumerate(scenarios):
        vals={}
        for pol in ("throughput","semantic"):
            rr=[run_counterfactual("oracle",sc,pol,scenario_id=i,replicate=r,root_seed=root_seed,model=model,horizon=horizon,bounds=bounds)["goal_utility_ratio"] for r in range(replicates)]
            vals[pol]=float(np.mean(rr))
        oracle[i]=vals["semantic"]-vals["throughput"]
    for a in grid:
        errs=[]
        for i,sc in enumerate(scenarios):
            vals={}
            for pol in ("throughput","semantic"):
                rr=[run_counterfactual(f"residual_{a:.2f}",sc,pol,scenario_id=i,replicate=r,root_seed=root_seed,model=model,trust=a,horizon=horizon,bounds=bounds)["goal_utility_ratio"] for r in range(replicates)]
                vals[pol]=float(np.mean(rr))
            eff=vals["semantic"]-vals["throughput"]; errs.append(abs(eff-oracle[i]))
        rows.append({"trust":float(a),"effect_mae":float(np.mean(errs)),"scenario_errors":errs})
    best=min(rows,key=lambda r:r["effect_mae"]); return best["trust"],rows


def run_final_study(model,trust_predictive,trust_intervention,*,root_seed=620218,n_scenarios=5,replicates=2,horizon=9.,regimes=("id","high_mobility","high_stress"),bounds=None):
    bounds=bounds or HazardBounds(); rows=[]
    specs=[("oracle",None),("mechanistic",None),("residual_raw",1.0),("residual_predictive",trust_predictive),("residual_intervention",trust_intervention)]
    for ri,reg in enumerate(regimes):
        scenarios=paired_scenarios(root_seed+1003*ri,n_scenarios,reg)
        for si,sc in enumerate(scenarios):
            for rep in range(replicates):
                for kind,trust in specs:
                    for pol in ("throughput","semantic"):
                        d=run_counterfactual(kind,sc,pol,scenario_id=100*ri+si,replicate=rep,root_seed=root_seed,model=model,trust=(1.0 if trust is None else trust),horizon=horizon,bounds=bounds,verify=(ri==0 and si==0 and rep==0 and kind=="residual_intervention" and pol=="semantic"))
                        d["regime"]=reg; d.update({f"scenario_{k}":v for k,v in asdict(sc).items()}); rows.append(d)
    return pd.DataFrame(rows)


def bootstrap(values,n=20000,seed=0):
    v=np.asarray(values,float); rng=np.random.default_rng(seed); draws=v[rng.integers(0,len(v),size=(n,len(v)))].mean(1); return {"mean":float(v.mean()),"lo":float(np.quantile(draws,.025)),"hi":float(np.quantile(draws,.975))}


def analyze_study(df,metric="goal_utility_ratio",n_boot=20000):
    sm=df.groupby(["regime","scenario","model","policy"],as_index=False)[metric].mean(); piv=sm.pivot_table(index=["regime","scenario","model"],columns="policy",values=metric).reset_index(); piv["effect"]=piv.semantic-piv.throughput
    out={"metric":metric,"regimes":{}}
    for reg in df.regime.unique():
        p=piv[piv.regime==reg]; o=p[p.model=="oracle"].set_index("scenario").effect; rd={"oracle_effect":bootstrap(o.values,n_boot,11),"models":{}}
        ol=sm[(sm.regime==reg)&(sm.model=="oracle")].set_index(["scenario","policy"])[metric]
        for kind in sorted(set(p.model)-{"oracle"}):
            e=p[p.model==kind].set_index("scenario").effect.reindex(o.index); err=e-o
            l=sm[(sm.regime==reg)&(sm.model==kind)].set_index(["scenario","policy"])[metric].reindex(ol.index)
            rd["models"][kind]={"effect_mean":float(e.mean()),"effect_mae":float(np.abs(err).mean()),"effect_rmse":float(np.sqrt((err**2).mean())),"sign_agreement":float(np.mean(np.sign(e)==np.sign(o))),"level_mae":float(np.abs(l-ol).mean()),"effect_error_ci":bootstrap(err.values,n_boot,17+len(kind))}
        out["regimes"][reg]=rd
    return out

def trust_intervention_grid_multi(
    model, *, root_seed=771177, regimes=("id","high_mobility","high_stress"),
    scenarios_per_regime=2, replicates=1, horizon=3.0,
    grid=(0,.25,.5,.75,1.0), bounds=None,
    predictive_weight:float=0.0, validation_traces=None,
):
    """Distributionally broader intervention trust calibration.

    The calibration scenarios are disjoint from final-study scenarios by root
    seed.  The objective is mean absolute oracle policy-effect error across
    regimes.  Optionally a small predictive term can be added to avoid choosing
    a counterfactually good but observationally degenerate residual shrinkage.
    """
    bounds=bounds or HazardBounds(); rows=[]; oracle={}; scenarios=[]
    for ri,reg in enumerate(regimes):
        for si,sc in enumerate(paired_scenarios(root_seed+1379*ri,scenarios_per_regime,reg)):
            sid=1000*ri+si; scenarios.append((reg,sid,sc))
            vals={}
            for pol in ("throughput","semantic"):
                rr=[run_counterfactual("oracle",sc,pol,scenario_id=sid,replicate=r,root_seed=root_seed,model=model,horizon=horizon,bounds=bounds)["goal_utility_ratio"] for r in range(replicates)]
                vals[pol]=float(np.mean(rr))
            oracle[(reg,sid)]=vals["semantic"]-vals["throughput"]
    pred_by_trust={}
    if validation_traces is not None:
        for a in grid: pred_by_trust[float(a)]=eval_hazard(model,validation_traces,bounds,a)["nmae"]
    for a in grid:
        errs=[]; by_reg={reg:[] for reg in regimes}
        for reg,sid,sc in scenarios:
            vals={}
            for pol in ("throughput","semantic"):
                rr=[run_counterfactual(f"residual_{a:.2f}",sc,pol,scenario_id=sid,replicate=r,root_seed=root_seed,model=model,trust=a,horizon=horizon,bounds=bounds)["goal_utility_ratio"] for r in range(replicates)]
                vals[pol]=float(np.mean(rr))
            e=abs((vals["semantic"]-vals["throughput"])-oracle[(reg,sid)])
            errs.append(e); by_reg[reg].append(e)
        intervention=float(np.mean(errs)); pred=float(pred_by_trust.get(float(a),0.0))
        objective=intervention+float(predictive_weight)*pred
        rows.append({"trust":float(a),"intervention_effect_mae":intervention,"predictive_nmae":pred,"objective":objective,"regime_mae":{k:float(np.mean(v)) for k,v in by_reg.items()},"scenario_errors":errs})
    best=min(rows,key=lambda r:(r["objective"],r["intervention_effect_mae"],r["predictive_nmae"])); return best["trust"],rows
