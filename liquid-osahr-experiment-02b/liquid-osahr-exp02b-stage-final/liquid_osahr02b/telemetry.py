"""Telemetry normalization for external 5G/6G simulators and RAN testbeds.

This module intentionally provides a *schema boundary*, not a claim that all
producers expose identical fields.  It normalizes a conservative common subset
of srsRAN/O-RAN KPM and 5G-LENA style measurements into the feature surface
used by Experiment 02B.
"""
from __future__ import annotations

from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Any, Iterable, Mapping
import csv
import json
import math


@dataclass(frozen=True)
class CanonicalKPMRecord:
    time_s: float
    ue_id: str | None = None
    cell_id: str | None = None
    rsrp_dbm: float | None = None
    rsrq_db: float | None = None
    sinr_db: float | None = None
    cqi: float | None = None
    dl_throughput_mbps: float | None = None
    ul_throughput_mbps: float | None = None
    dl_drop_rate: float | None = None
    ul_success_rate: float | None = None
    dl_volume_bytes: float | None = None
    ul_volume_bytes: float | None = None
    source: str = "unknown"

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


_SRS_ALIASES = {
    "cqi": ("CQI", "cqi", "wideband_cqi", "wb_cqi"),
    "rsrp_dbm": ("RSRP", "rsrp", "rsrp_dbm"),
    "rsrq_db": ("RSRQ", "rsrq", "rsrq_db"),
    "sinr_db": ("SINR", "sinr", "sinr_db", "snr_db"),
    "dl_throughput_mbps": ("DRB.UEThpDl", "dl_throughput_mbps", "ue_thp_dl"),
    "ul_throughput_mbps": ("DRB.UEThpUl", "ul_throughput_mbps", "ue_thp_ul"),
    "dl_drop_rate": ("DRB.RlcPacketDropRateDl", "dl_drop_rate", "rlc_packet_drop_rate_dl"),
    "ul_success_rate": ("DRB.PacketSuccessRateUlgNBUu", "ul_success_rate", "packet_success_rate_ul"),
    "dl_volume_bytes": ("DRB.RlcSduTransmittedVolumeDL", "dl_volume_bytes", "rlc_sdu_tx_volume_dl"),
    "ul_volume_bytes": ("DRB.RlcSduTransmittedVolumeUL", "ul_volume_bytes", "rlc_sdu_tx_volume_ul"),
}

_TIME_ALIASES = ("time_s", "timestamp_s", "sim_time_s", "time", "timestamp")
_UE_ALIASES = ("ue_id", "UE_id", "rnti", "ue", "ueId")
_CELL_ALIASES = ("cell_id", "cell", "pci", "gnb_id", "nr_cell_id")


def _flatten(obj: Any, prefix: str = "") -> dict[str, Any]:
    """Flatten nested dict/list JSON while retaining terminal field names.

    srsRAN's JSON metric payloads can change nesting across layers and release
    versions.  We therefore use exact *terminal metric names* documented by
    srsRAN/O-RAN instead of depending on one private JSON nesting layout.
    """
    out: dict[str, Any] = {}
    if isinstance(obj, Mapping):
        for k, v in obj.items():
            key = f"{prefix}.{k}" if prefix else str(k)
            out.update(_flatten(v, key))
            if not isinstance(v, (Mapping, list, tuple)):
                out.setdefault(str(k), v)
    elif isinstance(obj, (list, tuple)):
        for i, v in enumerate(obj):
            out.update(_flatten(v, f"{prefix}[{i}]"))
    else:
        out[prefix] = obj
    return out


def _first(flat: Mapping[str, Any], aliases: Iterable[str]) -> Any:
    for a in aliases:
        if a in flat:
            return flat[a]
    # Exact terminal match for nested keys.
    for a in aliases:
        suffixes = ("." + a, "]" + "." + a)
        for k, v in flat.items():
            if k.endswith(suffixes[0]) or k.endswith(suffixes[1]):
                return v
    return None


def _num(v: Any, *, percent_to_fraction: bool = False) -> float | None:
    if v is None:
        return None
    if isinstance(v, (list, tuple)):
        if not v:
            return None
        v = v[0]
    try:
        x = float(v)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(x):
        return None
    if percent_to_fraction and x > 1.0:
        x /= 100.0
    return x


def _identifier(v: Any) -> str | None:
    if v is None:
        return None
    if isinstance(v, (list, tuple)):
        if not v:
            return None
        v = v[0]
    return str(v)


