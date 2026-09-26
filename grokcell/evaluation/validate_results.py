"""Validate and summarize evaluation records; never executes candidates."""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path


PROTOCOLS = {
    "A": ("grokcell-controller-ablation", {"fixed", "jev", "inexpensive_alternative"}),
    "B": ("grokcell-complete-systems", None),
}
SPLITS = {"development", "retrieval", "evaluation"}
OUTCOMES = {"accepted", "yielded", "failed", "unknown"}
COST_SOURCES = {"invoice", "provider_usage", "reservation", "unknown"}
HEX_SHA256 = re.compile(r"^[0-9a-f]{64}$")


def _nonempty(value):
    return type(value) is str and bool(value.strip())


def _count(value):
    return type(value) is int and value >= 0


def validate_registry(registry):
    if type(registry) is not dict or set(registry) != {"acceptance_owner_id", "sealed_case_commitment", "cases"}:
        raise ValueError("independent case registry fields are required")
    if not _nonempty(registry["acceptance_owner_id"]):
        raise ValueError("independent acceptance owner is required")
    if not HEX_SHA256.fullmatch(registry["sealed_case_commitment"] or ""):
        raise ValueError("sealed case-set SHA-256 commitment required")
    if type(registry["cases"]) is not list or not registry["cases"]:
        raise ValueError("case registry must contain the owner-controlled case set")
    by_id, split_by_family, split_by_repository = {}, {}, {}
    for case in registry["cases"]:
        if type(case) is not dict or set(case) != {"case_id", "case_family", "repository_id", "split"}:
            raise ValueError("case registry row fields do not match the frozen contract")
        if any(not _nonempty(case[key]) for key in ("case_id", "case_family", "repository_id")):
            raise ValueError("case registry identities must be nonempty")
        if case["split"] not in SPLITS:
            raise ValueError("unknown case split")
        if case["case_id"] in by_id:
            raise ValueError("duplicate case id in registry")
        for index, key in ((split_by_family, "case_family"), (split_by_repository, "repository_id")):
            prior = index.setdefault(case[key], case["split"])
            if prior != case["split"]:
                raise ValueError("case family and repository must remain disjoint across splits")
        by_id[case["case_id"]] = case
    return by_id


def validate_record(record, study, registry):
    study_id, controllers = PROTOCOLS[study]
    cases = validate_registry(registry)
    required = {
        "study_id", "protocol_version", "split", "case_family", "repository_id", "case_id",
        "system_id", "controller_id", "worker_id", "verifier_contract_id", "environment_id",
        "permission_profile_id", "resource_limits_profile_id", "acceptance_owner_id",
        "sealed_case_commitment", "attempts", "uncertainty_notes",
    }
    if type(record) is not dict or set(record) != required:
        raise ValueError("record fields do not match the frozen result contract")
    if record["study_id"] != study_id or record["protocol_version"] != "1.0.0":
        raise ValueError("study identity or protocol version mismatch")
    if record["split"] != "evaluation" or record["split"] not in SPLITS:
        raise ValueError("only independent sealed evaluation cases can be scored")
    for key in ("case_family", "repository_id", "case_id", "system_id", "worker_id",
                "verifier_contract_id", "environment_id", "permission_profile_id",
                "resource_limits_profile_id", "acceptance_owner_id"):
        if not _nonempty(record[key]):
            raise ValueError("missing required identity: " + key)
    case = cases.get(record["case_id"])
    if (case is None or case != {key: record[key] for key in ("case_id", "case_family", "repository_id", "split")}
            or case["split"] != "evaluation"):
        raise ValueError("result case does not match the independent evaluation registry")
    if (record["acceptance_owner_id"] != registry["acceptance_owner_id"]
            or record["sealed_case_commitment"] != registry["sealed_case_commitment"]):
        raise ValueError("result does not match the independent case-set attestation")
    if controllers is None:
        if record["controller_id"] is not None and not _nonempty(record["controller_id"]):
            raise ValueError("controller_id must be null or nonempty text")
    elif record["controller_id"] not in controllers:
        raise ValueError("unregistered controller arm")
    if type(record["attempts"]) is not list or not record["attempts"]:
        raise ValueError("every episode must retain at least one attempt")
    if type(record["uncertainty_notes"]) is not list or any(not _nonempty(x) for x in record["uncertainty_notes"]):
        raise ValueError("uncertainty_notes must be a list of explicit notes")
    for attempt in record["attempts"]:
        fields = {"attempt_id", "outcome", "provider_cost_microusd", "cost_source", "billing_reconciled",
                  "latency_ms", "required_checks", "passed_checks", "human_rescue", "evidence_refs"}
        if type(attempt) is not dict or set(attempt) != fields:
            raise ValueError("attempt fields do not match the frozen result contract")
        if not _nonempty(attempt["attempt_id"]) or attempt["outcome"] not in OUTCOMES:
            raise ValueError("attempt identity or outcome is invalid")
        cost = attempt["provider_cost_microusd"]
        if cost is not None and not _count(cost):
            raise ValueError("provider cost must be nonnegative integer micro-USD or null")
        if attempt["cost_source"] not in COST_SOURCES:
            raise ValueError("unknown cost source")
        if type(attempt["billing_reconciled"]) is not bool:
            raise ValueError("billing reconciliation status is required")
        if attempt["cost_source"] == "invoice" and not attempt["billing_reconciled"]:
            raise ValueError("invoice sourced cost must be reconciled")
        if attempt["cost_source"] == "unknown" and cost is not None:
            raise ValueError("unknown cost cannot be recorded as a number")
        if attempt["latency_ms"] is not None and not _count(attempt["latency_ms"]):
            raise ValueError("latency must be nonnegative integer milliseconds or null")
        if not _count(attempt["required_checks"]) or not _count(attempt["passed_checks"]):
            raise ValueError("check coverage must use nonnegative integer counts")
        if attempt["passed_checks"] > attempt["required_checks"]:
            raise ValueError("passed checks exceed required checks")
        if type(attempt["human_rescue"]) is not bool:
            raise ValueError("human rescue status is required")
        if type(attempt["evidence_refs"]) is not list or any(not _nonempty(x) for x in attempt["evidence_refs"]):
            raise ValueError("attempt evidence references must be explicit")
    return record


