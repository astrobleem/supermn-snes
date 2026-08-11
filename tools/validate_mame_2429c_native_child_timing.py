#!/usr/bin/env python3
"""Check observed `$02429C` native-child dynamic costs in exact MAME.

The parent coroutine cannot safely acquire a virtual-clock owner until its
native children have a compatible ledger.  This reducer narrows the retained
original-MAME trace to the four direct native child bodies reached from the
root's guarded fusion/direct-call cluster.  It proves only the records the
trace actually visited and retains every missing dynamic PC as a coverage gap.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from collections import Counter
from pathlib import Path
from typing import Any

import audit_stage3_2429c_charge_blocks as inventory
import validate_mame_25110_branch_timing as trace_common


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SUMMARY = ROOT / "build/mame-25110-irq-phase-current-f369-v5/summary.json"
DEFAULT_PROGRAM = ROOT / "data/superman_m68k.bin"
DEFAULT_CYCLES = ROOT / "src/m68k_cpu000_static_cycles.bin"
NATIVE_CHILDREN = frozenset({0x023342, 0x023E34, 0x0235E0, 0x0259CA})


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def child_dynamic_pcs() -> dict[int, str]:
    transpiler = inventory.common.load_transpiler()
    records: dict[int, str] = {}
    for entry in NATIVE_CHILDREN:
        for block in inventory.common.basic_blocks(transpiler, entry):
            for instruction in block:
                kind = inventory.common.timing_kind(instruction)
                if kind is not None:
                    records[instruction.address] = kind
    if len(records) != 19:
        raise RuntimeError(f"native-child dynamic inventory changed: {len(records)} PCs")
    return records


def branch_prediction(
    pc: int, opcode: int, sr: int, registers: list[int], program: bytes
) -> tuple[int, int, str]:
    condition_code = (opcode >> 8) & 0x0F
    extension = int.from_bytes(program[pc + 2:pc + 4], "big")
    target = (pc + 2 + trace_common.signed16(extension)) & 0xFFFFFF
    if (opcode & 0xF0F8) == 0x50C8:
        if trace_common.condition(condition_code, sr):
            return 12, (pc + 4) & 0xFFFFFF, "dbcc:condition_true_exit"
        register = opcode & 0x0007
        decremented = (int(registers[register]) - 1) & 0xFFFF
        if decremented == 0xFFFF:
            return 14, (pc + 4) & 0xFFFFFF, "dbcc:expired_exit"
        return 10, target, "dbcc:decrement_branch"
    if trace_common.condition(condition_code, sr):
        return 10, target, "bcc_word:taken"
    return 12, (pc + 4) & 0xFFFFFF, "bcc_word:not_taken"


def movem_prediction(pc: int, opcode: int, program: bytes, static: bytes) -> tuple[int, str]:
    mask = int.from_bytes(program[pc + 2:pc + 4], "big")
    amount = mask.bit_count()
    # The audit accepts only actual MOVEM opcodes, not EXT encodings. CPU-000
    # adds 4 cycles/word register or 8 cycles/long register to the static base.
    unit = 8 if opcode & 0x0040 else 4
    return static[opcode] + amount * unit, "movem_long" if unit == 8 else "movem_word"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--summary", type=Path, default=DEFAULT_SUMMARY)
    parser.add_argument("--program", type=Path, default=DEFAULT_PROGRAM)
    parser.add_argument("--cycles", type=Path, default=DEFAULT_CYCLES)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        parser.error(f"refusing to overwrite output: {args.output}")
    for path in (args.summary, args.program, args.cycles):
        if not path.is_file():
            parser.error(f"missing input: {path}")
    summary = json.loads(args.summary.read_text(encoding="utf-8"))
    if summary.get("mame", {}).get("version") != "0.287 (mame0287)":
        raise RuntimeError("summary is not exact MAME 0.287 evidence")
    trace = trace_common.resolve(args.summary, summary["capture"]["debugger_trace"])
    program = args.program.read_bytes()
    static = args.cycles.read_bytes()
    if len(program) != 0x80000 or len(static) != 0x10000:
        raise RuntimeError("invalid original program or CPU-000 static-cycle input")
    dynamic = child_dynamic_pcs()
    rows = trace_common.parse_trace(trace)
    observed: Counter[int] = Counter()
    outcomes: Counter[str] = Counter()
    failures: list[dict[str, Any]] = []
    skipped_interrupts = 0
    for current, following in zip(rows, rows[1:]):
        pc = int(current["pc"])
        kind = dynamic.get(pc)
        if kind is None:
            continue
        if following["interrupt_before"]:
            skipped_interrupts += 1
            continue
        opcode = int.from_bytes(program[pc:pc + 2], "big")
        if kind == "conditional_branch_or_loop":
            predicted, expected_pc, outcome = branch_prediction(
                pc, opcode, int(current["sr"]), list(current["d"]), program
            )
        elif kind == "movem_register_count":
            predicted, outcome = movem_prediction(pc, opcode, program, static)
            expected_pc = (pc + 4) & 0xFFFFFF
        else:
            raise RuntimeError(f"unhandled native child timing kind {kind} at ${pc:06X}")
        actual_cycles = int(following["cycle"]) - int(current["cycle"])
        observed[pc] += 1
        outcomes[outcome] += 1
        if actual_cycles != predicted or int(following["pc"]) != expected_pc:
            failures.append(
                {
                    "pc": f"{pc:06X}",
                    "kind": kind,
                    "outcome": outcome,
                    "expected_cycles": predicted,
                    "actual_cycles": actual_cycles,
                    "expected_pc": f"{expected_pc:06X}",
                    "actual_pc": f"{int(following['pc']):06X}",
                }
            )
    report = {
        "scope": (
            "read-only exact-MAME subset for `$02429C` direct native children; "
            "unobserved child paths remain unledgered and this is not SNES/timer proof"
        ),
        "inputs": {
            "summary": {"path": str(args.summary.resolve()), "sha256": sha256(args.summary)},
            "trace": {"path": str(trace), "sha256": sha256(trace)},
            "program": {"path": str(args.program.resolve()), "sha256": sha256(args.program)},
            "static_cycles": {"path": str(args.cycles.resolve()), "sha256": sha256(args.cycles)},
        },
        "native_child_entries": [f"{entry:06X}" for entry in sorted(NATIVE_CHILDREN)],
        "dynamic_child_pcs": {f"{pc:06X}": dynamic[pc] for pc in sorted(dynamic)},
        "observed_counts": {f"{pc:06X}": observed[pc] for pc in sorted(observed)},
        "unobserved_dynamic_child_pcs": [f"{pc:06X}" for pc in sorted(set(dynamic) - set(observed))],
        "outcomes": dict(sorted(outcomes.items())),
        "interrupt_boundaries_skipped": skipped_interrupts,
        "failures": failures,
        "result": "green" if observed and not failures else "red",
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({"result": report["result"], "observed": sum(observed.values()), "output": str(args.output)}, sort_keys=True))
    return 0 if report["result"] == "green" else 1


if __name__ == "__main__":
    raise SystemExit(main())