class SrsRANKPMAdapter:
    """Normalize srsRAN JSON metrics or E2SM-KPM-derived dictionaries.

    The adapter deliberately recognizes only documented metric names and a few
    transparent aliases. Unknown fields remain ignored rather than guessed.
    Throughput unit conversion is configurable because E2SM-KPM deployments may
    expose implementation-specific scaling around the standardized metric.
    """

    def __init__(self, *, throughput_scale_to_mbps: float = 1.0,
                 volume_scale_to_bytes: float = 1.0):
        self.throughput_scale_to_mbps = float(throughput_scale_to_mbps)
        self.volume_scale_to_bytes = float(volume_scale_to_bytes)

    def parse(self, payload: Mapping[str, Any], *, default_time_s: float | None = None) -> CanonicalKPMRecord:
        flat = _flatten(payload)
        t = _num(_first(flat, _TIME_ALIASES))
        if t is None:
            if default_time_s is None:
                raise ValueError("srsRAN/KPM payload has no recognized time; supply default_time_s")
            t = float(default_time_s)
        vals: dict[str, Any] = {}
        for canonical, aliases in _SRS_ALIASES.items():
            raw = _first(flat, aliases)
            if canonical in {"dl_drop_rate", "ul_success_rate"}:
                vals[canonical] = _num(raw, percent_to_fraction=True)
            else:
                vals[canonical] = _num(raw)
        for k in ("dl_throughput_mbps", "ul_throughput_mbps"):
            if vals[k] is not None:
                vals[k] *= self.throughput_scale_to_mbps
        for k in ("dl_volume_bytes", "ul_volume_bytes"):
            if vals[k] is not None:
                vals[k] *= self.volume_scale_to_bytes
        return CanonicalKPMRecord(
            time_s=t,
            ue_id=_identifier(_first(flat, _UE_ALIASES)),
            cell_id=_identifier(_first(flat, _CELL_ALIASES)),
            source="srsran",
            **vals,
        )

    def read_jsonl(self, path: str | Path) -> list[CanonicalKPMRecord]:
        out = []
        with Path(path).open("r", encoding="utf-8") as f:
            for line_no, line in enumerate(f, 1):
                line = line.strip()
                if not line:
                    continue
                try:
                    obj = json.loads(line)
                except json.JSONDecodeError as exc:
                    raise ValueError(f"invalid JSON at {path}:{line_no}") from exc
                # Ignore websocket command/control envelopes.
                if isinstance(obj, Mapping) and "cmd" in obj and len(obj) <= 2:
                    continue
                out.append(self.parse(obj))
        return out


class SrsRANNativeJSONAdapter:
    """Normalize native srsRAN Project scheduler JSON metrics.

    Current srsRAN scheduler metrics expose per-UE fields such as ``cqi``,
    ``dl_brate``/``ul_brate`` (kbps), ``pusch_snr_db`` and ``pusch_rsrp_db``
    beneath ``cells[*].ue_list[*]``.  This adapter preserves one canonical row
    per UE.  A simulation-relative ``default_time_s`` is intentionally required
    when the producer timestamp is an ISO wall-clock value; the experiment must
    not silently reinterpret wall-clock time as simulation time.
    """

    def parse_records(self, payload: Mapping[str, Any], *, default_time_s: float | None = None) -> list[CanonicalKPMRecord]:
        raw_time = payload.get("time_s", payload.get("timestamp_s"))
        t = _num(raw_time)
        if t is None:
            if default_time_s is None:
                raise ValueError("native srsRAN JSON requires default_time_s when no numeric simulation time is present")
            t = float(default_time_s)

        cells = payload.get("cells")
        if not isinstance(cells, list):
            # The scheduler object may itself be nested under a top-level key.
            flat_candidates = []
            def walk(obj):
                if isinstance(obj, Mapping):
                    if isinstance(obj.get("cells"), list):
                        flat_candidates.append(obj["cells"])
                    for v in obj.values(): walk(v)
                elif isinstance(obj, list):
                    for v in obj: walk(v)
            walk(payload)
            cells = flat_candidates[0] if flat_candidates else None
        if not isinstance(cells, list):
            raise ValueError("native srsRAN scheduler payload has no cells list")

        out: list[CanonicalKPMRecord] = []
        for cell in cells:
            if not isinstance(cell, Mapping):
                continue
            cell_metrics = cell.get("cell_metrics") if isinstance(cell.get("cell_metrics"), Mapping) else {}
            pci = cell.get("pci", cell_metrics.get("pci"))
            ue_list = cell.get("ue_list", [])
            if not isinstance(ue_list, list):
                continue
            for ue in ue_list:
                if not isinstance(ue, Mapping):
                    continue
                cqi = _num(ue.get("cqi"))
                pusch_snr = _num(ue.get("pusch_snr_db"))
                pusch_rsrp = _num(ue.get("pusch_rsrp_db"))
                dl_kbps = _num(ue.get("dl_brate"))
                ul_kbps = _num(ue.get("ul_brate"))
                dl_ok = _num(ue.get("dl_nof_ok"))
                dl_nok = _num(ue.get("dl_nof_nok"))
                ul_ok = _num(ue.get("ul_nof_ok"))
                ul_nok = _num(ue.get("ul_nof_nok"))
                dl_drop = None
                if dl_ok is not None and dl_nok is not None and dl_ok + dl_nok > 0:
                    dl_drop = dl_nok / (dl_ok + dl_nok)
                ul_success = None
                if ul_ok is not None and ul_nok is not None and ul_ok + ul_nok > 0:
                    ul_success = ul_ok / (ul_ok + ul_nok)
                out.append(CanonicalKPMRecord(
                    time_s=t,
                    ue_id=_identifier(ue.get("rnti", ue.get("ue"))),
                    cell_id=_identifier(ue.get("pci", pci)),
                    rsrp_dbm=pusch_rsrp,
                    sinr_db=pusch_snr,
                    cqi=cqi,
                    dl_throughput_mbps=None if dl_kbps is None else dl_kbps / 1000.0,
                    ul_throughput_mbps=None if ul_kbps is None else ul_kbps / 1000.0,
                    dl_drop_rate=dl_drop,
                    ul_success_rate=ul_success,
                    source="srsran-native",
                ))
        return out

    def read_jsonl(self, path: str | Path, *, start_time_s: float = 0.0, period_s: float | None = None) -> list[CanonicalKPMRecord]:
        """Read native JSONL metrics.

        When native messages contain only ISO wall-clock timestamps, callers
        must provide ``period_s`` so records receive deterministic simulation
        times ``start_time_s + i*period_s``.  This keeps the OSAHR time axis
        explicit rather than implicitly coupling it to host wall-clock time.
        """
        out: list[CanonicalKPMRecord] = []
        with Path(path).open("r", encoding="utf-8") as f:
            logical_index = 0
            for line_no, line in enumerate(f, 1):
                line = line.strip()
                if not line:
                    continue
                try:
                    obj = json.loads(line)
                except json.JSONDecodeError as exc:
                    raise ValueError(f"invalid JSON at {path}:{line_no}") from exc
                if isinstance(obj, Mapping) and "cmd" in obj and len(obj) <= 2:
                    continue
                fallback = None if period_s is None else float(start_time_s + logical_index * period_s)
                recs = self.parse_records(obj, default_time_s=fallback)
                out.extend(recs)
                logical_index += 1
        return out


