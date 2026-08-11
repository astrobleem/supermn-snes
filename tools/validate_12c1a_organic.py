#!/usr/bin/env python3
"""Exact organic three-way differential for the $012C1A action selector.

The input is the retained MAME tick-8446 function-entry capture that exposed
the bug: D2 starts at $00000100, MOVE.B loads A4+$06=$73 while preserving the
upper byte, and CMP.B must select D7=$000120A8.  The identical architectural
entry state is executed through original MAME code, the complete SNES
interpreter, and the production bank-$97 native body.

All D/A registers, CCR/X, interrupt mask, mapped 16-KiB work RAM, and the live
plus popped return stack are compared at the caller's $011768 return seam.
Prepared native-off/native-on save states are retained before execution.
This is a focused state-injected differential, not fresh-boot evidence.
"""

from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

import validate_12e56_native as harness


wall = harness.wall
base = harness.base
ROOT = harness.ROOT
ENTRY_PC = 0x012C1A
ENTRY_NATIVE = 0x97B000
RETURN_PC = 0x011768
INEXT = harness.INEXT
OP_ILLEGAL = harness.OP_ILLEGAL
MAPPED_WORK_SIZE = harness.MAPPED_WORK_SIZE
FULL_WORK_SIZE = harness.FULL_WORK_SIZE
DEFAULT_ROM = ROOT / "build/interp.sfc"
DEFAULT_FIXTURE = (
    ROOT
    / "build/playtest-investigation-20260725"
    / "tick08446-mame-12c1a-entry-0287-v1"
)


def configure_harness() -> None:
    """Point the shared exact-function runner at this native body."""
    harness.ENTRY_PC = ENTRY_PC
    harness.ENTRY_NATIVE = ENTRY_NATIVE
    harness.RETURN_PC = RETURN_PC
    harness.INEXT = INEXT
    harness.OP_ILLEGAL = OP_ILLEGAL
    harness.MAPPED_WORK_SIZE = MAPPED_WORK_SIZE
    harness.FULL_WORK_SIZE = FULL_WORK_SIZE


