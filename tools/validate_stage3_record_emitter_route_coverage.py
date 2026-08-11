#!/usr/bin/env python3
"""Reduce the active Stage-3 record-emitter route failure and its candidate.

This joins three kinds of evidence without overstating any one of them:
the original MAME instruction trace proves the logical leaves execute, the
same safe-checkpoint SNES native-entry traces prove whether their wrappers
actually fire, and the bounded MAME/native-off/native-on parent differential
checks the complete real-return semantic contract.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
ACTIVE_SHA256 = "a9765fbfbd2a0863f093ff1bb887cfd422ecde26e3c46bae0afd56bf8b1dac60"
CANDIDATE_SHA256 = "387855daec19244788aec05bfaca3b471399844131a768733b3d917a87448219"
STATE_SHA256 = "bf4dfd88771f9b3d8a800c13bd451b5fc375b6bb721165a53fa738050199f1c8"

MAME_TRACE = ROOT / "build/mame-stage3-irq-phase-current-a976-14743-14747-v2/trace/m68k.log"
ACTIVE_TRACE = ROOT / "build/trace-stage3-all-native-entries-current-a976-safe14743-v1/trace.json"
CANDIDATE_TRACE = ROOT / "build/trace-stage3-record-emitter-route-current-a976-safe14743-native-on-v1/trace.json"
SEMANTIC = ROOT / "build/validate-stage3-record-emitter-route-current-a976-isolated-v1.jsonl"
RATE = ROOT / "build/measure-stage3-record-emitter-route-current-a976-safe14743-v1/summary.json"
FRESH_FAILURE = ROOT / "build/fresh-campaign-stage3-record-emitter-route-current-a976-to2958-prefailure-v1/summary.json"

REPAIRED_LEAVES = {
    "027B44": "entry_27b44@94CB40",
    "027B7C": "entry_27b7c@94CEC0",
}
REMAINING_DIRECT_LEAF = "02E524"
REMAINING_DIRECT_ENTRY = "entry_2e524@9DE190"


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def mame_counts(path: Path) -> dict[str, int]:
    text = path.read_text(encoding="utf-8", errors="replace")
    return {
        pc: len(re.findall(r"\|\s*" + pc + r":", text, flags=re.IGNORECASE))
        for pc in (*REPAIRED_LEAVES, REMAINING_DIRECT_LEAF)
    }


def semantic_summary(path: Path) -> tuple[dict, dict]:
    rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
    if not rows or rows[0].get("event") != "provenance" or rows[-1].get("event") != "summary":
        raise RuntimeError("parent differential is malformed")
    return rows[0], rows[-1]


def collect() -> dict:
    for path in (MAME_TRACE, ACTIVE_TRACE, CANDIDATE_TRACE, SEMANTIC, RATE, FRESH_FAILURE):
        if not path.is_file():
            raise RuntimeError(f"missing retained evidence: {path}")

    active = load_json(ACTIVE_TRACE)
    candidate = load_json(CANDIDATE_TRACE)
    provenance, semantic = semantic_summary(SEMANTIC)
    rate = load_json(RATE)
    fresh_failure = load_json(FRESH_FAILURE)
    original = mame_counts(MAME_TRACE)
    if active["rom_sha256"] != ACTIVE_SHA256:
        raise RuntimeError("active trace ROM identity changed")
    if candidate["rom_sha256"] != CANDIDATE_SHA256:
        raise RuntimeError("candidate trace ROM identity changed")
    if active["state_sha256"] != STATE_SHA256 or candidate["state_sha256"] != STATE_SHA256:
        raise RuntimeError("route traces do not share the retained safe checkpoint")
    if provenance["rom_sha256"] != CANDIDATE_SHA256 or semantic["result"] != "green":
        raise RuntimeError("candidate parent three-way differential is not green")
    if semantic["semantic_cases"] != 12 or semantic["route_probes"] != 2:
        raise RuntimeError("candidate parent differential coverage changed")
    if rate["rom_sha256"] != CANDIDATE_SHA256:
        raise RuntimeError("candidate rate report ROM identity changed")
    failure = fresh_failure.get("failure", {})
    if (
        fresh_failure.get("result") != "red"
        or fresh_failure.get("rom_sha256") != CANDIDATE_SHA256
        or failure.get("mame_tick") != 2958
        or failure.get("source_input_tick") != 2956
        or failure.get("comparison", {}).get("mismatches") != {"action": {"mame": 1, "snes": 0}}
    ):
        raise RuntimeError("candidate fresh Stage-1 rejection changed")

    active_counts = {
        pc: int(active["event_counts"].get(label, -1))
        for pc, label in REPAIRED_LEAVES.items()
    }
    candidate_counts = {
        pc: int(candidate["event_counts"].get(label, -1))
        for pc, label in REPAIRED_LEAVES.items()
    }
    if not all(original[pc] > 0 for pc in REPAIRED_LEAVES):
        raise RuntimeError("original MAME trace does not execute both leaves")
    if any(active_counts[pc] != 0 for pc in REPAIRED_LEAVES):
        raise RuntimeError("active native-on trace unexpectedly reaches an emitter")
    if not all(candidate_counts[pc] > 0 for pc in REPAIRED_LEAVES):
        raise RuntimeError("candidate native-on trace does not reach both emitters")

    source = (ROOT / "src/escbank7.pasm").read_text(encoding="utf-8")
    xdd_bank2 = source[source.index("xdd_bank2:") : source.index("xdd_bank1:")]
    direct_table = (ROOT / "tools/gen_xlat_table.py").read_text(encoding="utf-8")
    if "0x02E524" not in direct_table:
        raise RuntimeError("$02E524 no longer declares sparse direct routing")
    if "cmp #$E524" in xdd_bank2:
        raise RuntimeError("$02E524 source route is no longer an unresolved gap")
    remaining = {
        "logical_pc": REMAINING_DIRECT_LEAF,
        "mame_instruction_count": original[REMAINING_DIRECT_LEAF],
        "active_native_on_entry_count": int(
            active["event_counts"].get(REMAINING_DIRECT_ENTRY, -1)
        ),
        "candidate_native_on_entry_count": int(
            candidate["event_counts"].get(REMAINING_DIRECT_ENTRY, -1)
        ),
        "table_declares_sparse_direct_route": True,
        "sparse_dispatcher_has_exact_case": False,
        "classification": "native_hle_route_coverage_gap",
    }
    if (
        remaining["mame_instruction_count"] <= 0
        or remaining["active_native_on_entry_count"] != 0
        or remaining["candidate_native_on_entry_count"] != 0
    ):
        raise RuntimeError("$02E524 remaining-route classification changed")

    native_on = next(item for item in rate["variants"] if item["name"] == "production_native_on")
    route_counts = native_on["native_route_counts"]
    rate_counts = {
        pc: int(route_counts.get(
            "stage3_027b44_94cb40" if pc == "027B44" else "stage3_027b7c_94cec0",
            -1,
        ))
        for pc in REPAIRED_LEAVES
    }
    if not all(rate_counts[pc] > 0 for pc in REPAIRED_LEAVES):
        raise RuntimeError("candidate sustained run does not retain both route counts")
    cycles = rate["comparison"]["production_native_on_cycles_per_tick"]
    budget = rate["comparison"]["budget_cycles_per_tick"]

    return {
        "scope": (
            "Stage-3 record-emitter native-route diagnosis: original MAME instruction "
            "activity, exact same-state MAME/native-off/native-on bounded parent "
            "semantics, and safe-checkpoint SNES route firing; not fresh-boot FPS, "
            "a common-clock repair, or full-playthrough proof"
        ),
        "active": {
            "rom_sha256": ACTIVE_SHA256,
            "safe_checkpoint_sha256": STATE_SHA256,
            "native_on_emitter_entry_counts": active_counts,
            "result": "red",
        },
        "original_mame": {
            "trace": str(MAME_TRACE),
            "trace_sha256": digest(MAME_TRACE),
            "instruction_counts": original,
            "result": "green",
        },
        "candidate": {
            "rom_sha256": CANDIDATE_SHA256,
            "safe_checkpoint_sha256": STATE_SHA256,
            "native_on_emitter_entry_counts": candidate_counts,
            "bounded_same_state_three_way": {
                "artifact": str(SEMANTIC),
                "sha256": digest(SEMANTIC),
                "mame_native_off_native_on": True,
                "semantic_cases": semantic["semantic_cases"],
                "route_probes": semantic["route_probes"],
                "result": semantic["result"],
            },
            "sustained_checkpoint": {
                "artifact": str(RATE),
                "emitter_route_counts": rate_counts,
                "native_on_cycles_per_tick": cycles,
                "budget_cycles_per_tick": budget,
                "meets_budget": False,
                "result": rate["result"],
            },
            "fresh_power_on": {
                "artifact": str(FRESH_FAILURE),
                "pre_input_state_sha256": failure["pre_failure_input_state"]["sha256"],
                "input_tick": failure["source_input_tick"],
                "response_tick": failure["mame_tick"],
                "mame_action": failure["comparison"]["mame"]["action"],
                "native_on_action": failure["comparison"]["snes"]["action"],
                "result": fresh_failure["result"],
                "promotion_eligible": False,
            },
        },
        "newly_exposed_remaining_gap": remaining,
        "classification": {
            "cause": "native_hle",
            "root": (
                "bank-$02 enters the compact $9D:DA00 sparse dispatcher, but its "
                "$027B44/$027B7C comparisons were absent; xdd_miss rejoined xd_table "
                "and interpreted both record emitters despite their live native parent"
            ),
            "rejected_experiment": (
                "the candidate directs $027952's guarded $027AEA child and adds exact "
                "sparse cases to wrappers $94:CB40/$94:CEC0, which is locally exact at "
                "the Stage-3 checkpoint but not a safe global fix"
            ),
            "fresh_root": (
                "the $9D:DA00 sparse dispatcher is shared by Stage 1; canonical PC, "
                "pointer, and stack guards do not establish Stage-3 provenance, and the "
                "candidate deterministically delays the fresh tick-2,956 Button 1 response"
            ),
            "rate_status": (
                "improved local checkpoint throughput but still misses the 358K budget; "
                "the independent hardware-boundary/common-clock blocker and the live "
                "$02E524 sparse-route gap remain open"
            ),
        },
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
