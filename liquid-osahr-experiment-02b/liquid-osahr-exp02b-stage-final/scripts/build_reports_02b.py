#!/usr/bin/env python3
from __future__ import annotations
from pathlib import Path
import json, pandas as pd, pickle, platform, sys

ROOT=Path(__file__).resolve().parents[1]
# Allow direct execution from scripts/ without requiring an editable install.
for _path in (ROOT,):
    _s = str(_path)
    if _s not in sys.path:
        sys.path.insert(0, _s)
A=ROOT/'artifacts'
cal=json.loads((A/'intervention_calibration_multi.json').read_text())
train=json.loads((A/'training_summary.json').read_text())
ood=json.loads((A/'ood_hazard_evaluation.json').read_text())
pvc=json.loads((A/'predictive_vs_counterfactual.json').read_text())
confirm=pd.read_csv(A/'confirmatory_release.csv')
pilot=pd.read_csv(A/'counterfactual_release.csv')
paired=json.loads((A/'confirmatory_paired_comparisons.json').read_text())
analyses={m:json.loads((A/f'confirmatory_analysis_{m}.json').read_text()) for m in ['goal_utility_ratio','critical_success_rate','mean_latency']}
with open(A/'ran_dataset.pkl','rb') as f: ds=pickle.load(f)

def fmt(x,n=5): return f'{x:.{n}f}'
def table(rows,cols,headers=None):
    headers=headers or cols
    lines=['| '+' | '.join(headers)+' |','|'+'|'.join(['---']*len(cols))+'|']
    for r in rows:
        lines.append('| '+' | '.join(str(r.get(c,'')) for c in cols)+' |')
    return '\n'.join(lines)

def result_rows(metric):
    out=[]
    for reg,rd in analyses[metric]['regimes'].items():
        for model,v in rd['models'].items():
            out.append({'Regime':reg,'Model':model,'Effect MAE':fmt(v['effect_mae']),'Level MAE':fmt(v['level_mae']),'Sign':fmt(v['sign_agreement'],2)})
    return out

cal_rows=[]
for r in cal['grid']:
    cal_rows.append({'alpha':r['trust'],'Intervention MAE':fmt(r['intervention_effect_mae']),'Predictive NMAE':fmt(r['predictive_nmae']),'Objective':fmt(r['objective']),'Worst-regime MAE':fmt(r['worst_regime_mae'])})

haz_rows=[]
for reg in ['id','high_mobility','high_stress','weak_channel']:
    best_pred=pvc[reg]['best_predictive_trust'];best_cf=pvc[reg]['best_counterfactual_trust']
    haz_rows.append({'Regime':reg,'Best hazard alpha':best_pred,'Best counterfactual alpha':best_cf,'Spearman':fmt(pvc[reg]['spearman'],2)})

pair_rows=[]
for r in paired:
    if r['metric']=='goal_utility_ratio':
        pair_rows.append({'Regime':r['regime'],'Residual':r['model'],'Delta abs effect error':fmt(r['delta_abs_effect_error_vs_mechanistic']),'95% CI':f"[{fmt(r['ci_lo'])}, {fmt(r['ci_hi'])}]"})

oracle_rows=[]
for reg,rd in analyses['goal_utility_ratio']['regimes'].items():
    x=rd['oracle_effect'];oracle_rows.append({'Regime':reg,'Oracle semantic-throughput':fmt(x['mean']),'95% CI':f"[{fmt(x['lo'])}, {fmt(x['hi'])}]"})

