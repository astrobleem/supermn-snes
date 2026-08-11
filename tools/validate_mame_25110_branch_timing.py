#!/usr/bin/env python3
"""Prove the branch/DBcc timing outcomes in the retained MAME Stage-3 trace.

This is a read-only oracle reducer.  It consumes the register-qualified trace
produced by ``capture_mame_25110_irq_phase.py`` and evaluates each conditional
branch from the actual pre-instruction SR/Dn state.  It proves the concrete
timing rules needed at the Stage-3 virtual-IRQ seam without conflating MAME's
debugger pipeline PC with the instruction-hook PC.

It neither starts an emulator nor writes a ROM, save state, or private arcade
input.  The MAME source paths are development-only inputs that authenticate the
CPU-000 constants used to make the rule prediction; the executable trace stays
the timing oracle.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from collections import Counter
from pathlib import Path
from typing import Any

import audit_m68k_cycle_model as static_audit


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_PROGRAM = ROOT / "data" / "superman_m68k.bin"
STATE_TRACE_LINE = re.compile(
    r"^M68K_STATE "
    r"(?P<cycle>[0-9A-F]+) (?P<state_pc>[0-9A-F]+)"
    r"(?P<values>(?: [0-9A-F]+){17})"
    r" \| (?P<trace_pc>[0-9A-F]{6}): (?P<disassembly>.+)$"
)
INTERRUPT = re.compile(r"^\s*\(interrupted at [0-9A-F]{6}, IRQ 6\)$")


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
    parser.add_argument("--program", type=Path, default=DEFAULT_PROGRAM)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    for label, path in (
        ("capture summary", args.summary),
        ("MAME m68kmake.py", args.m68kmake),
        ("MAME m68k_in.lst", args.m68k_list),
        ("MAME m68kcpu.cpp", args.m68kcpu),
        ("program image", args.program),
    ):
        if not path.is_file():
            parser.error(f"missing {label}: {path}")
    if args.output.exists():
        parser.error(f"output already exists: {args.output}")
    return args


def signed8(value: int) -> int:
    return value - 0x100 if value & 0x80 else value


def signed16(value: int) -> int:
    return value - 0x10000 if value & 0x8000 else value


def condition(code: int, sr: int) -> bool:
    n = bool(sr & 0x0008)
    z = bool(sr & 0x0004)
    v = bool(sr & 0x0002)
    c = bool(sr & 0x0001)
    return (
        True,
        False,
        not c and not z,
        c or z,
        not c,
        c,
        not z,
        z,
        not v,
        v,
        not n,
        n,
        n == v,
        n != v,
        not z and n == v,
        z or n != v,
    )[code]


def parse_trace(path: Path) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    interrupt_before = False
    for line_number, raw in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        match = STATE_TRACE_LINE.match(raw)
        if match:
            values = [int(value, 16) for value in match.group("values").split()]
            if len(values) != 17:
                raise RuntimeError(f"bad register count at trace line {line_number}")
            records.append(
                {
                    "cycle": int(match.group("cycle"), 16),
                    "state_pc": int(match.group("state_pc"), 16),
                    "pc": int(match.group("trace_pc"), 16),
                    "d": values[:8],
                    "sr": values[16] & 0xFFFF,
                    "disassembly": match.group("disassembly"),
                    "interrupt_before": interrupt_before,
                    "line": line_number,
                }
            )
            interrupt_before = False
        elif INTERRUPT.match(raw):
            interrupt_before = True
    if len(records) < 2:
        raise RuntimeError("trace is not register-qualified or has too few instructions")
    return records


def main() -> int:
    args = parse_args()
    summary = json.loads(args.summary.read_text(encoding="utf-8"))
    if summary.get("mame", {}).get("version") != "0.287 (mame0287)":
        raise RuntimeError("capture is not the exact MAME 0.287 oracle")
    trace = resolve(args.summary, summary["capture"]["debugger_trace"])
    cpu_source = args.m68kcpu.read_text(encoding="utf-8", errors="replace")
    required_constants = {
        "m_cyc_bcc_notake_b = -2;": -2,
        "m_cyc_bcc_notake_w = 2;": 2,
        "m_cyc_dbcc_f_noexp = -2;": -2,
        "m_cyc_dbcc_f_exp   = 2;": 2,
    }
    if any(text not in cpu_source for text in required_constants):
        raise RuntimeError("MAME CPU-000 branch/DBcc timing constants changed")
    program = args.program.read_bytes()
    if len(program) != 0x80000:
        raise RuntimeError("expected 512 KiB MC68000 program image")
    static = static_audit.build_static_cycles(
        static_audit.load_m68kmake(args.m68kmake), args.m68k_list
    )
    records = parse_trace(trace)

    checked = 0
    skipped_interrupt = 0
    skipped_non_program = 0
    mismatches = 0
    by_kind: Counter[str] = Counter()
    by_outcome: Counter[str] = Counter()
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
        next_pc = int(following["pc"])
        observed = int(following["cycle"]) - int(current["cycle"])
        prediction: int | None = None
        outcome = ""
        kind = ""
        if 0x6200 <= opcode <= 0x6FFF:
            code = (opcode >> 8) & 0x0F
            displacement8 = opcode & 0xFF
            if code in (0, 1):  # BRA/BSR: fixed timing, not conditional Bcc.
                continue
            if displacement8:
                fallthrough = (pc + 2) & 0xFFFFFF
                target = (pc + 2 + signed8(displacement8)) & 0xFFFFFF
                taken = condition(code, int(current["sr"]))
                prediction = 10 if taken else 8
                kind = "bcc_short"
            else:
                extension = int.from_bytes(program[pc + 2 : pc + 4], "big")
                fallthrough = (pc + 4) & 0xFFFFFF
                target = (pc + 2 + signed16(extension)) & 0xFFFFFF
                taken = condition(code, int(current["sr"]))
                prediction = 10 if taken else 12
                kind = "bcc_word"
            expected_next = target if taken else fallthrough
            outcome = "taken" if taken else "not_taken"
            if next_pc != expected_next:
                prediction = None
                outcome = "unresolved_control_flow"
        elif (opcode & 0xF0F8) == 0x50C8:
            code = (opcode >> 8) & 0x0F
            register = opcode & 7
            extension = int.from_bytes(program[pc + 2 : pc + 4], "big")
            fallthrough = (pc + 4) & 0xFFFFFF
            target = (pc + 2 + signed16(extension)) & 0xFFFFFF
            condition_true = condition(code, int(current["sr"]))
            if condition_true:
                prediction = 12
                expected_next = fallthrough
                outcome = "condition_true_exit"
            else:
                decremented = (int(current["d"][register]) - 1) & 0xFFFF
                if decremented == 0xFFFF:
                    prediction = 14
                    expected_next = fallthrough
                    outcome = "expired_exit"
                else:
                    prediction = 10
                    expected_next = target
                    outcome = "decrement_branch"
            kind = "dbcc"
            if next_pc != expected_next:
                prediction = None
                outcome = "unresolved_control_flow"
        else:
            continue

        if prediction is None:
            continue
        checked += 1
        by_kind[kind] += 1
        by_outcome[f"{kind}:{outcome}"] += 1
        if observed != prediction:
            mismatches += 1
            if len(failures) < 32:
                failures.append(
                    {
                        "pc": f"{pc:06X}",
                        "opcode": f"{opcode:04X}",
                        "disassembly": current["disassembly"],
                        "sr": f"{int(current['sr']):04X}",
                        "next_pc": f"{next_pc:06X}",
                        "outcome": outcome,
                        "predicted_cycles": prediction,
                        "observed_cycles": observed,
                        "static_cycles": static[opcode],
                    }
                )

    checks = {
        "all_register_pipeline_pcs_are_trace_pc_plus_2": all(
            ((int(item["state_pc"]) - int(item["pc"])) & 0xFFFFFF) == 2
            for item in records
        ),
        "branch_or_dbcc_records_checked": checked > 0,
        "branch_and_dbcc_cycle_rules_match_trace": mismatches == 0,
        "all_retained_dynamic_outcomes_observed": all(
            by_outcome[key] > 0
            for key in (
                "bcc_short:taken",
                "bcc_short:not_taken",
                "bcc_word:taken",
                "bcc_word:not_taken",
                "dbcc:expired_exit",
                "dbcc:decrement_branch",
            )
        ),
    }
    report = {
        "scope": (
            "read-only original-MAME Stage-3 conditional branch/DBcc timing proof; "
            "not a SNES repair, rate result, or playthrough claim"
        ),
        "inputs": {
            "summary": {"path": str(args.summary.resolve()), "sha256": sha256(args.summary)},
            "trace": {"path": str(trace.resolve()), "sha256": sha256(trace)},
            "m68kmake": {"path": str(args.m68kmake.resolve()), "sha256": sha256(args.m68kmake)},
            "m68k_list": {"path": str(args.m68k_list.resolve()), "sha256": sha256(args.m68k_list)},
            "m68kcpu": {"path": str(args.m68kcpu.resolve()), "sha256": sha256(args.m68kcpu)},
            "program": {"path": str(args.program.resolve()), "sha256": sha256(args.program)},
        },
        "mame_cpu000_constants": required_constants,
        "accounting": {
            "register_trace_records": len(records),
            "interrupt_boundaries_skipped": skipped_interrupt,
            "non_program_pairs_skipped": skipped_non_program,
            "checked": checked,
            "mismatches": mismatches,
            "by_kind": dict(sorted(by_kind.items())),
            "by_outcome": dict(sorted(by_outcome.items())),
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
