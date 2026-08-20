# Liquid-OSAHR 02B External RAN Telemetry Contract

External RAN sources are normalized to `CanonicalKPMRecord`. The contract is intentionally conservative: unknown producer fields are ignored rather than guessed, missing optional values remain missing, and time/unit conversions must be explicit.

## Canonical fields

| Field | Unit |
|---|---|
| `time_s` | simulation/relative seconds |
| `ue_id` | stable string identifier |
| `cell_id` | stable cell/PCI identifier |
| `rsrp_dbm` | dBm |
| `rsrq_db` | dB |
| `sinr_db` | dB |
| `cqi` | source CQI index |
| `dl_throughput_mbps` | Mbit/s |
| `ul_throughput_mbps` | Mbit/s |
| `dl_drop_rate` | fraction |
| `ul_success_rate` | fraction |
| `dl_volume_bytes` | bytes |
| `ul_volume_bytes` | bytes |
| `source` | provenance label |

`time_s` is required. Wall-clock ISO timestamps are not silently interpreted as simulation time.

## Native srsRAN scheduler JSON

`SrsRANNativeJSONAdapter` parses one canonical row per UE from `cells[*].ue_list[*]`, including documented current fields such as `cqi`, `dl_brate`, `ul_brate`, `pusch_snr_db`, `pusch_rsrp_db`, DL/UL HARQ OK/NOK counts, `pci`, and `rnti`. `dl_brate`/`ul_brate` are converted from kbps to Mbps. When a native payload contains only wall-clock time, callers must provide `default_time_s` or a JSONL sampling period.

## srsRAN / O-RAN KPM-like path

`SrsRANKPMAdapter` recognizes documented KPM-style terminal names and explicit aliases for throughput, drop/success rates, transmitted data volumes, CQI, RSRP, RSRQ, and SINR. Throughput and volume scales are constructor parameters because deployments may export different outer representations/units.

## 5G-LENA / ns-3 path

`FiveGLenaCSVAdapter` requires explicit simulation time and an alias map for the specific trace source. 5G-LENA provides multiple trace surfaces rather than one universal CSV; the adapter does not infer semantics from an arbitrary column name.

## Required provenance for a real experiment

Persist alongside every normalized dataset:

- producer/version/commit;
- scenario/configuration hash;
- metric units and any scaling;
- sampling/reporting period;
- UE/cell identity mapping;
- clock origin and synchronization rule;
- missing-data/imputation policy;
- aggregation or filtering applied upstream;
- intervention/control policy and its activation interval.

This stable boundary allows the built-in surrogate to be replaced with measured or simulator telemetry while preserving the OSAHR graph/stochastic semantics.
