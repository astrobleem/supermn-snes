#!/usr/bin/env python3
"""Reduce the MAME scheduler-cycle probe without overstating read taps.

The raw scheduler capture is useful for locating the accelerated-owner seams,
but MAME program-space read taps also see data reads.  This reducer therefore
uses the instruction-only debugger trace for IRQ interruption PCs and cycle
cadence, and keeps the program-read observations explicitly qualified.  It
does not derive opcode retirement or block timing from a read-tap label.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from collections import Counter
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
RAW_SUMMARY = ROOT / "build" / "mame-scheduler-cycle-phase-current-a976-14743-14747-v3" / "summary.json"
TRACE_SUMMARY = ROOT / "build" / "mame-stage3-irq-phase-current-a976-14743-14747-v2" / "summary.json"
EXPECTED_MAME = {
    "gnome_content_revision": "263",
    "path": "/tmp/mame-4339-recovery/root/mame",
    "sha256": "297843036f728695878300f3bd9949122907cd83bfd6d501875e9a49cd950c6f",
    "snap_revision": "4339",
    "version": "0.287 (mame0287)",
}
EXPECTED_INTERRUPTS = ("000818", "000818", "0259B0", "02582E", "000810")
EXPECTED_PERIODS = (139300, 139302, 139296, 139342)
EXPECTED_RAW_LABELS = {
    "collision_25110",
    "collision_2582e",
    "collision_259b0",
    "collision_return_259c8",
    "game_tick",
    "idle_818",
    "irq_6c4",
    "rng_814",
    "scheduler_scan_74c",
    "scheduler_select_75c",
    "scheduler_switch_in_796",
    "scheduler_switch_out_532",
    "task15_2429c",
    "task15_dispatch_242be",
}
STATE = re.compile(r"^M68K_STATE ([0-9A-F]+) ([0-9A-F]+) ")
INTERRUPT = re.compile(r"interrupted at ([0-9A-F]{6}), IRQ 6")


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def read_json(path: Path) -> dict[str, Any]:
    if not path.is_file():
        raise RuntimeError(f"missing retained artifact: {path}")
    return json.loads(path.read_text(encoding="utf-8"))


def resolve(summary: Path, item: dict[str, Any]) -> Path:
    path = Path(str(item["path"]))
    path = path if path.is_absolute() else summary.parent / path
    if not path.is_file():
        raise RuntimeError(f"missing retained artifact: {path}")
    if sha256(path) != item["sha256"]:
        raise RuntimeError(f"SHA-256 mismatch: {path}")
    return path


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--raw-summary", type=Path, default=RAW_SUMMARY)
    parser.add_argument("--trace-summary", type=Path, default=TRACE_SUMMARY)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        parser.error(f"refusing to overwrite output: {args.output}")
    return args


def main() -> int:
    args = parse_args()
    raw_summary = read_json(args.raw_summary)
    trace_summary = read_json(args.trace_summary)
    if raw_summary.get("mame") != EXPECTED_MAME or trace_summary.get("mame") != EXPECTED_MAME:
        raise RuntimeError("both inputs must be the exact retained MAME 0.287 oracle")
    if raw_summary.get("movie") != trace_summary.get("movie"):
        raise RuntimeError("raw scheduler probe and instruction trace use different movies")
    if raw_summary.get("runtime_architectural_mutations") != [] or trace_summary.get("runtime_architectural_mutations") != []:
        raise RuntimeError("an input declares an architectural mutation")

    raw_log = resolve(args.raw_summary, raw_summary["capture"]["metadata"])
    trace_log = resolve(args.trace_summary, trace_summary["capture"]["debugger_trace"])
    raw_rows = read_jsonl(raw_log)
    raw_events = [row for row in raw_rows if row.get("event") != "summary"]
    raw_boundaries = [
        int(row["tick"])
        for row in raw_events
        if row.get("event") == "boundary" and row.get("label") == "game_tick"
    ]
    raw_cycles = [int(row["cycles"]) for row in raw_events]
    raw_labels = Counter(str(row.get("label")) for row in raw_events)
    raw_irq = [
        row for row in raw_events
        if row.get("label") == "irq_6c4" and int(row.get("PC", -1)) == 0x000078
    ]

    trace_events = read_jsonl(resolve(args.trace_summary, trace_summary["capture"]["metadata"]))
    trace_irq = [
        row for row in trace_events
        if row.get("label") == "irq_6c4" and int(row.get("PC", -1)) == 0x000078
    ]
    trace_irq_cycles = [int(row["cycles"]) for row in trace_irq]
    periods = tuple(
        trace_irq_cycles[index + 1] - trace_irq_cycles[index]
        for index in range(len(trace_irq_cycles) - 1)
    )

    last_state: tuple[int, int] | None = None
    interruptions: list[dict[str, int | str]] = []
    for line in trace_log.read_text(encoding="utf-8").splitlines():
        state = STATE.match(line)
        if state:
            last_state = (int(state.group(1), 16), int(state.group(2), 16))
            continue
        interruption = INTERRUPT.search(line)
        if interruption:
            if last_state is None:
                raise RuntimeError("interrupt line appears before a debugger state")
            interruptions.append(
                {
                    "interrupted_pc": interruption.group(1),
                    "last_instruction_start_cycles": last_state[0],
                    "last_debugger_pc": f"{last_state[1]:06X}",
                }
            )

    checks = {
        "raw_boundaries_exact": raw_boundaries == [14743, 14744, 14745, 14746, 14747],
        "raw_cycles_monotonic": raw_cycles == sorted(raw_cycles),
        "raw_has_all_owner_labels": set(raw_labels) == EXPECTED_RAW_LABELS,
        "instruction_trace_interrupt_pcs_exact": tuple(
            row["interrupted_pc"] for row in interruptions
        ) == EXPECTED_INTERRUPTS,
        "instruction_trace_periods_exact": periods == EXPECTED_PERIODS,
        "raw_and_trace_irq_cycles_agree": [int(row["cycles"]) for row in raw_irq]
        == trace_irq_cycles,
        "raw_probe_is_explicitly_not_instruction_attribution": True,
    }
    report = {
        "scope": (
            "exact-MAME original-code scheduler owner-activity capture joined "
            "to its instruction-only IRQ trace; not a SNES differential, "
            "per-block timing model, virtual-clock repair, rate, or "
            "playthrough result"
        ),
        "mame": EXPECTED_MAME,
        "movie": raw_summary["movie"],
        "raw_program_read_probe": {
            "summary": str(args.raw_summary.resolve()),
            "summary_sha256": sha256(args.raw_summary),
            "log": str(raw_log),
            "log_sha256": sha256(raw_log),
            "events": len(raw_events),
            "boundaries": raw_boundaries,
            "label_counts": dict(sorted(raw_labels.items())),
            "qualification": (
                "program-space read taps include data reads and prefetches; "
                "their labels establish owner activity only, never completed "
                "instruction/block attribution"
            ),
        },
        "instruction_only_irq_trace": {
            "summary": str(args.trace_summary.resolve()),
            "summary_sha256": sha256(args.trace_summary),
            "log": str(trace_log),
            "log_sha256": sha256(trace_log),
            "irq_cycles": trace_irq_cycles,
            "periods": periods,
            "interruptions": interruptions,
        },
        "checks": checks,
        "promotion_blocked": True,
        "not_proven": [
            "scheduler basic-block costs",
            "native parent-child handoff timing",
            "common virtual MC68000 clock",
            "SNES IRQ delivery or Stage-3 repair",
            "Stage-3 rate or full playthrough",
        ],
        "result": "green" if all(checks.values()) else "red",
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({"result": report["result"], "output": str(args.output.resolve())}, sort_keys=True))
    return 0 if report["result"] == "green" else 1


if __name__ == "__main__":
    raise SystemExit(main())