report=f'''# Liquid-OSAHR Experiment 02B — Intervention-Calibrated Standards-Informed RAN Twin

**Release:** 0.2.0  
**Experiment status:** completed research prototype / confirmatory synthetic study  
**Primary question:** can a mechanistically anchored liquid-neural residual improve a stochastic RAN digital twin *without sacrificing counterfactual policy fidelity*?

## 1. Executive result

Experiment 02B implements a standards-informed FR1 RAN surrogate, a simplified engineering/mechanistic hazard prior, a topology-coupled CfC residual with globally bounded stochastic intensities, exact OSAHR thinning, intervention-based trust calibration, external srsRAN/5G-LENA telemetry adapters, and a new untouched confirmatory study after the calibration protocol was frozen.

The headline result is deliberately nontrivial:

1. full residual trust (`alpha=1`) improves factual hazard identification over the mechanism on validation and on every OOD hazard set;
2. intervention calibration on 18 independent scenarios nevertheless chooses `alpha=0`, i.e. the mechanistic fallback;
3. that choice is calibration-stable (18/18 leave-one-scenario-out folds; {cal['selection_stability']['stratified_bootstrap']['selected_frequency']['0.0']*100:.2f}% of 20,000 stratified bootstrap recalibrations);
4. on a **new untouched 400-run confirmatory holdout**, no single alpha dominates counterfactually: ID favors `alpha=.5`, high-stress goal utility favors `.25`, high mobility and weak channel favor the mechanism for that estimand, while full trust is best for some latency effects;
5. therefore **predictive trust and intervention trust are different quantities, and one global scalar trust coefficient is not sufficient**.

This is stronger evidence for the core OSAHR design principle than a simple neural-model win would have been: the structural stochastic twin must validate the causal consequences of interventions, not only the accuracy of local predictions.

## 2. Scope and exactness boundary

02B is **not** a 3GPP-conformance simulator and is **not** presented as a replacement for 5G-LENA/ns-3, srsRAN, Sionna RT, or commercial RF twins. Those packages were not available locally in this execution environment. Instead 02B implements a deterministic standards-informed system-level surrogate whose large-scale propagation follows the 3GPP TR 38.901 UMi-Street-Canyon form and whose observable telemetry surface mirrors practical RAN metrics exposed by srsRAN/O-RAN paths.

Exact conditional semantics:

- OSAHR typed matching and DPO applicability;
- graph rewrites and deterministic replay;
- common-random-number seed partitioning;
- neural/global rate bounds;
- thinning conditional on the declared continuously varying bounded rates;
- candidate-time state queries are pure and rejected thinning candidates do not commit liquid state.

Model-dependent approximations:

- analytical/stochastic surrogate instead of a full NR PHY/MAC/RLC stack;
- smooth LOS mixing rather than sampled 38.901 channel condition state;
- bounded Doppler/fading surrogate rather than a clustered delay-line channel;
- CQI, BLER/drop, PRB/load and throughput proxies;
- simple A3-like handover pressure rather than complete RRC measurement/event semantics;
- synthetic application/task utility.

## 3. Standards-informed RAN layer

The site model uses 3.5 GHz, 40 MHz, two gNBs, four mobile UEs and two edge/MEC resources. The implemented telemetry includes:

`RSRP`, `SINR`, `CQI`, spectral efficiency, neighbor margin, speed, utilization, drop probability, throughput proxy.

Large-scale UMi path loss uses the 38.901 form implemented in `RANPhysics._pathloss_umi`; stochastic scenario variation is encoded into deterministic seed-conditioned shadow/fading fields so a physical realization is a pure function of `(scenario, seed, time, graph)`. This makes common-random-number policy comparisons meaningful.

02B additionally ships adapters for:

- srsRAN JSON metrics / E2SM-KPM terminal metric names;
- 5G-LENA/ns-3 CSV trace sources through an explicit alias map.

See `TELEMETRY_CONTRACT.md` and `canonical_kpm_schema.json`.

## 4. Mechanism + bounded residual

Let the engineering prior for an event head be `lambda_mech`, with certified global ceiling `B` and floor `eps`. The learned residual model is

```text
p_mech = (lambda_mech - eps) / (B - eps)
z_mech = logit(p_mech)
r = L * tanh(r_CfC(H, X, G))
lambda_alpha = eps + (B-eps) * sigmoid(z_mech + alpha*r)
```

where `L` is a fixed residual-logit limit and `alpha in [0,1]` is the neural trust parameter.

Properties:

- `alpha=0` is now an **exact runtime identity** to the mechanistic hazard, bypassing float32 neural conversion;
- all nonzero-trust hazards remain inside the same certified global OSAHR bound;
- topology still determines legal rewrite occurrences;
- the neural model corrects rates, not ontology or rewrite legality;
- unlike 02A, there is no free learned post-event jump map in 02B.

The trained residual CfC has **{train['params']:,} parameters**.

## 5. Identification dataset

Synthetic RAN traces:

| Split | Traces | Frames |
|---|---:|---:|
| Train | {len(ds['train'])} | {sum(len(t.times) for t in ds['train'])} |
| Validation | {len(ds['val'])} | {sum(len(t.times) for t in ds['val'])} |
| Test | {len(ds['test'])} | {sum(len(t.times) for t in ds['test'])} |

The residual was trained against oracle event intensities while receiving only telemetry/topology plus the mechanistic rate. Validation-selected predictive trust is **alpha={train['predictive_trust']}**.

Validation hazard error:

| Trust | NMAE | log-RMSE |
|---:|---:|---:|
'''
for r in train['predictive_grid']:
    report+=f"| {r['trust']:.2f} | {r['nmae']:.6f} | {r['log_rmse']:.6f} |\n"

