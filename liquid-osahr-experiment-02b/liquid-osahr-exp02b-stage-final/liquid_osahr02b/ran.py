"""Standards-informed RAN physics and intervention-constrained residual fields for Experiment 02B.

This is deliberately *not* presented as a replacement for ns-3/5G-LENA or srsRAN.
It is a deterministic, differentiable-enough control-plane surrogate whose large-scale
propagation follows 3GPP TR 38.901 UMi street-canyon equations and whose telemetry
schema mirrors metrics available from contemporary srsRAN/O-RAN KPM paths.
"""
from __future__ import annotations
from dataclasses import dataclass
from typing import Mapping
import math
import numpy as np
import torch
from torch import nn

from .field import (
    FieldBase, PersistentIndex, Scenario, HazardBounds, HEADS, HEAD_INDEX,
    graph_view, event_affected_mask, applicable_head_mask, RELATIONS, EVENTS, EVENT_INDEX,
)
from .liquid_base import CfCCell

# RAN/KPM features appended to the 02B structural vector.
KPM_FEATURES=("rsrp_dbm","sinr_db","cqi","spectral_eff","neighbor_margin_db","speed_mps","prb_util","drop_prob","throughput_norm")
RAN_STRUCT_DIM=14+len(KPM_FEATURES)

@dataclass(frozen=True)
class RANConfig:
    carrier_ghz: float=3.5
    bandwidth_mhz: float=40.0
    tx_power_dbm: float=30.0
    noise_figure_db: float=7.0
    bs_height_m: float=10.0
    ue_height_m: float=1.5
    factory_length_m: float=140.0
    factory_width_m: float=45.0
    shadow_sigma_db: float=4.0
    shadow_terms: int=5
    fading_db: float=2.2
    handover_hysteresis_db: float=3.0
    service_scale: float=0.82
    max_se_bps_hz: float=7.4
    residual_logit_limit: float=1.35


def _sigmoid(x): return 1.0/(1.0+np.exp(-np.clip(x,-40.0,40.0)))
def _logit(p):
    p=np.clip(p,1e-6,1-1e-6); return np.log(p/(1-p))