def load_case(directory: Path) -> wall.Case:
    log_path = directory / "capture.jsonl"
    rows = [
        json.loads(line)
        for line in log_path.read_text(encoding="utf-8").splitlines()
    ]
    matches = [
        row
        for row in rows
        if row.get("event") == "generic_pc"
        and int(row.get("offset", -1)) == ENTRY_PC
        and int(row.get("tick", -1)) == 8446
        and int(row.get("ordinal", -1)) == 1
    ]
    if len(matches) != 1:
        raise RuntimeError(
            f"expected one retained tick-8446 $012C1A entry, got {len(matches)}"
        )
    row = matches[0]
    work_path = directory / f"{row['name']}.work.bin"
    work = work_path.read_bytes()
    if len(work) != FULL_WORK_SIZE:
        raise RuntimeError(f"{work_path}: expected {FULL_WORK_SIZE} bytes")
    regs = {
        name: int(row[name]) & 0xFFFFFFFF
        for name in base.REG_NAMES
    }
    entry_sp = regs["A7"] & 0xFFFFFF
    if (entry_sp >> 16) != 0xF0:
        raise RuntimeError(f"entry stack is outside work RAM: ${entry_sp:06X}")
    stacked_return = int.from_bytes(
        work[entry_sp & 0xFFFF : (entry_sp & 0xFFFF) + 4],
        "big",
    )
    if stacked_return != RETURN_PC:
        raise RuntimeError(
            f"retained stack has ${stacked_return:06X}, "
            f"expected return ${RETURN_PC:06X}"
        )
    a4 = regs["A4"] & 0xFFFF
    required = {
        "D2": regs["D2"] == 0x00000100,
        "D7": regs["D7"] == 0,
        "A4+$06": work[(a4 + 6) & 0xFFFF] == 0x73,
    }
    failed = [name for name, valid in required.items() if not valid]
    if failed:
        raise RuntimeError(
            "retained organic byte-compare edge changed: " + ", ".join(failed)
        )
    return wall.Case(
        "organic-tick-08446-d2-0173-cmp-byte",
        regs,
        int(row["SR"]) & 0xFFFF,
        work,
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--rom", type=Path, default=DEFAULT_ROM)
    parser.add_argument("--fixture", type=Path, default=DEFAULT_FIXTURE)
    parser.add_argument("--nexen", type=Path, default=base.DEFAULT_NEXEN)
    parser.add_argument("--nat", type=Path, default=base.DEFAULT_NAT)
    parser.add_argument("--port", type=int, default=9281)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    required = (
        args.rom,
        args.fixture / "capture.jsonl",
        args.nexen,
        args.nat,
    )
    for path in required:
        if not path.is_file():
            parser.error(f"missing required input: {path}")
    if args.output.exists():
        parser.error(f"output already exists: {args.output}")
    args.output.parent.mkdir(parents=True, exist_ok=True)

    configure_harness()
    case = load_case(args.fixture)
    # The on-disk capture uses a descriptive MAME-generated name rather than
    # the regression case name, so record it from the retained row directly.
    fixture_work = next(args.fixture.glob("mame-generic-pc-*.work.bin"))
    events: list[dict] = [
        {
            "event": "provenance",
            "scope": (
                "retained organic-entry $012C1A MAME/interpreter/native "
                "differential; all D/A registers, CCR/X/mask, live and "
                "popped stack, mapped 16 KiB work RAM; not fresh boot or fps"
            ),
            "rom": str(args.rom.resolve()),
            "rom_sha256": wall.sha256(args.rom),
            "fixture": str(args.fixture.resolve()),
            "capture_log_sha256": wall.sha256(args.fixture / "capture.jsonl"),
            "fixture_work": str(fixture_work.resolve()),
            "fixture_work_sha256": wall.sha256(fixture_work),
            "nexen": str(args.nexen.resolve()),
            "nexen_sha256": wall.sha256(args.nexen),
            "nat": str(args.nat.resolve()),
            "nat_sha256": wall.sha256(args.nat),
            "entry_pc": f"{ENTRY_PC:06X}",
            "entry_native": f"{ENTRY_NATIVE:06X}",
            "return_pc": f"{RETURN_PC:06X}",
            "input_edge": {
                "D2_before_move_b": f"{case.regs['D2']:08X}",
                "A4_plus_06": f"{case.work[((case.regs['A4'] & 0xFFFF) + 6) & 0xFFFF]:02X}",
                "effective_D2_word_after_move_b": "00000173",
            },
            "time": time.time(),
        }
    ]

    mame = base.MameSession(
        mame="/snap/bin/mame",
        system="superman",
        rompath=str(base.MAME_TRACE / "roms"),
        workdir=str(base.MAME_TRACE),
        state_directory=str(base.MAME_TRACE / "sta"),
        extra_args=["-video", "none", "-sound", "none", "-nothrottle"],
    )
    try:
        mame.launch(boot_wait=25)
        oracle = harness.mame_result(mame, case)
    finally:
        mame.stop()

    semantic = {
        "oracle_D7": f"{oracle.regs['D7']:08X}",
        "oracle_A4_plus_06": (
            f"{oracle.work[((case.regs['A4'] & 0xFFFF) + 6) & 0xFFFF]:02X}"
        ),
        "oracle_A6_minus_66": (
            f"{int.from_bytes(oracle.work[((case.regs['A6'] - 0x66) & 0xFFFF):((case.regs['A6'] - 0x66) & 0xFFFF) + 2], 'big'):04X}"
        ),
    }
    if semantic != {
        "oracle_D7": "000120A8",
        "oracle_A4_plus_06": "00",
        "oracle_A6_minus_66": "0003",
    }:
        raise RuntimeError(f"MAME organic selector result changed: {semantic}")
    events.append({"event": "oracle_semantics", **semantic})

    with base.McpSession(
        rom=str(args.rom.resolve()),
        mesen=str(args.nexen.resolve()),
        cwd=ROOT,
        port=args.port,
        boot_wait=8.0,
        socket_timeout=180.0,
        stderr_log=args.output.parent / "12c1a-organic.nexen.stderr.log",
    ) as nexen:
        for native in (False, True):
            configuration = "native-on" if native else "native-off"
            result, state = harness.nexen_result(
                nexen,
                args.nat,
                case,
                native=native,
                pre_state=(
                    args.output.parent
                    / "states"
                    / configuration
                    / f"{case.name}.mss"
                ),
            )
            event = wall.compare(case, oracle, result, configuration)
            event["pre_state"] = state
            events.append(event)
            print(json.dumps(event, sort_keys=True), flush=True)

    results = [event for event in events if event.get("event") == "case"]
    green = sum(event["result"] == "green" for event in results)
    summary = {
        "event": "summary",
        "green": green,
        "red": len(results) - green,
        "total": len(results),
        "result": "green" if green == len(results) else "red",
        "time": time.time(),
    }
    events.append(summary)
    args.output.write_text(
        "".join(
            json.dumps(event, sort_keys=True) + "\n"
            for event in events
        ),
        encoding="utf-8",
    )
    print(json.dumps(summary, sort_keys=True), flush=True)
    return 0 if summary["result"] == "green" else 1


if __name__ == "__main__":
    raise SystemExit(main())