report+=f'''

The mechanistic validation NMAE is {train['predictive_grid'][0]['nmae']:.6f}; full residual trust reduces it to {train['predictive_grid'][-1]['nmae']:.6f}.

## 6. Intervention calibration

The primary calibration target is not hazard prediction. For each physical scenario `s`, let

`Delta_s = E[goal utility | semantic, s] - E[goal utility | throughput, s]`.

Trust is evaluated against absolute oracle policy-effect error:

`|Delta_hat(alpha,s) - Delta_oracle(s)|`.

The final multi-regime calibration set contains **18 independent scenarios** (6 ID, 6 high-mobility, 6 high-stress), one stochastic replicate per arm, and is disjoint in root seed from the confirmatory holdout. The objective is mean intervention-effect MAE plus `0.1 * predictive_NMAE`.

{table(cal_rows,['alpha','Intervention MAE','Predictive NMAE','Objective','Worst-regime MAE'])}

Selected robust trust:

**alpha = {cal['selected_trust']:.2f}**.

Stability audit:

- leave-one-scenario-out: alpha=0 in **18/18** folds;
- stratified bootstrap recalibration: alpha=0 in **{cal['selection_stability']['stratified_bootstrap']['selected_frequency']['0.0']*100:.2f}%** of 20,000 replicates.

This is an intentionally conservative result: the intervention calibration says that, given its calibration sample and loss, the residual should not be trusted globally for policy selection.

## 7. Why a new confirmatory holdout was necessary

An earlier 360-run pilot was inspected while the calibration protocol was still being enlarged. To avoid presenting an analyst-adaptive holdout as confirmatory, 02B froze:

- the mechanism;
- the CfC checkpoint;
- the alpha grid;
- predictive trust;
- the 18-scenario intervention-calibration procedure;
- the primary goal-utility policy-effect error.

Only then was a new root seed (`920218`) used for the final confirmatory study.

## 8. Confirmatory design

The untouched release contains **{len(confirm)} trajectories**:

- 4 regimes: ID, high mobility, high stress, weak channel;
- 5 independent physical scenarios per regime = **20 independent scenarios**;
- 2 stochastic replicates per model/policy arm;
- 5 model/trust arms;
- throughput and semantic policies.

Thus

`4 * 5 * 2 * 5 * 2 = 400`.

The scenario is the inferential unit. Replicates are averaged inside scenario before bootstrap inference. All model/policy arms within the same `(scenario, replicate)` use the same root stochastic seed and physical realization.

Models:

- `oracle`;
- `mechanistic_calibrated` (`alpha=0`, the frozen robust calibration);
- `residual_quarter` (`alpha=.25`, sensitivity arm);
- `residual_idcal` (`alpha=.5`, ID-only calibration arm);
- `residual_predictive` (`alpha=1`, predictive optimum).

The `weak_channel` regime was not part of multi-regime intervention calibration and serves as an additional transport/OOD test.

## 9. Oracle policy effects

Positive goal-utility effect means semantic policy is better; negative means throughput policy is better.

{table(oracle_rows,['Regime','Oracle semantic-throughput','95% CI'])}

The oracle itself therefore rejects any claim that semantic routing is universally superior in this synthetic world. In the five-scenario ID holdout, the oracle effect is negative and its scenario-bootstrap interval excludes zero. The other goal-utility regimes have intervals spanning zero.

## 10. Confirmatory goal-utility fidelity

{table(result_rows('goal_utility_ratio'),['Regime','Model','Effect MAE','Level MAE','Sign'])}

No single trust level wins every regime.

Paired difference in absolute policy-effect error versus the frozen mechanistic/calibrated arm (negative = residual better):

{table(pair_rows,['Regime','Residual','Delta abs effect error','95% CI'])}

Most notable within this five-scenario-per-regime design:

- ID `alpha=.5`: improvement `-0.04561`, bootstrap CI `[-0.10541, -0.00305]`;
- high stress `alpha=.25`: improvement `-0.10842`, CI `[-0.20299, -0.03373]`;
- weak-channel `alpha=.25`: degradation `+0.02667`, CI `[+0.00037, +0.07408]`;
- macro `alpha=.25`: improvement `-0.02573`, but the interval reaches essentially zero.

These are scenario-bootstrap intervals over only five independent scenarios per regime; they should be read as confirmatory *within this synthetic experimental design*, not external telecom effect sizes.

## 11. Factual hazard generalization versus counterfactual fidelity

Twenty additional OOD hazard traces (5 per regime) were generated with a separate root seed. Full residual trust gives the lowest hazard NMAE in **every regime**.

Yet the best goal-utility counterfactual trust differs:

{table(haz_rows,['Regime','Best hazard alpha','Best counterfactual alpha','Spearman'])}

Detailed OOD hazard NMAE:

| Regime | alpha=0 | .25 | .50 | .75 | 1.0 |
|---|---:|---:|---:|---:|---:|
'''
for reg in ['id','high_mobility','high_stress','weak_channel']:
    ks=['0','0.25','0.5','0.75','1.0']; vals=[ood[reg][k]['nmae'] for k in ks]
    report+=f"| {reg} | "+' | '.join(f'{v:.5f}' for v in vals)+' |\n'