class RANPhysics:
    """Continuous deterministic site surrogate with 3GPP-informed propagation.

    Randomness is encoded into a finite set of phase coefficients at construction,
    making telemetry a pure function of (time, graph, scenario, seed).  This is
    important for common-random-number counterfactual comparisons.
    """
    def __init__(self,index:PersistentIndex,scenario:Scenario,*,seed:int=0,cfg:RANConfig|None=None):
        self.index=index; self.scenario=scenario; self.cfg=cfg or RANConfig(); self.seed=int(seed)
        rng=np.random.default_rng(seed)
        self.ue_indices=[i for i,t in enumerate(index.types) if t=="UE"]
        self.gnb_indices=[i for i,t in enumerate(index.types) if t=="GNB"]
        self.edge_indices=[i for i,t in enumerate(index.types) if t=="EdgeNode"]
        n=max(len(self.ue_indices),1)
        self.phase=rng.uniform(0,2*np.pi,size=(n,4))
        self.shadow_phase=rng.uniform(0,2*np.pi,size=(n,self.cfg.shadow_terms))
        self.shadow_k=rng.uniform(.025,.11,size=(n,self.cfg.shadow_terms,2))
        self.fading_phase=rng.uniform(0,2*np.pi,size=(n,4))
        self.gnb_pos=np.asarray([[25.0,self.cfg.factory_width_m/2],[115.0,self.cfg.factory_width_m/2]],dtype=float)[:len(self.gnb_indices)]

    def ue_position(self,ue_local:int,t:float)->tuple[np.ndarray,float]:
        c=self.cfg; p=self.phase[ue_local]
        speed_scale=float(self.scenario.mobility)
        w=.07*speed_scale*(1.0+.08*ue_local)
        # Smooth bounded industrial-aisle trajectory; derivative is analytic.
        x=c.factory_length_m/2 + .43*c.factory_length_m*np.sin(w*t+p[0])
        y=c.factory_width_m/2 + .38*c.factory_width_m*np.sin(.61*w*t+p[1])
        dx=.43*c.factory_length_m*w*np.cos(w*t+p[0])
        dy=.38*c.factory_width_m*.61*w*np.cos(.61*w*t+p[1])
        return np.asarray([x,y]),float(np.hypot(dx,dy))

    def _pathloss_umi(self,d2d:float,los_weight:float)->float:
        c=self.cfg; fc=c.carrier_ghz; hbs=c.bs_height_m; hut=c.ue_height_m
        d2d=max(float(d2d),10.0); d3d=math.sqrt(d2d*d2d+(hbs-hut)**2)
        # TR 38.901 UMi street canyon formulas (Table 7.4.1-1).  In our <=150 m
        # site, the first LOS branch applies for the chosen FR1 geometry.
        pl_los=32.4+21.0*math.log10(d3d)+20.0*math.log10(fc)
        pl_nlos_p=35.3*math.log10(d3d)+22.4+21.3*math.log10(fc)-0.3*(hut-1.5)
        pl_nlos=max(pl_los,pl_nlos_p)
        return float(los_weight*pl_los+(1-los_weight)*pl_nlos)

    @staticmethod
    def _los_probability(d2d:float)->float:
        d=max(float(d2d),1.0)
        return min(18.0/d,1.0)*(1.0-math.exp(-d/36.0))+math.exp(-d/36.0)

    def _shadow(self,ue_local:int,pos:np.ndarray)->float:
        vals=np.sin(self.shadow_k[ue_local,:,0]*pos[0]+self.shadow_k[ue_local,:,1]*pos[1]+self.shadow_phase[ue_local])
        return float(self.cfg.shadow_sigma_db*vals.mean()*math.sqrt(2.0))

    def _fast_fading(self,ue_local:int,t:float,speed:float,gnb_local:int)->float:
        # Sum-of-sinusoids Doppler surrogate. Bounded so certified event-rate
        # bounds remain independent of channel realization.
        fd=max(speed,0.1)*self.cfg.carrier_ghz*1e9/3e8
        phases=self.fading_phase[ue_local]+gnb_local*.73
        vals=[math.sin(2*math.pi*fd*t*mult+ph) for mult,ph in zip((.31,.47,.69,.91),phases)]
        return float(self.cfg.fading_db*np.mean(vals))

    def link_metrics(self,t:float)->dict[int,dict[int,dict[str,float]]]:
        """Return UE-index -> gNB-index -> physical KPM metrics."""
        c=self.cfg; noise=-174.0+10*math.log10(c.bandwidth_mhz*1e6)+c.noise_figure_db
        rx={}
        aux={}
        for ul,ui in enumerate(self.ue_indices):
            pos,speed=self.ue_position(ul,t); rx[ui]={}; aux[ui]={}
            for gl,gi in enumerate(self.gnb_indices):
                d=float(np.linalg.norm(pos-self.gnb_pos[gl])); p_los=self._los_probability(d)
                pl=self._pathloss_umi(d,p_los)
                rsrp=c.tx_power_dbm-pl+self._shadow(ul,pos)+self._fast_fading(ul,t,speed,gl)
                rx[ui][gi]=rsrp; aux[ui][gi]=(d,p_los,speed)
        out={}
        for ui in self.ue_indices:
            out[ui]={}
            for gi in self.gnb_indices:
                signal=10**(rx[ui][gi]/10)
                interf=sum(10**(v/10) for gj,v in rx[ui].items() if gj!=gi)
                noise_mw=10**(noise/10)
                sinr=10*math.log10(signal/(interf+noise_mw)+1e-15)
                se=min(c.max_se_bps_hz,max(0.05,math.log2(1+10**(sinr/10)/1.5)))
                cqi=float(np.clip(np.floor((sinr+7.0)/2.0)+1,1,15))
                # Smooth BLER proxy: ~10% around 0 dB adjusted by CQI.
                bler=float(_sigmoid(-(sinr-(-5.0+1.35*cqi))/1.8))
                d,p_los,speed=aux[ui][gi]
                out[ui][gi]={"rsrp_dbm":float(rx[ui][gi]),"sinr_db":float(sinr),"cqi":cqi,"spectral_eff":float(se),"drop_prob":bler,"speed_mps":float(speed),"distance_m":d,"p_los":p_los}
        return out

    def association_map(self,graph)->dict[int,int]:
        ids=self.index.ids; id_to_i=self.index.id_to_index; out={}
        for eid in graph.edges_by_type.get("Association",set()):
            e=graph.edges[eid]; verts=[inc.vertex_id for inc in e.incidences]
            if len(verts)!=2: continue
            a,b=verts
            if a in id_to_i and b in id_to_i:
                ia,ib=id_to_i[a],id_to_i[b]
                if self.index.types[ia]=="UE": out[ia]=ib
                elif self.index.types[ib]=="UE": out[ib]=ia
        return out

    def telemetry(self,t:float,graph)->np.ndarray:
        base=graph_view(graph,self.index,self.scenario).structural.astype(np.float32)
        x=np.zeros((self.index.n,RAN_STRUCT_DIM),dtype=np.float32); x[:,:base.shape[1]]=base
        links=self.link_metrics(t); assoc=self.association_map(graph)
        # gNB load = number associated UEs / max(1,n_ues/2), edge load is already structural.
        gload={gi:0 for gi in self.gnb_indices}
        for ui,gi in assoc.items(): gload[gi]+=1
        norm=max(len(self.ue_indices)/2,1.0)
        for ul,ui in enumerate(self.ue_indices):
            gi=assoc.get(ui,self.gnb_indices[0]); m=links[ui][gi]
            neighbors=[g for g in self.gnb_indices if g!=gi]
            margin=max([links[ui][g]["rsrp_dbm"]-m["rsrp_dbm"] for g in neighbors] or [-30.0])
            util=min(gload.get(gi,0)/norm,1.5)
            tput=m["spectral_eff"]*self.cfg.bandwidth_mhz/max(gload.get(gi,1),1)
            vals=(m["rsrp_dbm"]/120.0,m["sinr_db"]/30.0,m["cqi"]/15.0,m["spectral_eff"]/self.cfg.max_se_bps_hz,margin/20.0,m["speed_mps"]/20.0,util,m["drop_prob"],tput/300.0)
            x[ui,14:]=np.asarray(vals,dtype=np.float32)
        for gi in self.gnb_indices:
            members=[ui for ui,g in assoc.items() if g==gi]
            if members:
                vals=[]
                for ui in members:
                    m=links[ui][gi]; vals.append([m["rsrp_dbm"]/120,m["sinr_db"]/30,m["cqi"]/15,m["spectral_eff"]/self.cfg.max_se_bps_hz,0,m["speed_mps"]/20,gload[gi]/norm,m["drop_prob"],m["spectral_eff"]*self.cfg.bandwidth_mhz/300])
                x[gi,14:]=np.mean(vals,axis=0)
        # Edge nodes inherit aggregate RAN state plus their own load.
        allm=[]
        for ui,gi in assoc.items():
            m=links[ui][gi]; allm.append([m["rsrp_dbm"]/120,m["sinr_db"]/30,m["cqi"]/15,m["spectral_eff"]/self.cfg.max_se_bps_hz,0,m["speed_mps"]/20,0,m["drop_prob"],m["spectral_eff"]*self.cfg.bandwidth_mhz/300])
        agg=np.mean(allm,axis=0) if allm else np.zeros(9)
        for ei in self.edge_indices:
            x[ei,14:]=agg; x[ei,20]=base[ei,4]  # PRB/util proxy follows MEC load coupling
        return x

    def oracle_rates(self,t:float,graph,bounds:HazardBounds)->np.ndarray:
        tele=self.telemetry(t,graph); out=np.zeros((self.index.n,len(HEADS)),dtype=float)
        b=bounds.vector(); floor=bounds.floor
        # service: network spectral efficiency + compute congestion + semantic channel condition
        for ei in self.edge_indices:
            load=float(tele[ei,4]); se=float(tele[ei,17]); drop=float(tele[ei,21]); available=float(tele[ei,3])
            profile_fast=1.0 if graph.vertices[self.index.ids[ei]].attributes.get("profile")=="fast" else 0.0
            z=-0.35+3.0*se-1.65*load-1.1*drop+0.55*profile_fast+0.25*self.scenario.channel
            out[ei,HEAD_INDEX["service"]]=floor+(b[0]-floor)*_sigmoid(z)*available
            if available>0.5:
                zf=-4.0+1.8*load+1.1*drop+0.8*self.scenario.stress
                out[ei,HEAD_INDEX["failure"]]=floor+(b[1]-floor)*_sigmoid(zf)
            else:
                zr=-.35-0.45*self.scenario.stress+0.25*self.scenario.channel
                out[ei,HEAD_INDEX["recovery"]]=floor+(b[2]-floor)*_sigmoid(zr)
        # handover: A3-style margin soft trigger with mobility sensitivity
        assoc=self.association_map(graph); links=self.link_metrics(t)
        for ui,gi in assoc.items():
            margins=[links[ui][g]["rsrp_dbm"]-links[ui][gi]["rsrp_dbm"] for g in self.gnb_indices if g!=gi]
            margin=max(margins or [-30.0]); speed=links[ui][gi]["speed_mps"]
            z=-3.5+1.15*(margin-self.cfg.handover_hysteresis_db)+0.07*speed
            out[ui,HEAD_INDEX["handover"]]=floor+(b[3]-floor)*_sigmoid(z)
        return out*applicable_head_mask(graph,self.index)

    def mechanistic_rates(self,t:float,graph,bounds:HazardBounds)->np.ndarray:
        """Intentionally simplified engineering prior used by the residual model."""
        tele=self.telemetry(t,graph); out=np.zeros((self.index.n,len(HEADS)),dtype=float); b=bounds.vector(); floor=bounds.floor
        for ei in self.edge_indices:
            load=float(tele[ei,4]); se=float(tele[ei,17]); avail=float(tele[ei,3])
            out[ei,0]=(floor+(b[0]-floor)*_sigmoid(-.25+2.55*se-1.45*load))*avail
            if avail>.5: out[ei,1]=floor+(b[1]-floor)*_sigmoid(-4.1+1.5*load+.55*self.scenario.stress)
            else: out[ei,2]=floor+(b[2]-floor)*_sigmoid(-.25-.35*self.scenario.stress)
        assoc=self.association_map(graph); links=self.link_metrics(t)
        for ui,gi in assoc.items():
            margins=[links[ui][g]["rsrp_dbm"]-links[ui][gi]["rsrp_dbm"] for g in self.gnb_indices if g!=gi]
            margin=max(margins or [-30]); out[ui,3]=floor+(b[3]-floor)*_sigmoid(-3.7+.92*(margin-self.cfg.handover_hysteresis_db))
        return out*applicable_head_mask(graph,self.index)


