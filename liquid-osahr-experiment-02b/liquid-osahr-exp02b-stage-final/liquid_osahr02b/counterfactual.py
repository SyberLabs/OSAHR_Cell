"""Counterfactual policy study for Liquid-OSAHR Experiment 02B."""
from __future__ import annotations

from dataclasses import dataclass, asdict
from pathlib import Path
import math
import sys
import copy

import numpy as np
import pandas as pd
import torch

VENDOR = Path(__file__).resolve().parents[1] / "vendor"
if str(VENDOR) not in sys.path: sys.path.insert(0,str(VENDOR))
from osahr import RuntimeConfig,SchedulerKind  # type: ignore
from osahr.rng import derive_seed  # type: ignore

from .field import HazardBounds,OracleField,NeuralLiquidField,FrozenOpenLoopNeuralField,Scenario,graph_view
from .hybrid import HybridLiquidRuntime
from .twin import TwinConfig,build_model


@dataclass
class RunMetrics:
    model:str; regime:str; scenario:int; replicate:int; policy:str; seed:int; events:int
    goal_utility_ratio:float; critical_success_rate:float; mean_latency:float; energy:float
    generated:int; delivered:int; outages:int; recoveries:int; handovers:int; reroutes:int
    final_hash:str; thinning_rejections:int; thinning_windows:int


def _memory_metrics(runtime:HybridLiquidRuntime)->dict:
    z=runtime.memory
    return {
        "goal_utility_ratio":float(z["timely_semantic_utility"])/max(float(z["generated_utility"]),1e-12),
        "critical_success_rate":float(z["timely_critical"])/max(int(z["generated_critical"]),1),
        "mean_latency":float(z["latency_sum"])/max(int(z["delivered"]),1),
        "energy":float(z["energy"]),"generated":int(z["generated"]),"delivered":int(z["delivered"]),
        "outages":int(z["outages"]),"recoveries":int(z["recoveries"]),"handovers":int(z["handovers"]),"reroutes":int(z["reroutes"]),
    }


def make_field(kind:str,scenario:Scenario,bounds:HazardBounds,index,graph,models:dict[str,torch.nn.Module],seed:int):
    if kind=="oracle": return OracleField(index,scenario,bounds,seed=seed,initial_noise=0.0)
    if kind=="cfc_openloop": return FrozenOpenLoopNeuralField(models["cfc_closed"],index,scenario,bounds,name=kind)
    model=models[kind]
    return NeuralLiquidField(model,index,scenario,bounds,name=kind)


def run_counterfactual(
    *,kind:str,scenario:Scenario,regime:str,scenario_id:int,replicate:int,policy:str,root_seed:int,
    models:dict[str,torch.nn.Module],bounds:HazardBounds|None=None,cfg:TwinConfig|None=None,verify_incremental:bool=False,
)->RunMetrics:
    bounds=bounds or HazardBounds(); cfg=cfg or TwinConfig()
    model,index=build_model(policy,scenario,cfg,bounds)
    run_seed=derive_seed(root_seed,f"02b:{regime}:{scenario_id}:{replicate}")
    field=make_field(kind,scenario,bounds,index,model.graph,models,derive_seed(root_seed,f"field:{kind}:{regime}:{scenario_id}:{replicate}"))
    runtime=HybridLiquidRuntime(model,field=field,root_seed=run_seed,config=RuntimeConfig(
        scheduler=SchedulerKind.THINNING,matcher_backend="incremental",incremental_verify=verify_incremental,
        max_simulation_time=cfg.horizon,thinning_window=.55,max_events=150_000,max_thinning_windows_per_plan=300_000,
    ))
    runtime.run_until_time(cfg.horizon)
    m=_memory_metrics(runtime)
    return RunMetrics(kind,regime,scenario_id,replicate,policy,run_seed,runtime.event_index,**m,final_hash=runtime.state_hash,
        thinning_rejections=int(runtime.thinning_audit.rejected_candidates),thinning_windows=int(runtime.thinning_audit.windows_crossed))