report+=f'''

This is the strongest 02B inference:

> **The model can become more accurate about local event intensities while becoming less reliable about the effect of changing policy.**

The failure is therefore not reducible to poor hazard prediction.

## 12. Mechanism misspecification versus residual overtrust

The calibration traces reveal two distinct failure classes.

**Residual overtrust:** increasing alpha creates counterfactual error that the mechanistic fallback avoids. Shrinkage can address this.

**Structural/mechanistic misspecification:** some scenarios produce essentially the same large policy-effect error for all alpha values, including alpha=0. No residual trust shrinkage can fix a causal abstraction that omitted the relevant mechanism.

This distinction matters operationally. A trust controller should not interpret every counterfactual disagreement as a request to reduce neural influence; some failures require changing the graph ontology, physical model, intervention semantics, or observation model.

## 13. External simulator/testbed bridge

02B now contains executable adapters rather than only a conceptual integration plan.

### srsRAN

`SrsRANKPMAdapter` supports terminal names documented on srsRAN's E2SM-KPM path, including:

- CQI / RSRP / RSRQ;
- `DRB.UEThpDl`, `DRB.UEThpUl`;
- `DRB.RlcPacketDropRateDl`;
- `DRB.PacketSuccessRateUlgNBUu`;
- `DRB.RlcSduTransmittedVolumeDL/UL`.

It can also consume JSON-lines captured from the srsRAN JSON/WebSocket metric output. Unknown fields are ignored; missing required time is rejected rather than fabricated.

### 5G-LENA

`FiveGLenaCSVAdapter` provides an explicit alias map for selected ns-3/5G-LENA trace sources. Since 5G-LENA exposes multiple PHY/MAC/application trace formats rather than one universal CSV, the adapter is intentionally extendable and requires an explicit simulation-time field.

## 14. Runtime audit

Confirmatory study:

- trajectories: **{len(confirm)}**;
- independent scenarios: **{confirm.scenario.nunique()}**;
- total OSAHR events: **{int(confirm.events.sum())}**;
- max events in one trajectory: **{int(confirm.events.max())}**;
- thinning candidate rejections: **{int(confirm.thinning_rejections.sum())}**;
- unique augmented final hashes: **{confirm.final_hash.nunique()} / {len(confirm)}**;
- common-root-seed violations across model/policy arms: **0**.

The first confirmatory residual run additionally executed with incremental matching continuously checked against the exhaustive reference matcher.

## 15. Statistical interpretation

The confirmatory design uses five independent scenarios per regime. This is a meaningful improvement over the pilot but still a small-sample mechanistic experiment. Bootstrap intervals quantify scenario sensitivity inside the declared scenario generator; they do not establish population-level effects for real networks.

The correct epistemic reading is:

- the implementation demonstrates the mechanism and exposes failure modes;
- it provides a reproducible counterfactual-validation protocol;
- it does **not** establish field performance in a deployed RAN;
- external validation now requires 5G-LENA/srsRAN/O-RAN or measured traces plus intervention regimes with known/observable policy outcomes.

## 16. What 02B establishes

1. A standards-informed RAN layer can be coupled to exact OSAHR stochastic structural semantics.
2. A CfC can be constrained to a bounded residual over engineering hazard models without controlling rewrite legality.
3. `alpha=0` can be made an exact semantic fallback to the mechanism.
4. Predictive residual correction materially improves hazard identification.
5. Intervention-based calibration can prefer drastically less neural trust than predictive calibration.
6. That calibration decision itself can fail to transport to fresh regimes/scenarios.
7. Local predictive fidelity and downstream counterfactual fidelity are empirically separable in the same closed stochastic graph twin.
8. A single global trust scalar is inadequate for a trustworthy Network Digital Twin.
9. External srsRAN/5G-LENA telemetry can now enter through a stable canonical schema.

## 17. What 02B does not establish

- 5G-LENA/ns-3 equivalence;
- srsRAN/Open-RAN field validation;
- standards conformance of the synthetic handover or scheduling rules;
- superiority of CfC over every recurrent architecture;
- real-world semantic-routing gains;
- that intervention calibration from synthetic oracle access is directly available in deployment;
- that bootstrap intervals over five generated scenarios are telecom population confidence intervals.

## 18. Optimal next architecture

02B rules out both extremes:

`always trust mechanism` and `always trust neural residual`.

The next architecture should represent trust as a state- and query-dependent epistemic variable:

`alpha = alpha(regime, entity, event head, uncertainty, intervention, estimand)`.

The most defensible implementation route is:

1. replace synthetic KPMs with 5G-LENA and/or srsRAN/O-RAN telemetry through the shipped adapters;
2. retain an explicit mechanistic backbone;
3. learn bounded residuals with ensemble/epistemic uncertainty;
4. propagate **model-trust uncertainty** through OSAHR counterfactual ensembles instead of returning one trajectory distribution;
5. calibrate separately for service, failure, recovery and handover heads;
6. validate policy ranking / directional sensitivity on intervention scenarios, not only NLL/RMSE;
7. detect model-inadequacy cases where all trust levels disagree with oracle/observed interventions;
8. only after shadow validation compile reduced decisions into Non-RT RIC/rApp or Near-RT control logic.

## 19. Primary-source research grounding

- 3GPP TS 28.561 — Management and orchestration; Management aspects of Network Digital Twins (Release 19). https://www.3gpp.org/dynareport/28561.htm
- 3GPP, “The Network Digital Twin: Enabling Network Intelligence and Automation,” 27 Apr 2026. https://www.3gpp.org/technologies/digital-twin1
- ETSI / 3GPP TR 38.901, channel model for 0.5–100 GHz, including UMi Street Canyon. https://www.etsi.org/deliver/etsi_tr/138900_138999/138901/
- srsRAN Project, JSON Metrics output. https://docs.srsran.com/projects/project/en/latest/user_manuals/source/outputs.html
- srsRAN Project, O-RAN NearRT-RIC and E2SM-KPM application note. https://docs.srsran.com/projects/project/en/latest/tutorials/source/near-rt-ric/source/index.html
- 5G-LENA NR module and feature documentation. https://cttc-lena.gitlab.io/nr/manual/nr-module.html
- O-RAN ALLIANCE Digital Twin Platform / AI and Open RAN research announcement, 22 May 2025. https://www.o-ran.org/press-releases
- Hasani et al., Closed-form continuous-time neural networks (CfC), Nature Machine Intelligence / arXiv:2106.13898.
- Lemaire et al., Exact simulation of jump times of a class of PDMPs, arXiv:1602.07871.
- Laudy, Digital Twin Counterfactual Framework, arXiv:2604.01325 (2026).
- Jimenez Agudelo et al., Towards Trustworthy 6G Network Digital Twins, arXiv:2604.14787 (2026).

## 20. Apex interpretation

02B began with the hypothesis that intervention calibration would tell us *how much* to trust a liquid neural residual.

The result is more important:

> **Trust is not a scalar property of a digital-twin model. It is a property of a model, regime, intervention, outcome, and causal query together.**

The same full residual model was the best local hazard predictor in every tested regime, while different trust levels were optimal for different counterfactual questions. For an OSAHR-style twin, the correct product is therefore not “the most accurate network predictor.” It is a system that carries competing mechanistic/neural hypotheses into counterfactual simulation and exposes where a decision is robust—or fragile—to model trust.
'''
(ROOT/'EXPERIMENT_REPORT.md').write_text(report)