class RANOracleField(FieldBase):
    name="ran_oracle"
    def __init__(self,index,scenario,bounds,*,seed:int=0,cfg:RANConfig|None=None):
        super().__init__(index,scenario,bounds); self.physics=RANPhysics(index,scenario,seed=seed,cfg=cfg); self.anchor_state=np.zeros((index.n,3)); self._cache={}
    def initialize(self,graph): self.anchor_time=0.; self.anchor_state=np.zeros((self.index.n,3)); self._cache={}
    def state_at(self,time,graph):
        tele=self.physics.telemetry(float(time),graph); return tele[:,14:17].astype(float)
    def base_rates_at(self,time,graph): return self.physics.oracle_rates(float(time),graph,self.bounds)
    def commit_event(self,time,pre_graph,post_graph,rule_id,match): self.anchor_time=float(time); return {"rule":rule_id,"affected":event_affected_mask(rule_id,match,self.index).tolist(),"mechanistic_jump":True}
    def snapshot(self): return {"anchor_time":self.anchor_time}
    def restore(self,s): self.anchor_time=float(s["anchor_time"])

class RANMechanisticField(RANOracleField):
    name="ran_mechanistic"
    def base_rates_at(self,time,graph): return self.physics.mechanistic_rates(float(time),graph,self.bounds)