_LENA_ALIASES = {
    "time_s": ("time_s", "Time", "time", "simTime", "timestamp"),
    "ue_id": ("ue_id", "IMSI", "imsi", "RNTI", "rnti", "ueId"),
    "cell_id": ("cell_id", "CellId", "cellId", "cell", "PCI", "pci"),
    "rsrp_dbm": ("rsrp_dbm", "RSRP", "rsrp", "Rsrp"),
    "rsrq_db": ("rsrq_db", "RSRQ", "rsrq", "Rsrq"),
    "sinr_db": ("sinr_db", "SINR", "sinr", "Sinr", "SNR", "snr"),
    "cqi": ("cqi", "CQI", "Cqi"),
    "dl_throughput_mbps": ("dl_throughput_mbps", "throughput_mbps", "ThroughputMbps", "dlThroughputMbps"),
    "ul_throughput_mbps": ("ul_throughput_mbps", "ulThroughputMbps"),
    "dl_drop_rate": ("dl_drop_rate", "drop_rate", "packetDropRate"),
}


class FiveGLenaCSVAdapter:
    """Normalize a user-selected 5G-LENA/ns-3 trace CSV into canonical KPMs.

    5G-LENA exposes multiple trace sources rather than one universal CSV schema.
    This adapter therefore uses a declared alias map and fails if time is absent;
    callers may extend ``aliases`` for a chosen trace source without changing
    the OSAHR side of the experiment.
    """

    def __init__(self, aliases: Mapping[str, Iterable[str]] | None = None):
        self.aliases = {k: tuple(v) for k, v in (aliases or _LENA_ALIASES).items()}

    def parse_row(self, row: Mapping[str, Any]) -> CanonicalKPMRecord:
        def get(name: str):
            return _first(row, self.aliases.get(name, (name,)))
        t = _num(get("time_s"))
        if t is None:
            raise ValueError("5G-LENA row has no recognized simulation time")
        return CanonicalKPMRecord(
            time_s=t,
            ue_id=_identifier(get("ue_id")),
            cell_id=_identifier(get("cell_id")),
            rsrp_dbm=_num(get("rsrp_dbm")),
            rsrq_db=_num(get("rsrq_db")),
            sinr_db=_num(get("sinr_db")),
            cqi=_num(get("cqi")),
            dl_throughput_mbps=_num(get("dl_throughput_mbps")),
            ul_throughput_mbps=_num(get("ul_throughput_mbps")),
            dl_drop_rate=_num(get("dl_drop_rate"), percent_to_fraction=True),
            source="5g-lena",
        )

    def read_csv(self, path: str | Path) -> list[CanonicalKPMRecord]:
        with Path(path).open("r", newline="", encoding="utf-8") as f:
            return [self.parse_row(row) for row in csv.DictReader(f)]


def canonical_records_to_rows(records: Iterable[CanonicalKPMRecord]) -> list[dict[str, Any]]:
    return [r.as_dict() for r in records]