def validate_dataset(records, study):
    if study != "A":
        return
    arms = PROTOCOLS[study][1]
    paired = {}
    matched = ("worker_id", "verifier_contract_id", "environment_id", "permission_profile_id",
               "resource_limits_profile_id")
    for record in records:
        key = (record["repository_id"], record["case_id"])
        arms_for_case = paired.setdefault(key, {})
        arm = record["controller_id"]
        if arm in arms_for_case:
            raise ValueError("duplicate controller arm for paired case")
        arms_for_case[arm] = record
    if not paired or any(set(values) != arms for values in paired.values()):
        raise ValueError("Study A requires all pre-registered controller arms for every case")
    for values in paired.values():
        baseline = values["fixed"]
        if any(any(record[key] != baseline[key] for key in matched) for record in values.values()):
            raise ValueError("Study A arms do not share worker, checks, environment, authority, and limits")


def summarize(records, study):
    groups = {}
    for record in records:
        identity = record["controller_id"] if study == "A" else record["system_id"]
        group = groups.setdefault(identity, {"episodes": 0, "attempts": 0, "failed_attempts": 0,
            "yielded_attempts": 0, "unknown_outcome_attempts": 0, "accepted_attempts": 0,
            "required_checks": 0, "passed_checks": 0, "human_rescue_attempts": 0,
            "known_latency_ms_total": 0, "latency_unknown_attempts": 0, "known_cost_microusd": 0,
            "unknown_cost_attempts": 0, "unreconciled_cost_attempts": 0, "uncertainty_notes": 0})
        group["episodes"] += 1
        group["uncertainty_notes"] += len(record["uncertainty_notes"])
        for attempt in record["attempts"]:
            group["attempts"] += 1
            group["failed_attempts"] += attempt["outcome"] == "failed"
            group["yielded_attempts"] += attempt["outcome"] == "yielded"
            group["unknown_outcome_attempts"] += attempt["outcome"] == "unknown"
            group["accepted_attempts"] += attempt["outcome"] == "accepted"
            group["required_checks"] += attempt["required_checks"]
            group["passed_checks"] += attempt["passed_checks"]
            group["human_rescue_attempts"] += attempt["human_rescue"]
            if attempt["latency_ms"] is None:
                group["latency_unknown_attempts"] += 1
            else:
                group["known_latency_ms_total"] += attempt["latency_ms"]
            if attempt["provider_cost_microusd"] is None:
                group["unknown_cost_attempts"] += 1
            else:
                group["known_cost_microusd"] += attempt["provider_cost_microusd"]
            group["unreconciled_cost_attempts"] += not attempt["billing_reconciled"]
    for group in groups.values():
        required = group["required_checks"]
        group["check_coverage"] = group["passed_checks"] / required if required else None
    return groups


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("results", type=Path)
    parser.add_argument("--registry", type=Path, required=True,
                        help="private registry signed/controlled by the independent acceptance owner")
    parser.add_argument("--study", choices=tuple(PROTOCOLS), required=True)
    args = parser.parse_args(argv)
    records = []
    seen = set()
    try:
        registry = json.loads(args.registry.read_text(encoding="utf-8"))
        validate_registry(registry)
        with args.results.open(encoding="utf-8") as handle:
            for number, line in enumerate(handle, 1):
                if not line.strip():
                    continue
                try:
                    record = validate_record(json.loads(line), args.study, registry)
                except (ValueError, TypeError) as exc:
                    raise ValueError(f"line {number}: {exc}") from exc
                key = (record["repository_id"], record["case_id"], record["system_id"])
                if key in seen:
                    raise ValueError(f"line {number}: duplicate system result for case")
                seen.add(key)
                records.append(record)
        if not records:
            raise ValueError("no result records")
        validate_dataset(records, args.study)
        print(json.dumps({"study": PROTOCOLS[args.study][0], "records": len(records),
                          "scope": "descriptive-only-unverified-record-authenticity",
                          "systems": summarize(records, args.study)}, indent=2, sort_keys=True))
        return 0
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(json.dumps({"status": "blocked", "reason": str(exc)}), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
