"""Shared 02B residual twin execution for Experiment 04."""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Any, Callable

import pandas as pd

from .protocol import ARM_SPECS, ART, EXP02B, HORIZON, POLICIES, REPLICATES

if str(EXP02B) not in sys.path:
    sys.path.insert(0, str(EXP02B))
if str(EXP02B / "vendor") not in sys.path:
    sys.path.insert(0, str(EXP02B / "vendor"))

import torch
from liquid_osahr02b.field import HazardBounds, Scenario  # type: ignore
from liquid_osahr02b.ran import RAN_STRUCT_DIM, ResidualGraphCfC  # type: ignore
from liquid_osahr02b.ran_experiment import paired_scenarios, run_counterfactual  # type: ignore


def load_residual():
    ck = torch.load(EXP02B / "artifacts" / "residual_cfc.pt", map_location="cpu", weights_only=False)
    model = ResidualGraphCfC(RAN_STRUCT_DIM, int(ck["config"]["hidden_size"]))
    model.load_state_dict(ck["state_dict"])
    model.eval()
    return model, ck


def run_arm(
    *,
    model,
    scenario: Scenario,
    kind: str,
    field_kind: str,
    trust: float,
    policy: str,
    scenario_id: int,
    replicate: int,
    root_seed: int,
    horizon: float = HORIZON,
    verify: bool = False,
) -> dict[str, Any]:
    with torch.inference_mode():
        row = run_counterfactual(
            field_kind,
            scenario,
            policy,
            scenario_id=scenario_id,
            replicate=replicate,
            root_seed=root_seed,
            model=model,
            trust=trust,
            horizon=horizon,
            bounds=HazardBounds(),
            verify=verify,
        )
    row["model"] = kind
    row["trust"] = float(trust)
    for key, value in scenario.__dict__.items():
        row[f"scenario_{key}"] = value
    return row


def expected_rows(n_scenarios: int, n_regimes: int) -> int:
    return n_regimes * n_scenarios * REPLICATES * len(ARM_SPECS) * len(POLICIES)


def run_split(
    *,
    split: str,
    root_seed: int,
    regimes: tuple[str, ...],
    n_scenarios: int,
    scenario_id_fn: Callable[[int, int], int],
    seed_offset_fn: Callable[[int], int],
    combined_csv: Path,
    horizon: float = HORIZON,
) -> pd.DataFrame:
    ART.mkdir(parents=True, exist_ok=True)
    model, _ = load_residual()
    chunk_dir = ART / f"{split}_chunks"
    chunk_dir.mkdir(exist_ok=True)
    frames: list[pd.DataFrame] = []
    for ri, regime in enumerate(regimes):
        scenarios = paired_scenarios(seed_offset_fn(ri), n_scenarios, regime)
        for si, scenario in enumerate(scenarios):
            sid = scenario_id_fn(ri, si)
            out = chunk_dir / f"{regime}_{si}.csv"
            rows = pd.read_csv(out).to_dict("records") if out.exists() and out.stat().st_size else []
            done = {(int(r["replicate"]), str(r["model"]), str(r["policy"])) for r in rows}
            for rep in range(REPLICATES):
                for kind, field_kind, trust in ARM_SPECS:
                    for pol in POLICIES:
                        key = (rep, kind, pol)
                        if key in done:
                            continue
                        verify = (
                            split == "confirmatory"
                            and regime == "id"
                            and si == 0
                            and rep == 0
                            and kind == "residual_predictive"
                            and pol == "semantic"
                        )
                        print("RUN", split, regime, si, rep, kind, pol, flush=True)
                        row = run_arm(
                            model=model,
                            scenario=scenario,
                            kind=kind,
                            field_kind=field_kind,
                            trust=trust,
                            policy=pol,
                            scenario_id=sid,
                            replicate=rep,
                            root_seed=root_seed,
                            horizon=horizon,
                            verify=verify,
                        )
                        row["regime"] = regime
                        row["local_scenario"] = si
                        rows.append(row)
                        done.add(key)
                        tmp = out.with_suffix(".tmp")
                        pd.DataFrame(rows).to_csv(tmp, index=False)
                        tmp.replace(out)
            assert len(rows) == REPLICATES * len(ARM_SPECS) * len(POLICIES)
            frames.append(pd.DataFrame(rows))
    df = pd.concat(frames, ignore_index=True)
    expected = expected_rows(n_scenarios, len(regimes))
    if len(df) != expected:
        raise RuntimeError(f"{split} row count {len(df)} != {expected}")
    tmp = combined_csv.with_suffix(".tmp")
    df.to_csv(tmp, index=False)
    tmp.replace(combined_csv)
    print("WROTE", combined_csv, len(df), flush=True)
    return df
