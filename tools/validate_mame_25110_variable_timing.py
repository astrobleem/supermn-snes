#!/usr/bin/env python3
"""Prove MOVEM and register-shift cycle charges in an original MAME trace.

The virtual-IRQ repair cannot charge one logical instruction per dispatch:
CPU-000 MOVEM costs depend on the extension-word register list and data-register
shift/rotate costs depend on either its encoded immediate or the pre-instruction
Dn value.  This read-only reducer evaluates those operands from the
register-qualified trace made by ``capture_mame_25110_irq_phase.py`` and
compares the predicted MAME CPU-000 cost to the next instruction timestamp.

It does not start an emulator or modify a ROM, save state, or arcade input.
The retained executable MAME trace is the timing oracle.  The MAME source
inputs authenticate the exact CPU-000 rules being reduced.
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
    parser.add_argument("--m68kops", type=Path, required=True)
    parser.add_argument("--program", type=Path, default=DEFAULT_PROGRAM)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    for label, path in (
        ("capture summary", args.summary),
        ("MAME m68kmake.py", args.m68kmake),
        ("MAME m68k_in.lst", args.m68k_list),
        ("MAME m68kcpu.cpp", args.m68kcpu),
        ("MAME m68kops.cpp", args.m68kops),
        ("program image", args.program),
    ):
        if not path.is_file():
            parser.error(f"missing {label}: {path}")
    if args.output.exists():
        parser.error(f"output already exists: {args.output}")
    return args


def popcount16(value: int) -> int:
    return (value & 0xFFFF).bit_count()


def is_movem(opcode: int) -> bool:
    # MOVEM encodes either 48xx (register list to memory) or 4Cxx (memory to
    # register list), with bit 6 selecting word/long.  Modes 0 and 1 are Dn
    # and An direct, respectively; they are not legal MOVEM effective
    # addresses and include EXT.W/EXT.L opcode encodings (for example 4880
    # and 48C0).  The mask plus memory-EA check is derived from the CPU-000
    # handlers rather than disassembly spelling.
    mode = (opcode >> 3) & 7
    return (opcode & 0xFB80) == 0x4880 and mode >= 2


def register_shift_count(opcode: int, d: list[int]) -> tuple[int, str] | None:
    """Return CPU-000 data-register shift/rotate count and its source.

    Memory shifts have ``size=11`` and a static table cost; they are excluded.
    The remaining 1110 instructions are the CPU-000 data-register shift and
    rotate forms.  For the immediate form count field zero encodes eight.
    """

    if (opcode & 0xF000) != 0xE000 or (opcode & 0x00C0) == 0x00C0:
        return None
    source_register = (opcode >> 9) & 7
    if opcode & 0x0020:
        return int(d[source_register]) & 0x3F, "register"
    encoded = source_register
    return (encoded if encoded else 8), "immediate"


def source_rules(cpu_source: str, ops_source: str) -> dict[str, int]:
    required_cpu = {
        "m_cyc_movem_w      = 4;": 4,
        "m_cyc_movem_l      = 8;": 8,
        "m_cyc_shift        = 2;": 2,
    }
    if any(text not in cpu_source for text in required_cpu):
        raise RuntimeError("MAME CPU-000 variable-cycle constants changed")
    required_ops = (
        "m_icount -= count * m_cyc_movem_w;",
        "m_icount -= count * m_cyc_movem_l;",
        "m_icount -= shift * m_cyc_shift;",
        "u32 shift = DX() & 0x3f;",
        "u32 shift = (((m_ir >> 9) - 1) & 7) + 1;",
    )
    if any(text not in ops_source for text in required_ops):
        raise RuntimeError("MAME CPU-000 MOVEM/shift handler rules changed")
    return required_cpu


def main() -> int:
    args = parse_args()
    summary = json.loads(args.summary.read_text(encoding="utf-8"))
    if summary.get("mame", {}).get("version") != "0.287 (mame0287)":
        raise RuntimeError("capture is not the exact MAME 0.287 oracle")
    trace = resolve(args.summary, summary["capture"]["debugger_trace"])
    cpu_source = args.m68kcpu.read_text(encoding="utf-8", errors="replace")
    ops_source = args.m68kops.read_text(encoding="utf-8", errors="replace")
    constants = source_rules(cpu_source, ops_source)
    program = args.program.read_bytes()
    if len(program) != 0x80000:
        raise RuntimeError("expected 512 KiB MC68000 program image")
    static = static_audit.build_static_cycles(
        static_audit.load_m68kmake(args.m68kmake), args.m68k_list
    )
    records = branch_timing.parse_trace(trace)

    checked = 0
    skipped_interrupt = 0
    skipped_non_program = 0
    mismatches = 0
    by_kind: Counter[str] = Counter()
    by_detail: Counter[str] = Counter()
    failures: list[dict[str, Any]] = []

    for current, following in zip(records, records[1:]):
        if following["interrupt_before"]:
            skipped_interrupt += 1
            continue
        pc = int(current["pc"])
        if pc + 3 >= len(program):
            skipped_non_program += 1
            continue
        opcode = int.from_bytes(program[pc : pc + 2], "big")
        static_cycles = static[opcode]
        observed = int(following["cycle"]) - int(current["cycle"])
        detail = ""
        amount = 0
        predicted: int | None = None

        if is_movem(opcode):
            mask = int.from_bytes(program[pc + 2 : pc + 4], "big")
            amount = popcount16(mask)
            long_size = bool(opcode & 0x0040)
            unit = constants["m_cyc_movem_l      = 8;"] if long_size else constants[
                "m_cyc_movem_w      = 4;"
            ]
            predicted = static_cycles + amount * unit
            detail = "movem_long" if long_size else "movem_word"
        else:
            shift = register_shift_count(opcode, list(current["d"]))
            if shift is None:
                continue
            amount, source = shift
            predicted = static_cycles + amount * constants["m_cyc_shift        = 2;"]
            detail = f"shift_{source}"

        checked += 1
        by_kind["movem" if detail.startswith("movem") else "shift_rotate"] += 1
        by_detail[detail] += 1
        if observed != predicted:
            mismatches += 1
            if len(failures) < 32:
                failure: dict[str, Any] = {
                    "pc": f"{pc:06X}",
                    "opcode": f"{opcode:04X}",
                    "disassembly": current["disassembly"],
                    "static_cycles": static_cycles,
                    "amount": amount,
                    "predicted_cycles": predicted,
                    "observed_cycles": observed,
                }
                if detail.startswith("movem"):
                    failure["register_mask"] = f"{int.from_bytes(program[pc + 2 : pc + 4], 'big'):04X}"
                else:
                    failure["count_source"] = detail.removeprefix("shift_")
                failures.append(failure)

    checks = {
        "all_register_pipeline_pcs_are_trace_pc_plus_2": all(
            ((int(item["state_pc"]) - int(item["pc"])) & 0xFFFFFF) == 2
            for item in records
        ),
        "movem_and_shift_records_checked": checked > 0,
        "movem_and_shift_cycle_rules_match_trace": mismatches == 0,
        "all_retained_variable_forms_observed": all(
            by_detail[key] > 0
            for key in ("movem_word", "movem_long", "shift_immediate", "shift_register")
        ),
    }
    report = {
        "scope": (
            "read-only original-MAME Stage-3 MOVEM and data-register shift/rotate "
            "timing proof; not a SNES repair, rate result, or playthrough claim"
        ),
        "inputs": {
            "summary": {"path": str(args.summary.resolve()), "sha256": sha256(args.summary)},
            "trace": {"path": str(trace.resolve()), "sha256": sha256(trace)},
            "m68kmake": {"path": str(args.m68kmake.resolve()), "sha256": sha256(args.m68kmake)},
            "m68k_list": {"path": str(args.m68k_list.resolve()), "sha256": sha256(args.m68k_list)},
            "m68kcpu": {"path": str(args.m68kcpu.resolve()), "sha256": sha256(args.m68kcpu)},
            "m68kops": {"path": str(args.m68kops.resolve()), "sha256": sha256(args.m68kops)},
            "program": {"path": str(args.program.resolve()), "sha256": sha256(args.program)},
        },
        "mame_cpu000_constants": constants,
        "accounting": {
            "register_trace_records": len(records),
            "interrupt_boundaries_skipped": skipped_interrupt,
            "non_program_pairs_skipped": skipped_non_program,
            "checked": checked,
            "mismatches": mismatches,
            "by_kind": dict(sorted(by_kind.items())),
            "by_detail": dict(sorted(by_detail.items())),
        },
        "checks": checks,
        "failures": failures,
        "result": "green" if all(checks.values()) else "red",
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({"result": report["result"], "output": str(args.output)}, sort_keys=True))
    return 0 if report["result"] == "green" else 1


if __name__ == "__main__":
    raise SystemExit(main())
