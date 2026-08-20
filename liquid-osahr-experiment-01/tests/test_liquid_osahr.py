import math
import numpy as np
import torch

from liquid_osahr.teacher import LinkTeacher, TeacherConfig, FEATURE_NAMES
from liquid_osahr.liquid import CfCCell
from liquid_osahr.models import ModelConfig, CfCHazardModel
from liquid_osahr.training import poisson_process_nll
from liquid_osahr.osahr_bridge import run_twin, TwinConfig


def test_teacher_is_deterministic_and_self_consistent():
    teacher=LinkTeacher(TeacherConfig(horizon=5.0, process_dt=0.05))
    a=teacher.generate(12345, regime='id', profile='fast')
    b=teacher.generate(12345, regime='id', profile='fast')
    for name in ['times','features','interval_dt','event_counts','true_avg_rates','event_times','event_marks']:
        np.testing.assert_array_equal(getattr(a,name),getattr(b,name))
    assert a.features.shape[1] == len(FEATURE_NAMES)
    assert int(a.event_counts.sum()) == len(a.event_marks) == len(a.event_times)
    assert np.all(a.interval_dt > 0)
    assert np.all(a.true_avg_rates >= 0)
    assert math.isclose(float(a.interval_dt.sum()), 5.0, rel_tol=0, abs_tol=2e-5)


def test_cfc_elapsed_time_changes_state():
    torch.manual_seed(1)
    cell=CfCCell(3,5,backbone_units=7)
    x=torch.tensor([[0.2,-0.1,0.7]],dtype=torch.float32)
    h=torch.tensor([[0.1,0.2,-0.2,0.05,0.3]],dtype=torch.float32)
    y0=cell(x,h,torch.tensor([[0.0]]))
    y2=cell(x,h,torch.tensor([[2.0]]))
    assert not torch.allclose(y0,y2)
    assert torch.isfinite(y0).all() and torch.isfinite(y2).all()


def test_neural_hazards_are_positive():
    model=CfCHazardModel(ModelConfig(input_size=len(FEATURE_NAMES), hidden_size=8, backbone_units=12))
    x=torch.randn(2,4,len(FEATURE_NAMES))
    dt=torch.rand(2,4,1)
    mask=torch.ones(2,4,dtype=torch.bool)
    rates=model(x,dt,mask)
    assert rates.shape == (2,4,3)
    assert torch.all(rates > 0)


def test_point_process_nll_matches_analytic_formula():
    rates=torch.tensor([[[2.0,0.5,1.5]]])
    counts=torch.tensor([[[1.0,0.0,2.0]]])
    dt=torch.tensor([[[0.25]]])
    mask=torch.tensor([[True]])
    got=float(poisson_process_nll(rates,counts,dt,mask,reduction='sum'))
    expected=(2.0+0.5+1.5)*0.25 - math.log(2.0) - 2*math.log(1.5)
    assert math.isclose(got,expected,rel_tol=1e-6,abs_tol=1e-6)


def test_osahr_bridge_reproducible_and_crn_seed_independent_of_model_policy():
    teacher=LinkTeacher(TeacherConfig(horizon=4.0,process_dt=0.05))
    f=teacher.generate(101,regime='id',profile='fast')
    r=teacher.generate(202,regime='id',profile='robust')
    cfg=TwinConfig(horizon=4.0,arrivals_stop=3.0,n_ues=2)
    kwargs=dict(regime='id',scenario=0,replicate=0,fast_times=f.times,fast_rates=f.true_avg_rates,
                robust_times=r.times,robust_rates=r.true_avg_rates,root_seed=999,cfg=cfg)
    a=run_twin(hazard_model='oracle',policy='throughput',verify_incremental=True,**kwargs)
    b=run_twin(hazard_model='oracle',policy='throughput',verify_incremental=True,**kwargs)
    c=run_twin(hazard_model='different-label',policy='semantic',verify_incremental=False,**kwargs)
    assert a.seed == b.seed == c.seed
    assert a.state_hash == b.state_hash
    assert a.events == b.events
    assert a.generated == b.generated


def test_paired_sparsification_preserves_physical_events_and_exposure():
    from liquid_osahr.data import sparsify_trace
    teacher=LinkTeacher(TeacherConfig(horizon=8.0,process_dt=0.05))
    t=teacher.generate(707,regime='id',profile='fast')
    s=sparsify_trace(t,keep_probability=0.4,seed=99)
    np.testing.assert_array_equal(s.event_times,t.event_times)
    np.testing.assert_array_equal(s.event_marks,t.event_marks)
    assert int(s.event_counts.sum()) == int(t.event_counts.sum())
    assert math.isclose(float(s.interval_dt.sum()),float(t.interval_dt.sum()),rel_tol=0,abs_tol=2e-5)
    # Integrated teacher hazards must be exactly preserved up to float roundoff.
    a=(t.true_avg_rates*t.interval_dt[:,None]).sum(axis=0)
    b=(s.true_avg_rates*s.interval_dt[:,None]).sum(axis=0)
    np.testing.assert_allclose(a,b,rtol=2e-5,atol=2e-5)
    assert len(s.times) < len(t.times)


