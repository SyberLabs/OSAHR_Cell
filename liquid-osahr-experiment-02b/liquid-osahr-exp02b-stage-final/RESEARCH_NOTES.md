# Research Notes: Experiment 02B

## Network Digital Twins

3GPP Release 19 TS 28.561 formalizes management aspects of Network Digital Twins, and 3GPP's 2026 NDT overview describes twins as virtual replicas intended to capture network attributes, behavior and interactions for intelligence/automation and pre-deployment evaluation.

O-RAN has an active Digital Twin research program and uses DTs in AI/Open-RAN experimentation. This supports positioning OSAHR above packet/RF simulation as a shadow causal/control twin rather than as a replacement radio simulator.

## RAN physics / simulator grounding

The synthetic layer uses the UMi Street Canyon large-scale path-loss form from 3GPP TR 38.901. It does not implement the full clustered channel, antenna, PHY, scheduler, HARQ or RLC stack. 5G-LENA is the target high-fidelity simulator bridge because its NR module supports 38.901 channel modeling and system-level calibration.

## Operational telemetry grounding

srsRAN Project supports JSON metrics and an O-RAN E2 interface. Current scheduler JSON documents a `cells[*].ue_list[*]` structure with per-UE CQI, DL/UL bitrate, PUSCH SNR/RSRP, HARQ OK/NOK counts, PCI and RNTI; 02B ships a native parser for that surface in addition to its conservative E2SM-KPM-style adapter.

## Counterfactual validation

Recent 2026 digital-twin causal-validation work emphasizes that prediction and counterfactual validity require different assumptions/tests. 02B operationalizes that distinction by evaluating oracle intervention effects directly in a synthetic world where those effects are observable. A recent 6G NDT paper also proposes directional/intervention-sensitive validation rather than relying only on regression accuracy.

## Neural continuous-time component

CfC provides a closed-form continuous-time recurrent architecture. In 02B, it is not allowed to generate graph structure or legal transitions. It learns only a bounded residual correction to event intensities.

## Exact stochastic simulation

OSAHR uses thinning with architectural global rate ceilings. This is aligned with exact PDMP/thinning theory: exactness depends on a valid dominating intensity, which is guaranteed here by construction.

## Key references

- 3GPP TS 28.561: https://www.3gpp.org/dynareport/28561.htm
- 3GPP NDT overview: https://www.3gpp.org/technologies/digital-twin1
- 3GPP TR 38.901 / ETSI: https://www.etsi.org/deliver/etsi_tr/138900_138999/138901/
- srsRAN scheduler/JSON metrics: https://docs.srsran.com/projects/project/en/latest/user_manuals/source/outputs.html
- srsRAN NearRT-RIC/E2SM-KPM: https://docs.srsran.com/projects/project/en/latest/tutorials/source/near-rt-ric/source/index.html
- 5G-LENA NR module: https://cttc-lena.gitlab.io/nr/manual/nr-module.html
- O-RAN press releases / Digital Twin platform: https://www.o-ran.org/press-releases
- Hasani et al., CfC: https://arxiv.org/abs/2106.13898
- Exact PDMP jump simulation: https://arxiv.org/abs/1602.07871
- Digital Twin Counterfactual Framework: https://arxiv.org/abs/2604.01325
- Trustworthy 6G NDT counterfactual validation: https://arxiv.org/abs/2604.14787