readme='''# Liquid-OSAHR Experiment 02B\n\nIntervention-calibrated, standards-informed RAN digital-twin experiment built on OSAHR.\n\n## Core architecture\n\n`RAN mechanism -> bounded CfC residual -> certified event hazards -> typed OSAHR rewrites -> counterfactual policy evaluation`\n\nThe project includes a 3GPP TR 38.901-informed RAN surrogate, exact OSAHR thinning, mechanistic and residual hazard fields, trust calibration, srsRAN/5G-LENA telemetry adapters, synthetic training data, frozen calibration artifacts, an untouched 400-run confirmatory study, and full tests.\n\n## Important result\n\nFull neural trust gives the best local hazard prediction across all tested regimes, but not the best policy-effect fidelity. The final 18-scenario intervention calibration selects alpha=0, while the untouched holdout shows the best alpha is query/regime dependent. See `EXPERIMENT_REPORT.md`.\n\n## Run tests\n\n```bash\npython -m pytest -q\n```\n\n## Normalize external telemetry\n\n```bash\npython scripts/ingest_telemetry.py srsran-jsonl examples/srsran_kpm_sample.jsonl\npython scripts/ingest_telemetry.py 5glena-csv examples/5glena_trace_sample.csv\n```\n\nSee `TELEMETRY_CONTRACT.md` for the source boundary and unit/provenance requirements.\n\n## Key artifacts\n\n- `artifacts/residual_cfc.pt` — trained residual checkpoint\n- `artifacts/training_summary.json` — predictive calibration\n- `artifacts/intervention_calibration_multi.json` — frozen 18-scenario intervention calibration\n- `artifacts/confirmatory_release.csv` — 400 untouched confirmatory trajectories\n- `artifacts/confirmatory_summary.csv` — compact results\n- `artifacts/ood_hazard_evaluation.json` — factual OOD hazard audit\n- `artifacts/predictive_vs_counterfactual.json` — prediction/intervention mismatch audit\n\n## Scope warning\n\nThe shipped radio layer is standards-informed but is not a full NR protocol simulator. The code deliberately includes adapters so future experiments can replace it with 5G-LENA, srsRAN/O-RAN, or measured telemetry without changing OSAHR's structural semantics.\n'''
(ROOT/'README.md').write_text(readme)