class ResidualGraphCfC(nn.Module):
    """Topology-coupled CfC that learns a bounded *residual* over mechanism."""
    def __init__(self,structural_dim:int=RAN_STRUCT_DIM,hidden_size:int=20,residual_limit:float=1.35):
        super().__init__(); self.structural_dim=structural_dim; self.hidden_size=hidden_size; self.residual_limit=float(residual_limit)
        self.rel=nn.ModuleList([nn.Linear(hidden_size,hidden_size,bias=False) for _ in RELATIONS])
        self.input_proj=nn.Sequential(nn.Linear(structural_dim+hidden_size,56),nn.Tanh(),nn.Linear(56,32),nn.Tanh())
        self.cell=CfCCell(32,hidden_size,backbone_units=48,backbone_layers=1)
        self.kappa_raw=nn.Parameter(torch.zeros(hidden_size)); self.init_net=nn.Sequential(nn.Linear(structural_dim,48),nn.Tanh(),nn.Linear(48,hidden_size),nn.Tanh())
        self.residual_head=nn.Linear(hidden_size+structural_dim,len(HEADS))
        for m in self.modules():
            if isinstance(m,nn.Linear): nn.init.xavier_uniform_(m.weight); nn.init.zeros_(m.bias) if m.bias is not None else None
    def initial_state(self,x): return self.init_net(x)
    def _message(self,h,A):
        out=torch.zeros_like(h)
        for r,layer in enumerate(self.rel): out+=torch.einsum("bij,bjh->bih",A[:,r],layer(h))
        return out/len(self.rel)
    def flow(self,h,x,A,dt):
        if dt.ndim==1: dt=dt[:,None]
        inp=self.input_proj(torch.cat([x,self._message(h,A)],dim=-1)); B,N,_=inp.shape
        elapsed=dt[:,None,:].expand(B,N,1).reshape(B*N,1); cand=self.cell(inp.reshape(B*N,-1),h.reshape(B*N,-1),elapsed).reshape(B,N,-1)
        k=torch.nn.functional.softplus(self.kappa_raw).view(1,1,-1)+1e-4; a=1-torch.exp(-k*dt[:,None,:]); return h+a*(cand-h)
    def residual(self,h,x): return self.residual_limit*torch.tanh(self.residual_head(torch.cat([h,x],dim=-1)))
    def rates(self,h,x,mechanism,bounds,floor:float,trust:float=1.0):
        # alpha=0 is a semantic identity, not merely an approximation through
        # logit/sigmoid. This matters at exact floor/ceiling values and makes
        # the intervention-calibrated fallback precisely the mechanistic prior.
        if float(trust) == 0.0:
            return mechanism
        frac=((mechanism-floor)/(bounds.view(1,1,-1)-floor)).clamp(1e-5,1-1e-5)
        base=torch.log(frac)-torch.log1p(-frac); logits=base+float(trust)*self.residual(h,x)
        return floor+(bounds.view(1,1,-1)-floor)*torch.sigmoid(logits)

