#!/usr/bin/env python3
"""Normalize external RAN telemetry into Liquid-OSAHR's canonical KPM schema."""
from __future__ import annotations
import sys
from pathlib import Path as _BootstrapPath
_ROOT = _BootstrapPath(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path: sys.path.insert(0, str(_ROOT))
import argparse,json
from liquid_osahr02b.telemetry import (
    SrsRANKPMAdapter,SrsRANNativeJSONAdapter,FiveGLenaCSVAdapter,canonical_records_to_rows
)

def main():
    p=argparse.ArgumentParser()
    p.add_argument('format',choices=('srsran-jsonl','srsran-native-jsonl','5glena-csv'))
    p.add_argument('path')
    p.add_argument('--throughput-scale-to-mbps',type=float,default=1.0)
    p.add_argument('--start-time-s',type=float,default=0.0)
    p.add_argument('--period-s',type=float)
    a=p.parse_args()
    if a.format=='srsran-jsonl':
        recs=SrsRANKPMAdapter(throughput_scale_to_mbps=a.throughput_scale_to_mbps).read_jsonl(a.path)
    elif a.format=='srsran-native-jsonl':
        recs=SrsRANNativeJSONAdapter().read_jsonl(a.path,start_time_s=a.start_time_s,period_s=a.period_s)
    else:
        recs=FiveGLenaCSVAdapter().read_csv(a.path)
    print(json.dumps(canonical_records_to_rows(recs),indent=2))

if __name__=='__main__': main()