arch='''# Liquid-OSAHR 02B Architecture\n\n## 1. Augmented state\n\nThe authoritative stochastic state is the OSAHR graph/runtime state plus the continuous residual state and deterministic physical realization. OSAHR remains authoritative about type legality, DPO applicability, boundaries, event timing, event sourcing and replay.\n\n## 2. Layers\n\n1. **RAN physical surrogate**: deterministic-in-seed continuous mobility, 38.901-informed path loss, shadow/fading, inter-cell SINR, KPM proxies.\n2. **Mechanistic hazard prior**: deliberately incomplete engineering functions for service, failure/recovery and handover.\n3. **Residual CfC**: graph/topology-conditioned continuous hidden state and bounded logit correction.\n4. **Trust layer**: alpha controls the residual correction; alpha=0 bypasses the neural numerical path exactly.\n5. **OSAHR runtime**: exact typed occurrence set + bounded thinning + structural rewrite.\n6. **Counterfactual evaluator**: common-random-number paired policy rollouts and scenario-level inference.\n\n## 3. Bounded residual semantics\n\nFor each head with floor eps and global bound B:\n\n```text\nq = clip((lambda_mech-eps)/(B-eps))\nz = logit(q)\nr = L*tanh(neural_residual)\nlambda = eps + (B-eps)*sigmoid(z + alpha*r)\n```\n\nFor alpha=0, runtime code returns `lambda_mech` directly. This is stronger than algebraic equivalence: it avoids precision-induced stochastic clock perturbation.\n\n## 4. Purity and caching\n\nCandidate-time field evaluation is observational. Neural flow is cached by `(candidate_time, graph_epoch, anchor_time)` so all rewrite occurrences at the same candidate time share one liquid evaluation. Rejected thinning candidates never commit the liquid anchor. Accepted events commit the pre-event state at exactly the event time, then OSAHR changes topology.\n\n## 5. Common random numbers\n\nPhysical seeds and stochastic runtime seeds depend on scenario/replicate, not candidate model/policy. This is tested. Divergent models can of course diverge pathwise after selecting different events; CRN is a variance-reduction coupling, not an assertion of identical event sequences.\n\n## 6. Intervention calibration\n\nCalibration is a separate data split. It minimizes oracle policy-effect error, not trajectory MSE. The final protocol uses six scenarios each from ID/high-mobility/high-stress and freezes alpha before the confirmatory root seed is analyzed.\n\n## 7. External telemetry\n\n`telemetry.py` defines a stable source-neutral record plus srsRAN and 5G-LENA adapters. External source semantics and units remain explicit; missing fields are not fabricated.\n\n## 8. Exactness boundary\n\nThe stochastic process is exact relative to its declared bounded hazard functions. Fidelity of those hazards to real NR is a model-validation question. The synthetic RAN layer must not be described as standards-conformant PHY/MAC behavior.\n'''
(ROOT/'ARCHITECTURE.md').write_text(arch)

