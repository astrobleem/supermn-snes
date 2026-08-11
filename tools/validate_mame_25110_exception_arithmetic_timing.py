#!/usr/bin/env python3
"""Pin the remaining exception/arithmetic timing facts in the Stage-3 trace.

This reducer deliberately keeps two distinct facts separate:

* every observed ``TRAP #n`` follows MAME's CPU-000 exception-vector timing;
* the three retained multiply/divide operand situations have the exact observed
  instruction-to-instruction timing.

The latter is a regression sentinel, not a claim that the three samples are a
complete 68000 multiply/divide formula.  A virtual-IRQ implementation must not
quietly substitute the static opcode table at any of these sites, and must add
general operand coverage before it can claim a complete arithmetic model.

The tool is read-only: it consumes a retained original-MAME trace and source
files, and writes only its requested JSON report.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from collections import Counter
from pathlib import Path
from typing import Any

import audit_m68k_cycle_model as static_audit
import validate_mame_25110_branch_timing as branch_timing


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_PROGRAM = ROOT / "data" / "superman_m68k.bin"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def resolve(owner: Path, item: dict[str, Any]) -> Path:
    path = Path(str(item["path"]))
    path = path if path.is_absolute() else owner.parent / path
    if not path.is_file() or sha256(path) != item["sha256"]:
        raise RuntimeError(f"unauthenticated retained artifact: {path}")
    return path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--summary", type=Path, required=True)
    parser.add_argument("--m68kmake", type=Path, required=True)
    parser.add_argument("--m68k-list", type=Path, required=True)
    parser.add_argument("--m68kcpu", type=Path, required=True)
    parser.add_argument("--m68kcpu-h", type=Path, required=True)
    parser.add_argument("--m68kops", type=Path, required=True)
    parser.add_argument("--program", type=Path, default=DEFAULT_PROGRAM)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    for label, path in (
        ("capture summary", args.summary),
        ("MAME m68kmake.py", args.m68kmake),
        ("MAME m68k_in.lst", args.m68k_list),
        ("MAME m68kcpu.cpp", args.m68kcpu),
        ("MAME m68kcpu.h", args.m68kcpu_h),
        ("MAME m68kops.cpp", args.m68kops),
        ("program image", args.program),
    ):
        if not path.is_file():
            parser.error(f"missing {label}: {path}")
    if args.output.exists():
        parser.error(f"output already exists: {args.output}")
    return args


def word(program: bytes, pc: int) -> int:
    return int.from_bytes(program[pc : pc + 2], "big")


def main() -> int:
    args = parse_args()
    summary = json.loads(args.summary.read_text(encoding="utf-8"))
    if summary.get("mame", {}).get("version") != "0.287 (mame0287)":
        raise RuntimeError("capture is not the exact MAME 0.287 oracle")
    trace = resolve(args.summary, summary["capture"]["debugger_trace"])
    program = args.program.read_bytes()
    if len(program) != 0x80000:
        raise RuntimeError("expected 512 KiB MC68000 program image")
    static = static_audit.build_static_cycles(
        static_audit.load_m68kmake(args.m68kmake), args.m68k_list
    )
    cpu = args.m68kcpu.read_text(encoding="utf-8", errors="replace")
    cpu_h = args.m68kcpu_h.read_text(encoding="utf-8", errors="replace")
    ops = args.m68kops.read_text(encoding="utf-8", errors="replace")
    required_source = (
        "34, /* 32: TRAP #0",
        "34, /* 47: TRAP #15",
        "inline void m68ki_exception_trapN(u32 vector)",
        "m_icount -= m_cyc_exception[vector];",
        "void m68000_musashi_device::x4e40_trap_071234fc()",
        "m68ki_exception_trapN(EXCEPTION_TRAP_BASE + (m_ir & 0xf));",
        "m_icount -= m_cyc_instruction[m_ir];",
    )
    if any(text not in (cpu + cpu_h + ops) for text in required_source):
        raise RuntimeError("MAME CPU-000 exception timing source changed")

    records = branch_timing.parse_trace(trace)
    trap_rows: list[dict[str, Any]] = []
    arithmetic_rows: list[dict[str, Any]] = []
    unexpected_arithmetic: list[dict[str, Any]] = []
    skipped_interrupt = 0
    skipped_non_program = 0
    by_kind: Counter[str] = Counter()

    expected_arithmetic = {
        # pc, opcode, immediate word, destination register, pre-D value:
        # observed CPU-000 cycles, static-table cycles, retained sample count.
        (0x00CA3E, 0x82FC, 0x000A, 1, 0x00000005): (140, 144, 4),
        (0x00041A, 0xCFFC, 0x00B0, 7, 0x00004357): (50, 58, 1),
        (0x00041E, 0x8FFC, 0x7FED, 7, 0x002E4BD0): (146, 162, 1),
    }
    expected_seen: Counter[tuple[int, int, int, int, int]] = Counter()

    for current, following in zip(records, records[1:]):
        if following["interrupt_before"]:
            skipped_interrupt += 1
            continue
        pc = int(current["pc"])
        if pc + 3 >= len(program):
            skipped_non_program += 1
            continue
        opcode = word(program, pc)
        observed = int(following["cycle"]) - int(current["cycle"])
        table_cycles = static[opcode]
        if 0x4E40 <= opcode <= 0x4E4F:
            trap_rows.append(
                {
                    "pc": f"{pc:06X}",
                    "opcode": f"{opcode:04X}",
                    "vector": 32 + (opcode & 0xF),
                    "static_cycles": table_cycles,
                    "observed_cycles": observed,
                }
            )
            by_kind["trap"] += 1
            continue
        mnemonic = str(current["disassembly"]).split(maxsplit=1)[0].lower()
        if not mnemonic.startswith(("muls", "mulu", "divs", "divu")):
            continue
        if observed == table_cycles:
            continue
        immediate = word(program, pc + 2)
        destination = (opcode >> 9) & 7
        pre_d = int(current["d"][destination]) & 0xFFFFFFFF
        signature = (pc, opcode, immediate, destination, pre_d)
        row = {
            "pc": f"{pc:06X}",
            "opcode": f"{opcode:04X}",
            "disassembly": current["disassembly"],
            "immediate_word": f"{immediate:04X}",
            "destination_d": destination,
            "pre_destination_d": f"{pre_d:08X}",
            "static_cycles": table_cycles,
            "observed_cycles": observed,
        }
        if signature not in expected_arithmetic:
            unexpected_arithmetic.append(row)
            continue
        arithmetic_rows.append(row)
        expected_seen[signature] += 1
        by_kind["arithmetic"] += 1

    trap_ok = bool(trap_rows) and all(
        row["static_cycles"] == 4 and row["observed_cycles"] == 34
        for row in trap_rows
    )
    arithmetic_ok = not unexpected_arithmetic and all(
        expected_seen[key] == sample_count
        and all(
            row["observed_cycles"] == expected_observed
            and row["static_cycles"] == expected_static
            for row in arithmetic_rows
            if (
                int(row["pc"], 16),
                int(row["opcode"], 16),
                int(row["immediate_word"], 16),
                int(row["destination_d"]),
                int(row["pre_destination_d"], 16),
            )
            == key
        )
        for key, (expected_observed, expected_static, sample_count) in expected_arithmetic.items()
    )
    checks = {
        "all_register_pipeline_pcs_are_trace_pc_plus_2": all(
            ((int(item["state_pc"]) - int(item["pc"])) & 0xFFFFFF) == 2
            for item in records
        ),
        "trap_vector_source_is_present": True,
        "all_observed_traps_match_cpu000_vector_32_to_47_cost": trap_ok,
        "all_retained_arithmetic_mismatch_samples_match": arithmetic_ok,
        "no_unexpected_arithmetic_static_mismatch": not unexpected_arithmetic,
    }
    report = {
        "scope": (
            "read-only original-MAME Stage-3 exception and retained arithmetic timing "
            "proof; the arithmetic rows are trace-specific regression sentinels, not "
            "a complete multiply/divide timing formula or a SNES repair"
        ),
        "inputs": {
            "summary": {"path": str(args.summary.resolve()), "sha256": sha256(args.summary)},
            "trace": {"path": str(trace.resolve()), "sha256": sha256(trace)},
            "m68kmake": {"path": str(args.m68kmake.resolve()), "sha256": sha256(args.m68kmake)},
            "m68k_list": {"path": str(args.m68k_list.resolve()), "sha256": sha256(args.m68k_list)},
            "m68kcpu": {"path": str(args.m68kcpu.resolve()), "sha256": sha256(args.m68kcpu)},
            "m68kcpu_h": {"path": str(args.m68kcpu_h.resolve()), "sha256": sha256(args.m68kcpu_h)},
            "m68kops": {"path": str(args.m68kops.resolve()), "sha256": sha256(args.m68kops)},
            "program": {"path": str(args.program.resolve()), "sha256": sha256(args.program)},
        },
        "mame_cpu000_trap_contract": {
            "static_opcode_table_cycles": 4,
            "exception_vector_32_to_47_cycles": 34,
            "observed_total_cycles": 34,
            "note": (
                "The exception path is not an additive 4+34 calculation: the retained "
                "MAME trace observes the vector timing total of 34."
            ),
        },
        "accounting": {
            "register_trace_records": len(records),
            "interrupt_boundaries_skipped": skipped_interrupt,
            "non_program_pairs_skipped": skipped_non_program,
            "by_kind": dict(sorted(by_kind.items())),
            "trap_rows": len(trap_rows),
            "arithmetic_rows": len(arithmetic_rows),
            "unexpected_arithmetic_rows": len(unexpected_arithmetic),
        },
        "retained_arithmetic_samples": arithmetic_rows,
        "unexpected_arithmetic_rows": unexpected_arithmetic,
        "checks": checks,
        "result": "green" if all(checks.values()) else "red",
        "next_requirement": (
            "Generalize multiply/divide operand timing beyond these retained samples "
            "before an implementation claims a complete dynamic CPU-000 timing model."
        ),
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({"result": report["result"], "output": str(args.output)}, sort_keys=True))
    return 0 if report["result"] == "green" else 1


if __name__ == "__main__":
    raise SystemExit(main())
