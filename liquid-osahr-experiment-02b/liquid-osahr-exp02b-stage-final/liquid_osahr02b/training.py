"""Training and identification metrics for topology-coupled bounded hazard fields."""
from __future__ import annotations

from dataclasses import dataclass, asdict
from pathlib import Path
import copy
import json
import math
import time

import numpy as np
import torch
from torch import nn

from .data import HybridTrace, make_loader
from .field import AnchoredGraphCfC, AnchoredGraphGRU, HazardBounds, HEADS, STRUCT_DIM, parameter_count


@dataclass(frozen=True)
class TrainConfig:
    epochs:int=34
    batch_size:int=4
    learning_rate:float=1.8e-3
    weight_decay:float=2e-5
    grad_clip:float=4.0
    patience:int=7
    min_delta:float=2e-4
    seed:int=20260218
    device:str="cpu"


@dataclass
class TrainResult:
    model_name:str
    parameter_count:int
    best_epoch:int
    best_val_loss:float
    train_seconds:float
    history:list[dict[str,float]]
    checkpoint:str|None=None


def build_field_model(name:str,*,seed:int=0):
    torch.manual_seed(seed)
    if name=="cfc_closed": return AnchoredGraphCfC(STRUCT_DIM,20,use_jumps=True,dynamic_topology=True)
    if name=="cfc_nojump": return AnchoredGraphCfC(STRUCT_DIM,20,use_jumps=False,dynamic_topology=True)
    if name=="gru_closed": return AnchoredGraphGRU(STRUCT_DIM,26,use_jumps=True,dynamic_topology=True)
    raise ValueError(name)


def rollout_rates(model:nn.Module,batch:dict[str,torch.Tensor],bounds:HazardBounds,*,device:str="cpu",return_hidden:bool=False):
    structural=batch["structural"].to(device); adjacency=batch["adjacency"].to(device); times=batch["times"].to(device)
    event_code=batch["event_code"].to(device); affected=batch["affected"].to(device); frame_mask=batch["frame_mask"].to(device)
    B,L,N,F=structural.shape
    h=model.initial_state(structural[:,0])
    bvec=torch.tensor(bounds.vector(),dtype=structural.dtype,device=device)
    outputs=[model.rates(h,structural[:,0],bvec,bounds.floor)]
    hidden=[h] if return_hidden else None
    for i in range(1,L):
        dt=(times[:,i]-times[:,i-1]).clamp_min(0.0).unsqueeze(-1)
        proposed=model.flow(h,structural[:,i-1],adjacency[:,i-1],dt)
        proposed=model.jump(proposed,event_code[:,i],affected[:,i],structural[:,i])
        valid=frame_mask[:,i].view(B,1,1)
        h=torch.where(valid,proposed,h)
        outputs.append(model.rates(h,structural[:,i],bvec,bounds.floor))
        if hidden is not None: hidden.append(h)
    rates=torch.stack(outputs,dim=1)
    if return_hidden: return rates,torch.stack(hidden,dim=1)
    return rates


def masked_hazard_loss(pred:torch.Tensor,target:torch.Tensor,rate_mask:torch.Tensor,frame_mask:torch.Tensor,bounds:HazardBounds)->torch.Tensor:
    active=rate_mask*frame_mask[:,:,None,None].to(rate_mask.dtype)
    eps=1e-6
    log_err=(torch.log(pred+eps)-torch.log(target+eps))**2
    bvec=torch.tensor(bounds.vector(),dtype=pred.dtype,device=pred.device).view(1,1,1,-1)
    norm_err=((pred-target)/bvec.clamp_min(1e-6))**2
    # Log error dominates rare failure/recovery heads; normalized error keeps
    # high-rate service scale honest.
    loss=(log_err+0.25*norm_err)*active
    return loss.sum()/active.sum().clamp_min(1.0)


@torch.no_grad()
def evaluate_loss(model,traces:list[HybridTrace],bounds:HazardBounds,*,batch_size:int=4,device:str="cpu")->float:
    model.eval(); total=0.0; weight=0.0
    for batch in make_loader(traces,batch_size=batch_size,shuffle=False,seed=0):
        pred=rollout_rates(model,batch,bounds,device=device)
        target=batch["target_rates"].to(device); rate_mask=batch["rate_mask"].to(device); fm=batch["frame_mask"].to(device)
        active=float((rate_mask*fm[:,:,None,None]).sum())
        loss=masked_hazard_loss(pred,target,rate_mask,fm,bounds)
        total+=float(loss)*active; weight+=active
    return total/max(weight,1.0)


