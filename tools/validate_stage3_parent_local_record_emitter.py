#!/usr/bin/env python3
"""Join the parent-local Stage-3 emitter repair evidence without promotion."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

import build_stage3_parent_local_record_emitter_candidate as candidate


ROOT = Path(__file__).resolve().parents[1]
ROM_SHA256 = "0453ef75077e24eae188e606532512f25604fa3e84bfeb1954dadbe2b26ceebf"
SEMANTIC = ROOT / "build/validate-stage3-parent-local-record-emitter-current-a976-isolated-v1.jsonl"
TRACE = ROOT / "build/trace-stage3-parent-local-record-emitter-current-a976-safe14743-native-on-v1/trace.json"
FRESH = ROOT / "build/fresh-campaign-stage3-parent-local-record-emitter-current-a976-to3000-native-on-v1/summary.json"
RATE = ROOT / "build/measure-stage3-parent-local-record-emitter-current-a976-safe14743-v1/summary.json"


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def collect() -> dict:
    for path in (SEMANTIC, TRACE, FRESH, RATE):
        if not path.is_file():
            raise RuntimeError(f"missing retained evidence: {path}")
    rows = [json.loads(line) for line in SEMANTIC.read_text(encoding="utf-8").splitlines()]
    semantic = rows[-1]
    trace = load(TRACE)
    fresh = load(FRESH)
    rate = load(RATE)
    if semantic != {**semantic, "event": "summary", "green": 14, "red": 0, "result": "green", "route_probes": 2, "semantic_cases": 12, "time": semantic["time"], "total": 14}:
        raise RuntimeError("parent-local semantic summary changed")
    if trace["rom_sha256"] != ROM_SHA256 or fresh["rom_sha256"] != ROM_SHA256 or rate["rom_sha256"] != ROM_SHA256:
        raise RuntimeError("parent-local evidence ROM identity changed")
    child_counts = {
        "$027AEA": trace["event_counts"].get("entry_27aea@9FC000"),
        "$027B44": trace["event_counts"].get("entry_27b44@94CB40"),
        "$027B7C": trace["event_counts"].get("entry_27b7c@94CEC0"),
    }
    if child_counts != {"$027AEA": 12, "$027B44": 12, "$027B7C": 12}:
        raise RuntimeError("parent-local Stage-3 child route counts changed")
    failure = fresh.get("failure", {})
    if (
        fresh.get("result") != "red"
        or fresh.get("mame_end_tick") != 3000
        or fresh.get("oracle_divergence_count") != 0
        or failure.get("classification") != "coverage"
        or failure.get("reason") != "required_controller_or_action_coverage_missing"
    ):
        raise RuntimeError("fresh parent-local Stage-1 segment changed")
    comparison = rate["comparison"]
    if comparison["production_meets_budget"] or rate["result"] != "red":
        raise RuntimeError("parent-local rate gate unexpectedly changed")
    return {
        "scope": (
            "parent-local Stage-3 record-emitter repair: bounded original-MAME/native-off/native-on "
            "semantics, one safe-checkpoint route tick, fresh power-on controller segment through tick 3,000, "
            "and sustained checkpoint rate; not full campaign, organic Stage-3 timing, or FPS proof"
        ),
        "rom_sha256": ROM_SHA256,
        "source_fix": (
            "native $027952 directly bridges its $027B44/$027B7C children; shared $9D:DA00 remains conservative"
        ),
        "bounded_three_way": {
            "artifact": str(SEMANTIC),
            "sha256": digest(SEMANTIC),
            "cases": 12,
            "route_probes": 2,
            "result": "green",
        },
        "safe_checkpoint_route": {
            "artifact": str(TRACE),
            "child_counts": child_counts,
            "result": "green",
        },
        "fresh_power_on_segment": {
            "artifact": str(FRESH),
            "end_tick": 3000,
            "oracle_divergence_count": 0,
            "terminal": "coverage-only red",
            "repaired_button1_tick": 2958,
            "result": "green",
        },
        "sustained_stage3_rate": {
            "artifact": str(RATE),
            "native_on_cycles_per_tick": comparison["production_native_on_cycles_per_tick"],
            "budget_cycles_per_tick": comparison["budget_cycles_per_tick"],
            "result": "red",
        },
        "promotion_eligible": False,
        "result": "red",
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        parser.error(f"refusing to overwrite output: {args.output}")
    report = collect()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({"output": str(args.output), "result": report["result"]}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