spec='''# Experiment 02B Protocol\n\n## Primary objective\n\nEvaluate whether a bounded liquid-neural residual over a mechanistic RAN prior improves counterfactual policy-effect fidelity in an OSAHR network digital twin.\n\n## Frozen hierarchy\n\n1. Train residual on synthetic oracle hazards.\n2. Select predictive alpha on validation hazard NMAE.\n3. Select intervention alpha on a disjoint calibration set using goal-utility policy-effect MAE plus a small predictive penalty.\n4. Audit calibration stability by leave-one-scenario-out and stratified bootstrap.\n5. Freeze model, trust grid, objective, calibration set and confirmatory seed protocol.\n6. Evaluate a new untouched root seed across ID/high mobility/high stress/weak channel.\n\n## Independent unit\n\nPhysical scenario. Stochastic replicates are averaged inside scenario.\n\n## Confirmatory primary endpoint\n\nAbsolute error in the semantic-vs-throughput goal-utility effect relative to oracle.\n\n## Secondary endpoints\n\n- goal-utility level MAE;\n- critical-success effect/level error;\n- mean-latency effect/level error;\n- event/hazard OOD NMAE and log-RMSE;\n- sign agreement.\n\n## Confirmatory design\n\n4 regimes x 5 scenarios x 2 stochastic replicates x 5 model/trust arms x 2 policies = 400 runs.\n\n## Calibration design\n\n3 regimes x 6 scenarios with alpha grid {0,.25,.5,.75,1}; one stochastic replicate per arm at 2 s horizon; separate root seed.\n\n## Reporting rule\n\nNo claim of real-network efficacy is permitted from this experiment. All empirical effect magnitudes refer only to the declared synthetic scenario generator.\n'''
(ROOT/'EXPERIMENT_SPEC.md').write_text(spec)

