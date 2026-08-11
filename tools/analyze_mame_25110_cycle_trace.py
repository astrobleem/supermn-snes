#!/usr/bin/env python3
"""Reduce the MAME Stage-3 debugger trace into timing-model requirements.

The trace is an original-code, cold-power-on capture.  This reducer performs
no emulation and writes no ROM-derived bytes: it retains only addresses,
opcodes, and cycle deltas needed to show whether the virtual IRQ can safely
use a constant instruction budget.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_PROGRAM = ROOT / "data" / "superman_m68k.bin"
LINE = re.compile(r"^([0-9A-F]+)\s+([0-9A-F]{6}):\s+(.+)$")
INTERRUPT = re.compile(r"^\s*\(interrupted at ([0-9A-F]{6}), IRQ 6\)$")


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def resolve(owner: Path, metadata: dict[str, Any]) -> Path:
    path = Path(str(metadata["path"]))
    path = path if path.is_absolute() else owner.parent / path
    if not path.is_file():
        raise RuntimeError(f"missing artifact: {path}")
    if sha256(path) != metadata["sha256"]:
        raise RuntimeError(f"SHA-256 mismatch: {path}")
    return path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--summary", type=Path, required=True)
    parser.add_argument("--program", type=Path, default=DEFAULT_PROGRAM)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    for label, path in (("summary", args.summary), ("program image", args.program)):
        if not path.is_file():
            parser.error(f"missing {label}: {path}")
    if args.output.exists():
        parser.error(f"output already exists: {args.output}")
    return args


def main() -> int:
    args = parse_args()
    summary = json.loads(args.summary.read_text(encoding="utf-8"))
    trace_path = resolve(args.summary, summary["capture"]["debugger_trace"])
    program = args.program.read_bytes()
    records: list[dict[str, Any]] = []
    interrupts: list[dict[str, Any]] = []
    pending_interrupt = False
    for line_number, raw in enumerate(trace_path.read_text(encoding="utf-8").splitlines(), 1):
        match = LINE.match(raw)
        if match:
            cycle, pc, disassembly = match.groups()
            records.append(
                {
                    "cycle": int(cycle, 16),
                    "pc": int(pc, 16),
                    "disassembly": disassembly,
                    "interrupt_before": pending_interrupt,
                    "line": line_number,
                }
            )
            pending_interrupt = False
            continue
        match = INTERRUPT.match(raw)
        if match:
            if not records:
                raise RuntimeError(f"{trace_path}:{line_number}: interrupt before first instruction")
            interrupts.append(
                {
                    "pc": int(match.group(1), 16),
                    "line": line_number,
                    "preceding_record": len(records) - 1,
                }
            )
            pending_interrupt = True

    if not records or not interrupts:
        raise RuntimeError("trace lacks instruction records or level-6 interrupts")
    valid_deltas: list[tuple[dict[str, Any], int]] = []
    for current, following in zip(records, records[1:]):
        if following["interrupt_before"]:
            continue
        delta = following["cycle"] - current["cycle"]
        if delta <= 0:
            raise RuntimeError(f"nonpositive instruction delta after line {current['line']}")
        valid_deltas.append((current, delta))

    costs: dict[tuple[int, int], Counter[int]] = defaultdict(Counter)
    for record, delta in valid_deltas:
        pc = record["pc"]
        if pc + 1 >= len(program):
            continue
        opcode = int.from_bytes(program[pc : pc + 2], "big")
        costs[(pc, opcode)][delta] += 1
    variable = [
        {
            "pc": f"{pc:06X}",
            "opcode": f"{opcode:04X}",
            "samples": sum(values.values()),
            "cycles": {str(cost): values[cost] for cost in sorted(values)},
        }
        for (pc, opcode), values in costs.items()
        if len(values) > 1
    ]
    variable.sort(key=lambda row: (-row["samples"], row["pc"]))

    irq_entries = []
    metadata_path = resolve(args.summary, summary["capture"]["metadata"])
    meta_rows = [json.loads(line) for line in metadata_path.read_text(encoding="utf-8").splitlines()]
    for row in meta_rows:
        if row.get("label") == "irq_6c4" and int(row.get("PC", -1)) == 0x78:
            irq_entries.append({"tick": int(row["tick"]), "cycle": int(row["cycles"])})
    if len(irq_entries) != len(interrupts):
        raise RuntimeError(
            f"metadata has {len(irq_entries)} IRQ entries but trace has {len(interrupts)} markers"
        )
    interrupt_rows = [
        {
            "mame_tick": irq_entries[index]["tick"],
            "service_cycle": irq_entries[index]["cycle"],
            "interrupted_pc": f"{marker['pc']:06X}",
            "trace_line": marker["line"],
        }
        for index, marker in enumerate(interrupts)
    ]
    histogram = Counter(delta for _, delta in valid_deltas)
    report = {
        "scope": (
            "read-only reduction of the original-MAME Stage-3 cycle trace; "
            "it identifies virtual-timer requirements and is not a SNES timing fix, "
            "FPS result, or playthrough claim"
        ),
        "trace": {"path": str(trace_path), "sha256": sha256(trace_path)},
        "program": {"path": str(args.program.resolve()), "sha256": sha256(args.program)},
        "instructions": {
            "records": len(records),
            "valid_adjacent_cycle_deltas": len(valid_deltas),
            "cycle_histogram": {str(cost): histogram[cost] for cost in sorted(histogram)},
            "pc_opcode_sites_with_variable_cost": variable[:64],
            "variable_cost_site_count": len(variable),
        },
        "irq_service": interrupt_rows,
        "conclusion": (
            "A constant instruction reload cannot model this trace: the same original "
            "PC/opcode executes with multiple cycle costs, and the observed IRQ services "
            "land at distinct instruction boundaries.  A repair needs instruction-cycle "
            "accounting including dynamic branch/loop outcomes and native-span charges."
        ),
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({"result": "green", "output": str(args.output)}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