def test_teacher_down_up_events_respect_binary_link_state():
    teacher=LinkTeacher(TeacherConfig(horizon=20.0,process_dt=0.05))
    t=teacher.generate(808,regime='high_mobility',profile='fast')
    jumps=[int(m) for m in t.event_marks if int(m) in (1,2)]
    blocked=False
    for m in jumps:
        if m==1:
            assert not blocked
            blocked=True
        else:
            assert blocked
            blocked=False


def test_teacher_lagged_event_features_are_strictly_causal():
    teacher=LinkTeacher(TeacherConfig(horizon=10.0,process_dt=0.05))
    t=teacher.generate(919,regime='id',profile='fast')
    # The first observation has no completed interval behind it.
    np.testing.assert_array_equal(t.features[0,8:11],np.zeros(3,dtype=np.float32))
    if len(t.times)>1:
        expected_service=t.event_counts[:-1,0]/np.maximum(t.interval_dt[:-1],1e-6)
        np.testing.assert_allclose(t.features[1:,8],expected_service,rtol=0,atol=1e-6)
        np.testing.assert_array_equal(t.features[1:,9],t.event_counts[:-1,1])
        np.testing.assert_array_equal(t.features[1:,10],t.event_counts[:-1,2])


def test_ltc_cell_is_finite_and_elapsed_time_matters():
    from liquid_osahr.liquid import FullyConnectedLTCCell
    torch.manual_seed(2)
    cell=FullyConnectedLTCCell(3,5,ode_unfolds=4,seed=42)
    x=torch.tensor([[0.3,-0.2,0.1]],dtype=torch.float32)
    h=torch.tensor([[0.1,0.0,-0.1,0.2,-0.2]],dtype=torch.float32)
    a=cell(x,h,torch.tensor([[0.1]]))
    b=cell(x,h,torch.tensor([[1.7]]))
    assert torch.isfinite(a).all() and torch.isfinite(b).all()
    assert not torch.allclose(a,b)


def test_point_process_nll_has_finite_gradients():
    raw=torch.tensor([[[0.2,-0.5,1.0]]],requires_grad=True)
    rates=torch.nn.functional.softplus(raw)+1e-5
    counts=torch.tensor([[[2.0,0.0,1.0]]])
    dt=torch.tensor([[[0.7]]])
    mask=torch.tensor([[True]])
    loss=poisson_process_nll(rates,counts,dt,mask,reduction='sum')
    loss.backward()
    assert torch.isfinite(loss)
    assert raw.grad is not None and torch.isfinite(raw.grad).all()


def test_sparsification_recomputes_lags_without_future_counts():
    from liquid_osahr.data import sparsify_trace
    teacher=LinkTeacher(TeacherConfig(horizon=12.0,process_dt=0.05))
    t=teacher.generate(1234,regime='id',profile='robust')
    s=sparsify_trace(t,keep_probability=0.32,seed=23)
    np.testing.assert_array_equal(s.features[0,8:11],np.zeros(3,dtype=np.float32))
    if len(s.times)>1:
        np.testing.assert_allclose(s.features[1:,8],s.event_counts[:-1,0]/np.maximum(s.interval_dt[:-1],1e-6),atol=1e-6)
        np.testing.assert_array_equal(s.features[1:,9],s.event_counts[:-1,1])
        np.testing.assert_array_equal(s.features[1:,10],s.event_counts[:-1,2])


def test_same_physical_trace_sparsification_is_reproducible():
    from liquid_osahr.data import sparsify_trace
    teacher=LinkTeacher(TeacherConfig(horizon=8.0,process_dt=0.05))
    t=teacher.generate(4444,regime='id',profile='fast')
    a=sparsify_trace(t,keep_probability=.45,seed=77)
    b=sparsify_trace(t,keep_probability=.45,seed=77)
    for name in ['times','features','interval_dt','event_counts','true_avg_rates','event_times','event_marks']:
        np.testing.assert_array_equal(getattr(a,name),getattr(b,name))


def test_seed_context_can_couple_paired_sparse_to_id_stream():
    teacher=LinkTeacher(TeacherConfig(horizon=2.0,process_dt=0.05))
    f=teacher.generate(303,regime='id',profile='fast')
    r=teacher.generate(404,regime='id',profile='robust')
    cfg=TwinConfig(horizon=2.0,arrivals_stop=1.5,n_ues=1)
    common=dict(policy='throughput',scenario=2,replicate=1,fast_times=f.times,fast_rates=f.true_avg_rates,robust_times=r.times,robust_rates=r.true_avg_rates,root_seed=77,cfg=cfg)
    a=run_twin(hazard_model='a',regime='id',**common)
    b=run_twin(hazard_model='b',regime='paired_sparse',seed_context='id',**common)
    assert a.seed==b.seed


def test_teacher_history_features_are_strictly_lagged_not_current_labels():
    t=LinkTeacher(TeacherConfig(horizon=6.0)).generate(909,regime='id',profile='robust')
    np.testing.assert_array_equal(t.features[0,8:],np.zeros(3,dtype=np.float32))
    if len(t.times)>1:
        np.testing.assert_allclose(t.features[1:,8],t.event_counts[:-1,0]/t.interval_dt[:-1],rtol=1e-6,atol=1e-6)
        np.testing.assert_array_equal(t.features[1:,9],t.event_counts[:-1,1])
        np.testing.assert_array_equal(t.features[1:,10],t.event_counts[:-1,2])