def paired_scenarios(seed:int,n:int,regime:str)->list[Scenario]:
    from .data import sample_scenario
    rng=np.random.default_rng(seed)
    return [sample_scenario(rng,regime=regime) for _ in range(n)]


def run_study(models:dict[str,torch.nn.Module],*,root_seed:int=912017,n_scenarios:int=8,replicates:int=3,horizon:float=16.0,regimes=("id","high_mobility","high_stress"),model_kinds=("oracle","cfc_closed","cfc_nojump","gru_closed"),verify_first:bool=True)->pd.DataFrame:
    rows=[]; bounds=HazardBounds(); cfg=TwinConfig(horizon=horizon)
    for regime_i,regime in enumerate(regimes):
        scenarios=paired_scenarios(root_seed+113*regime_i,n_scenarios,regime)
        for sidx,scenario in enumerate(scenarios):
            for rep in range(replicates):
                for kind in model_kinds:
                    for policy in ("throughput","semantic"):
                        row=run_counterfactual(kind=kind,scenario=scenario,regime=regime,scenario_id=sidx,replicate=rep,policy=policy,root_seed=root_seed,models=models,bounds=bounds,cfg=cfg,verify_incremental=verify_first and regime_i==0 and sidx==0 and rep==0 and kind=="cfc_closed" and policy=="semantic")
                        d=asdict(row); d.update({f"scenario_{k}":v for k,v in asdict(scenario).items()}); rows.append(d)
    return pd.DataFrame(rows)


def _scenario_means(df:pd.DataFrame,metric:str)->pd.DataFrame:
    return df.groupby(["regime","scenario","model","policy"],as_index=False)[metric].mean()


def policy_effect_table(df:pd.DataFrame,metric:str="goal_utility_ratio")->pd.DataFrame:
    m=_scenario_means(df,metric)
    piv=m.pivot_table(index=["regime","scenario","model"],columns="policy",values=metric).reset_index()
    piv["effect"]=piv["semantic"]-piv["throughput"]
    return piv


def bootstrap_scenario_mean(values:np.ndarray,*,seed:int=0,n_boot:int=20000)->dict[str,float]:
    values=np.asarray(values,dtype=float); rng=np.random.default_rng(seed)
    if len(values)==0: return {"mean":math.nan,"lo":math.nan,"hi":math.nan}
    draws=values[rng.integers(0,len(values),size=(n_boot,len(values)))].mean(axis=1)
    return {"mean":float(values.mean()),"lo":float(np.quantile(draws,.025)),"hi":float(np.quantile(draws,.975))}


def analyze_study(df:pd.DataFrame,*,metric:str="goal_utility_ratio",n_boot:int=20000)->dict[str,object]:
    effects=policy_effect_table(df,metric)
    out={"metric":metric,"regimes":{}}
    for regime in sorted(effects.regime.unique()):
        part=effects[effects.regime==regime]; oracle=part[part.model=="oracle"].set_index("scenario")["effect"]
        reg={"oracle_effect":bootstrap_scenario_mean(oracle.values,seed=100+len(regime),n_boot=n_boot),"models":{}}
        # aggregate distribution fidelity under both policies at scenario level
        sm=_scenario_means(df[df.regime==regime],metric)
        oracle_levels=sm[sm.model=="oracle"].set_index(["scenario","policy"])[metric]
        for kind in sorted(set(part.model)-{"oracle"}):
            eff=part[part.model==kind].set_index("scenario")["effect"].reindex(oracle.index)
            err=(eff-oracle)
            level=sm[sm.model==kind].set_index(["scenario","policy"])[metric].reindex(oracle_levels.index)
            level_err=(level-oracle_levels)
            reg["models"][kind]={
                "effect_mean":float(eff.mean()),"effect_mae":float(np.mean(np.abs(err))),"effect_rmse":float(np.sqrt(np.mean(err**2))),
                "effect_sign_agreement":float(np.mean(np.sign(eff)==np.sign(oracle))),"level_mae":float(np.mean(np.abs(level_err))),
                "effect_error_bootstrap":bootstrap_scenario_mean(err.values,seed=300+sum(map(ord,kind+regime)),n_boot=n_boot),
            }
        out["regimes"][regime]=reg
    return out
