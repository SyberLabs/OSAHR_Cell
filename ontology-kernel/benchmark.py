"""Compare existing exhaustive vs bound matching with the same DPO transaction."""
import json
import platform
from datetime import datetime, timezone
from hashlib import sha256
from statistics import median
from time import perf_counter
from pathlib import Path

from demo import EVIDENCE, MODULE, PROPOSAL, fixture, full_context
from kernel import AdmissionProfile


if __name__ == "__main__":
    profile = AdmissionProfile()
    rows = []
    for count in (0, 100, 1000):
        data = fixture(count)
        start = perf_counter()
        model = profile.prepare(data, PROPOSAL, MODULE, EVIDENCE)
        prepare_ms = 1000 * (perf_counter() - start)
        complete = full_context(model, data)
        samples = {"local_bound": [], "full_bound": [], "full_exhaustive": []}
        expected = profile.rewrite(model).graph.state_hash
        full_expected = profile.rewrite(complete, bound=False).graph.state_hash
        for iteration in range(7):
            modes = list(samples)
            for mode in (modes if iteration % 2 == 0 else reversed(modes)):
                selected = model if mode == "local_bound" else complete
                start = perf_counter()
                result = profile.rewrite(selected, bound=mode != "full_exhaustive")
                samples[mode].append(1000 * (perf_counter() - start))
                assert result.graph.state_hash == (expected if mode == "local_bound" else full_expected)
                assert result.graph.vertices[result.post_vertex_map["comp"]].attributes == {"name": "edge.ping"}
        start = perf_counter()
        preview = profile.preview(data, PROPOSAL, MODULE, EVIDENCE)
        preview_ms = 1000 * (perf_counter() - start)
        rows.append({"existing_components": count, "rdf_triples": len(data),
                     "prepare_ms_single_run": prepare_ms,
                     "local_bound_ms_median_7": median(samples["local_bound"]),
                     "full_bound_ms_median_7": median(samples["full_bound"]),
                     "full_exhaustive_ms_median_7": median(samples["full_exhaustive"]),
                     "full_preview_ms_single_run": preview_ms,
                     "same_post_graph": preview.receipt["post_graph"] == expected,
                     "samples_ms": samples})
    report = {"python": platform.python_version(), "platform": platform.platform(),
              "measured_at_utc": datetime.now(timezone.utc).isoformat(),
              "profile_source_sha256": sha256(Path(__file__).with_name("kernel.py").read_bytes()).hexdigest(),
              "benchmark_source_sha256": sha256(Path(__file__).read_bytes()).hexdigest(),
              "scope": "local synthetic fixture; includes full graph clone and validation; no portable speedup claim",
              "rows": rows}
    path = Path(__file__).resolve().parent / "artifacts" / "benchmark.json"
    path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2))