def train_model(name:str,train:list[HybridTrace],val:list[HybridTrace],bounds:HazardBounds,cfg:TrainConfig,*,checkpoint:Path|None=None):
    torch.manual_seed(cfg.seed); np.random.seed(cfg.seed)
    model=build_field_model(name,seed=cfg.seed).to(cfg.device)
    opt=torch.optim.AdamW(model.parameters(),lr=cfg.learning_rate,weight_decay=cfg.weight_decay)
    loader=make_loader(train,batch_size=cfg.batch_size,shuffle=True,seed=cfg.seed)
    best=copy.deepcopy(model.state_dict()); best_val=math.inf; best_epoch=0; left=cfg.patience; history=[]; start=time.perf_counter()
    for epoch in range(1,cfg.epochs+1):
        model.train(); total=0.0; weight=0.0
        for batch in loader:
            opt.zero_grad(set_to_none=True)
            pred=rollout_rates(model,batch,bounds,device=cfg.device)
            target=batch["target_rates"].to(cfg.device); rm=batch["rate_mask"].to(cfg.device); fm=batch["frame_mask"].to(cfg.device)
            loss=masked_hazard_loss(pred,target,rm,fm,bounds)
            if not torch.isfinite(loss): raise RuntimeError(f"non-finite loss for {name}")
            loss.backward(); nn.utils.clip_grad_norm_(model.parameters(),cfg.grad_clip); opt.step()
            active=float((rm*fm[:,:,None,None]).sum()); total+=float(loss.detach())*active; weight+=active
        train_loss=total/max(weight,1.0); val_loss=evaluate_loss(model,val,bounds,batch_size=cfg.batch_size,device=cfg.device)
        history.append({"epoch":epoch,"train_loss":train_loss,"val_loss":val_loss})
        if val_loss < best_val-cfg.min_delta:
            best_val=val_loss; best_epoch=epoch; best=copy.deepcopy(model.state_dict()); left=cfg.patience
        else:
            left-=1
            if left<=0: break
    elapsed=time.perf_counter()-start; model.load_state_dict(best)
    result=TrainResult(name,parameter_count(model),best_epoch,best_val,elapsed,history,str(checkpoint) if checkpoint else None)
    if checkpoint is not None:
        checkpoint.parent.mkdir(parents=True,exist_ok=True)
        torch.save({"model_name":name,"state_dict":best,"train_config":asdict(cfg),"best_epoch":best_epoch,"best_val_loss":best_val,"bounds":asdict(bounds),"parameter_count":parameter_count(model)},checkpoint)
    return model,result


def load_checkpoint(path:Path,*,device:str="cpu"):
    payload=torch.load(path,map_location=device,weights_only=False); model=build_field_model(payload["model_name"],seed=0).to(device); model.load_state_dict(payload["state_dict"]); model.eval(); return model,payload


@torch.no_grad()
def identification_metrics(model,traces:list[HybridTrace],bounds:HazardBounds,*,model_name:str,device:str="cpu")->dict[str,object]:
    model.eval(); pred_all=[]; target_all=[]; mask_all=[]
    per_trace=[]
    for tr in traces:
        batch=next(iter(make_loader([tr],batch_size=1,shuffle=False,seed=0)))
        pred=rollout_rates(model,batch,bounds,device=device)[0,:tr.length].cpu().numpy()
        target=tr.target_rates; mask=tr.rate_mask.astype(bool)
        p=pred[mask]; y=target[mask]
        log_rmse=float(np.sqrt(np.mean((np.log(p+1e-6)-np.log(y+1e-6))**2)))
        mae=float(np.mean(np.abs(p-y))); nmae=float(np.mean(np.abs(p-y)/np.broadcast_to(bounds.vector(),target.shape)[mask]))
        per_trace.append({"trace_id":tr.trace_id,"mae":mae,"normalized_mae":nmae,"log_rmse":log_rmse})
        pred_all.append(pred); target_all.append(target); mask_all.append(mask)
    # flatten valid cells across traces
    ps=np.concatenate([p[m] for p,m in zip(pred_all,mask_all)]); ys=np.concatenate([y[m] for y,m in zip(target_all,mask_all)])
    head={}
    for k,name in enumerate(HEADS):
        hp=[]; hy=[]
        for p,y,m in zip(pred_all,target_all,mask_all):
            mk=m[:,:,k]
            if mk.any(): hp.append(p[:,:,k][mk]); hy.append(y[:,:,k][mk])
        if hp:
            pp=np.concatenate(hp); yy=np.concatenate(hy)
            head[name]={"mae":float(np.mean(np.abs(pp-yy))),"rmse":float(np.sqrt(np.mean((pp-yy)**2))),"mean_pred":float(pp.mean()),"mean_true":float(yy.mean())}
    return {
        "model":model_name,"traces":len(traces),"cells":int(len(ps)),"mae":float(np.mean(np.abs(ps-ys))),"normalized_mae":float(np.mean([x["normalized_mae"] for x in per_trace])),"log_rmse":float(np.sqrt(np.mean((np.log(ps+1e-6)-np.log(ys+1e-6))**2))),"head_metrics":head,"per_trace":per_trace,
    }