class ResidualRANField(FieldBase):
    name="ran_residual"
    def __init__(self,model:ResidualGraphCfC,index,scenario,bounds,*,seed:int=0,trust:float=1.0,cfg:RANConfig|None=None,device:str="cpu",name:str|None=None):
        super().__init__(index,scenario,bounds); self.model=model.to(device).eval(); self.device=device; self.trust=float(trust); self.physics=RANPhysics(index,scenario,seed=seed,cfg=cfg); self.anchor_state=np.zeros((index.n,model.hidden_size),dtype=np.float32); self.name=name or f"ran_residual_{trust:.2f}"; self._cache={}
    def _view(self,t,graph):
        x=self.physics.telemetry(float(t),graph); A=graph_view(graph,self.index,self.scenario).adjacency
        return torch.from_numpy(x).unsqueeze(0).to(self.device),torch.from_numpy(A).unsqueeze(0).to(self.device)
    def initialize(self,graph):
        x,A=self._view(0.,graph)
        with torch.inference_mode(): self.anchor_state=self.model.initial_state(x)[0].cpu().numpy().astype(np.float32)
        self.anchor_time=0.; self._cache={}
    def state_at(self,time,graph):
        key=(float(time),graph.epoch,self.anchor_time)
        if key in self._cache and self._cache[key][0] is not None:
            return self._cache[key][0].copy()
        x,A=self._view(time,graph); h=torch.from_numpy(self.anchor_state).unsqueeze(0).to(self.device); dt=torch.tensor([[max(0.,float(time-self.anchor_time))]],dtype=h.dtype,device=self.device)
        with torch.inference_mode(): st=self.model.flow(h,x,A,dt)
        val=st[0].cpu().numpy().astype(float)
        prior_rates = self._cache.get(key, (None, None))[1]
        self._cache[key]=(val,prior_rates)
        return val.copy()
    def base_rates_at(self,time,graph):
        key=(float(time),graph.epoch,self.anchor_time)
        if key in self._cache and self._cache[key][1] is not None: return self._cache[key][1].copy()
        # alpha=0 is the *exact* mechanistic fallback at the runtime boundary.
        # Avoid a float64 -> float32 -> float64 round trip in the neural path,
        # because even microscopic rate perturbations can in principle change a
        # stochastic jump ordering under common random numbers.
        if self.trust == 0.0:
            rv=self.physics.mechanistic_rates(float(time),graph,self.bounds)
            self._cache[key]=(None,rv.copy())
            return rv.copy()
        x,A=self._view(time,graph); h=torch.from_numpy(self.anchor_state).unsqueeze(0).to(self.device); dt=torch.tensor([[max(0.,float(time-self.anchor_time))]],dtype=h.dtype,device=self.device); b=torch.tensor(self.bounds.vector(),dtype=h.dtype,device=self.device)
        mech=torch.from_numpy(self.physics.mechanistic_rates(float(time),graph,self.bounds).astype(np.float32)).unsqueeze(0).to(self.device)
        with torch.inference_mode(): st=self.model.flow(h,x,A,dt); rates=self.model.rates(st,x,mech,b,self.bounds.floor,self.trust)
        rv=rates[0].cpu().numpy().astype(float)*applicable_head_mask(graph,self.index); sv=st[0].cpu().numpy().astype(float); self._cache[key]=(sv,rv); return rv.copy()
    def commit_event(self,time,pre_graph,post_graph,rule_id,match):
        pre=self.state_at(time,pre_graph); self.anchor_state=pre.astype(np.float32); self.anchor_time=float(time); self._cache={}; return {"rule":rule_id,"affected":event_affected_mask(rule_id,match,self.index).tolist(),"residual_jump":False,"trust":self.trust}
    def snapshot(self): return {"anchor_time":self.anchor_time,"anchor_state":self.anchor_state.copy(),"trust":self.trust}
    def restore(self,s): self.anchor_time=float(s["anchor_time"]); self.anchor_state=np.asarray(s["anchor_state"],dtype=np.float32).copy(); self.trust=float(s.get("trust",self.trust)); self._cache={}
