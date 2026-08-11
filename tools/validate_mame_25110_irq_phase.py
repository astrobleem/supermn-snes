#!/usr/bin/env python3
"""Validate the retained original-MAME cycle oracle for the Stage-3 IRQ seam.

The expected cycle values below are deliberately narrow: they identify the
authenticated ROM/movie/tick window, not a general hardware cadence formula.
They prevent a future timer change from being justified by a trace that lost
the observed cycle source or interrupted a different Stage-3 path.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path
from typing import Any


EXPECTED_INTERRUPTS = ("000818", "0259B0", "02582E", "000810")
EXPECTED_PERIODS = (139302, 139296, 139342)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def resolve(owner: Path, item: dict[str, Any]) -> Path:
    path = Path(str(item["path"]))
    path = path if path.is_absolute() else owner.parent / path
    if not path.is_file():
        raise RuntimeError(f"missing retained artifact: {path}")
    if sha256(path) != item["sha256"]:
        raise RuntimeError(f"SHA-256 mismatch: {path}")
    return path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--summary", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if not args.summary.is_file():
        parser.error(f"missing summary: {args.summary}")
    if args.output.exists():
        parser.error(f"output already exists: {args.output}")
    return args


def main() -> int:
    args = parse_args()
    source = json.loads(args.summary.read_text(encoding="utf-8"))
    capture = source["capture"]
    meta_path = resolve(args.summary, capture["metadata"])
    trace_path = resolve(args.summary, capture["debugger_trace"])
    rows = [json.loads(line) for line in meta_path.read_text(encoding="utf-8").splitlines()]
    events = [row for row in rows if row.get("event") != "summary"]
    boundaries = [row for row in events if row.get("event") == "boundary"]
    ticks = [int(row["tick"]) for row in boundaries]
    boundary_cycles = [int(row["cycles"]) for row in boundaries]
    irq_entries = [
        row
        for row in events
        if row.get("label") == "irq_6c4" and int(row.get("PC", -1)) == 0x000078
    ]
    irq_cycles = [int(row["cycles"]) for row in irq_entries]
    periods = tuple(
        irq_cycles[index + 1] - irq_cycles[index]
        for index in range(len(irq_cycles) - 1)
    )
    trace = trace_path.read_text(encoding="utf-8")
    interrupts = tuple(re.findall(r"interrupted at ([0-9A-F]{6}), IRQ 6", trace))
    tick_14746_2582e = [
        row
        for row in events
        if row.get("tick") == 14746
        and row.get("label") == "collision_2582e"
        # The program-read tap observes the opcode fetch at $2582E while
        # MAME's architectural PC still names its prefetch address $2582C.
        and int(row.get("PC", -1)) == 0x02582C
    ]
    tick_14746_irq = [
        row
        for row in events
        if row.get("tick") == 14746 and row.get("label") == "irq_6c4"
    ]
    checks = {
        "window_is_retained_four_ticks": ticks == [14744, 14745, 14746, 14747],
        "one_irq_entry_per_retained_tick": len(irq_entries) == 4,
        "cycle_periods_match_exact_oracle": periods == EXPECTED_PERIODS,
        "interrupt_pcs_match_exact_oracle": interrupts == EXPECTED_INTERRUPTS,
        "tick_14746_irq_lands_at_2582e_cycle": bool(tick_14746_2582e)
        and bool(tick_14746_irq)
        and any(
            int(collision["cycles"]) == int(irq["cycles"])
            for collision in tick_14746_2582e
            for irq in tick_14746_irq
        ),
        "source_declares_read_only": source.get("runtime_architectural_mutations") == [],
    }
    report = {
        "scope": (
            "artifact-identity regression for the original-MAME Stage-3 IRQ "
            "cycle oracle; not a SNES timing fix, FPS result, or playthrough claim"
        ),
        "source_summary": str(args.summary.resolve()),
        "source_summary_sha256": sha256(args.summary),
        "metadata": str(meta_path),
        "debugger_trace": str(trace_path),
        "boundaries": {"ticks": ticks, "cycles": boundary_cycles},
        "irq_entries": {"cycles": irq_cycles, "periods": periods},
        "interrupt_pcs": interrupts,
        "checks": checks,
        "result": "green" if all(checks.values()) else "red",
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({"result": report["result"], "output": str(args.output)}, sort_keys=True))
    return 0 if report["result"] == "green" else 1


if __name__ == "__main__":
    raise SystemExit(main())