research='''# Research Notes — Experiment 02B\n\n## Network Digital Twins\n\n3GPP Release 19 TS 28.561 formalizes management aspects of Network Digital Twins, and 3GPP's 2026 NDT overview describes twins as virtual replicas intended to capture network attributes, behavior and interactions for intelligence/automation and pre-deployment evaluation.\n\nO-RAN has an active Digital Twin research program and uses DTs in AI/Open-RAN experimentation. This supports positioning OSAHR above packet/RF simulation as a shadow causal/control twin rather than as a replacement radio simulator.\n\n## RAN physics / simulator grounding\n\nThe synthetic layer uses the UMi Street Canyon large-scale path-loss form from 3GPP TR 38.901. It does not implement the full clustered channel, antenna, PHY, scheduler, HARQ or RLC stack. 5G-LENA is the target high-fidelity simulator bridge because its NR module supports 38.901 channel modeling and system-level calibration.\n\n## Operational telemetry grounding\n\nsrsRAN Project supports JSON metrics over WebSocket and an O-RAN E2 interface. Its documented E2SM-KPM application note exposes CQI/RSRP/RSRQ plus ORAN-defined throughput/drop/success/volume metrics. 02B's canonical KPM adapter covers that conservative subset.\n\n## Counterfactual validation\n\nRecent 2026 digital-twin causal-validation work emphasizes that prediction and counterfactual validity require different assumptions/tests. 02B operationalizes that distinction by evaluating oracle intervention effects directly in a synthetic world where those effects are observable. A recent 6G NDT paper also proposes directional/intervention-sensitive validation rather than relying only on regression accuracy.\n\n## Neural continuous-time component\n\nCfC provides a closed-form continuous-time recurrent architecture. In 02B, it is not allowed to generate graph structure or legal transitions. It learns only a bounded residual correction to event intensities.\n\n## Exact stochastic simulation\n\nOSAHR uses thinning with architectural global rate ceilings. This is aligned with exact PDMP/thinning theory: exactness depends on a valid dominating intensity, which is guaranteed here by construction.\n\n## Key references\n\n- 3GPP TS 28.561: https://www.3gpp.org/dynareport/28561.htm\n- 3GPP NDT overview: https://www.3gpp.org/technologies/digital-twin1\n- 3GPP TR 38.901 / ETSI: https://www.etsi.org/deliver/etsi_tr/138900_138999/138901/\n- srsRAN metrics: https://docs.srsran.com/projects/project/en/latest/user_manuals/source/outputs.html\n- srsRAN NearRT-RIC/E2SM-KPM: https://docs.srsran.com/projects/project/en/latest/tutorials/source/near-rt-ric/source/index.html\n- 5G-LENA NR module: https://cttc-lena.gitlab.io/nr/manual/nr-module.html\n- O-RAN press releases / Digital Twin platform: https://www.o-ran.org/press-releases\n- Hasani et al., CfC: https://arxiv.org/abs/2106.13898\n- Exact PDMP jump simulation: https://arxiv.org/abs/1602.07871\n- Digital Twin Counterfactual Framework: https://arxiv.org/abs/2604.01325\n- Trustworthy 6G NDT counterfactual validation: https://arxiv.org/abs/2604.14787\n'''
(ROOT/'RESEARCH_NOTES.md').write_text(research)

manifest={
 'experiment':'Liquid-OSAHR 02B','version':'0.2.0','status':'completed research prototype',
 'dataset_seed':26021802,'training_seed':260218,'id_calibration_root_seed':99117,'multiregime_calibration_root_seed':771177,'pilot_root_seed':620218,'confirmatory_root_seed':920218,'ood_hazard_root_seed':332211,
 'residual_parameters':train['params'],'predictive_trust':train['predictive_trust'],'id_intervention_trust':json.loads((A/'intervention_calibration.json').read_text())['selected_trust'],'robust_intervention_trust':cal['selected_trust'],
 'calibration':{'regimes':cal['regimes'],'scenarios_per_regime':cal['scenarios_per_regime'],'bootstrap_selection_replicates':cal['selection_stability']['stratified_bootstrap']['replicates']},
 'confirmatory':{'rows':len(confirm),'regimes':sorted(confirm.regime.unique().tolist()),'scenarios':int(confirm.scenario.nunique()),'replicates_per_arm':2,'events':int(confirm.events.sum()),'thinning_rejections':int(confirm.thinning_rejections.sum()),'unique_final_hashes':int(confirm.final_hash.nunique())},
 'semantic_contract':{'alpha_zero_exact_mechanistic':True,'residual_bounded':True,'matcher_backend':'incremental with reference audit','scheduler':'exact thinning conditional on declared rates'},
 'external_trace_adapters':['srsRAN JSON/E2SM-KPM','5G-LENA CSV alias adapter'],
 'primary_endpoint':'scenario-level absolute error in oracle semantic-vs-throughput goal-utility effect',
 'limitations':['standards-informed surrogate, not full NR stack','synthetic teacher','small confirmatory scenario count per regime','no claim of real-network efficacy']
}
(ROOT/'RUN_MANIFEST.json').write_text(json.dumps(manifest,indent=2))
print('Wrote reports:',len(report),'chars')
