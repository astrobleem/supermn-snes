#!/usr/bin/env python3
"""Whole-function MAME/Nexen differential for the guarded $00C8E0 HLE.

The cases use the organic round-start target pair ($001008/$0013BE) and low
task stacks.  MAME executes the original 68000 function through RTS; Nexen
enters the production table wrapper with the same real return already on the
emulated stack.  Every D/A register, XNZVC bit, and byte of mapped low-16K
work RAM is compared, including LINK/MOVEM/callee residue below A7.

This is bounded function evidence, not an end-to-end performance claim.
"""

from __future__ import annotations

import argparse
import json
import random
import time
from pathlib import Path

import validate_render_helpers as base


ROOT = Path(__file__).resolve().parents[1]
ENTRY_PC = 0x00C8E0
RETURN_PC = 0x00D15A
ENTRY_NATIVE = 0x958000
FAST_NATIVE = 0x95A745
FALLBACK_NATIVE = 0x958004
SNES_PARK_PC = 0x7EF800


def put16(data: bytearray, offset: int, value: int) -> None:
    data[offset:offset + 2] = (value & 0xFFFF).to_bytes(2, "big")


def put32(data: bytearray, offset: int, value: int) -> None:
    data[offset:offset + 4] = base.be32(value)


def build_case(
    name: str,
    seed: int,
    *,
    stack: int,
    argument: int,
    source_zero: int,
    source_one: int,
) -> base.Case:
    rng = random.Random(seed)
    work = bytearray(rng.randrange(256) for _ in range(0x4000))
    work.extend([0xFF] * 0xC000)
    regs = {reg: rng.randrange(1 << 32) for reg in base.REG_NAMES}
    regs["A5"] = 0x00F00000
    regs["A7"] = 0x00F00000 | stack
    sr = 0x2700 | rng.randrange(0x20)

    put32(work, 0x1C9E, 0x00001008)
    put32(work, 0x1CAE, 0x000013BE)
    put32(work, 0x1CEA, source_zero)
    put32(work, 0x1CEE, source_one)
    put32(work, stack, RETURN_PC)
    put16(work, stack + 4, argument)
    return base.Case(name, ENTRY_PC, regs, sr, bytes(work), [])


def make_cases() -> list[base.Case]:
    return [
        build_case(
            "arg0-zero-production-stack-a",
            0xC8E000,
            stack=0x1200,
            argument=0,
            source_zero=0,
            source_one=54321,
        ),
        build_case(
            "arg0-99999-production-stack-b",
            0xC8E001,
            stack=0x1000,
            argument=0,
            source_zero=99999,
            source_one=12345,
        ),
        build_case(
            "arg0-clamp-100000",
            0xC8E002,
            stack=0x0E00,
            argument=0,
            source_zero=100000,
            source_one=1,
        ),
        build_case(
            "arg1-midrange-production-stack",
            0xC8E003,
            stack=0x0D80,
            argument=1,
            source_zero=777,
            source_one=54321,
        ),
        build_case(
            "arg-nonzero-max-five-digit",
            0xC8E004,
            stack=0x1180,
            argument=0xFFFF,
            source_zero=42,
            source_one=99999,
        ),
    ]


def make_fallback_probe() -> base.Case:
    # The high stack is outside the production-low, field-disjoint contract.
    return build_case(
        "fallback-high-stack-probe",
        0xC8E0FF,
        stack=0x3D00,
        argument=0,
        source_zero=12345,
        source_one=67890,
    )


def mame_result(session: base.MameSession, case: base.Case) -> base.Result:
    session.pause()
    session.write_block(0xF00000, case.work[:0x4000])
    for name in base.REG_NAMES[:-1]:
        session.set_reg(name, case.regs[name])
    session.set_reg("SP", case.regs["A7"])
    session.set_reg("USP", case.regs["A7"])
    session.set_reg("SR", case.sr)
    session.set_reg("PC", ENTRY_PC)
    capture = session.cmd(
        "capture_at_pc",
        pc=RETURN_PC,
        addr=0xF00000,
        len=0x4000,
        nth=1,
        exp_sp=(case.regs["A7"] + 4) & 0xFFFFFF,
        maxFrames=30,
        timeout=30,
    )
    if not capture.get("registers"):
        raise RuntimeError(f"MAME did not return for {case.name}: {capture!r}")
    raw = capture["registers"]
    regs = {name: raw[name] & 0xFFFFFFFF for name in base.REG_NAMES[:-1]}
    regs["A7"] = raw["SP"] & 0xFFFFFFFF
    return base.Result(
        regs,
        raw["SR"] & 0xFFFF,
        bytes.fromhex(capture["hex"]),
        [],
        [],
    )


def write_u16(
    session: base.McpSession,
    address: int,
    value: int,
    space: str = base.DP_SPACE,
) -> None:
    session.write_u16(address, value & 0xFFFF, space)


def park_snes_cpu(session: base.McpSession) -> None:
    session.write_memory("snesWorkRam", SNES_PARK_PC & 0x1FFFF, "80fe")
    session.write_memory("snesMemory", 0x4200, "00")
    session.read_memory("snesMemory", 0x4210, 1)
    state = dict(session.get_cpu_state("Snes"))
    state.update(
        {
            "pc": SNES_PARK_PC & 0xFFFF,
            "k": (SNES_PARK_PC >> 16) & 0xFF,
            "d": 0,
            "dbr": 0,
            "ps": int(state.get("ps", 0)) | 0x04,
            "emulationMode": False,
        }
    )
    allowed = (
        "cpuType", "pc", "k", "a", "x", "y", "sp", "d", "dbr", "ps",
        "emulationMode",
    )
    session.tool(
        "set_cpu_state", {key: state[key] for key in allowed if key in state}
    )


def prepare_nexen_case(
    session: base.McpSession, nat: Path, case: base.Case
) -> None:
    session.load_state(str(nat))
    session.pause()
    registers = b"".join(base.le32(case.regs[f"D{i}"]) for i in range(8))
    registers += b"".join(base.le32(case.regs[f"A{i}"]) for i in range(8))
    session.write_memory(base.DP_SPACE, 0x00, registers.hex())
    session.write_memory(base.SNES_SPACE, 0x400000, case.work[:0x4000].hex())

    flags = case.sr & base.CCR_MASK
    write_u16(session, 0x6E, flags & 1)
    write_u16(session, 0x72, (flags >> 1) & 1)
    write_u16(session, 0x60, (flags >> 2) & 1)
    write_u16(session, 0x70, (flags >> 3) & 1)
    write_u16(session, 0xA2, (flags >> 4) & 1)
    write_u16(session, 0x7C, 7)
    # Native spans may cross an SA-1 IRQ even though the synthetic entry masks
    # new delivery.  Seed the interpreter's saved emulated-stack pair so any
    # already-pending context round-trip restores this case's A7, not whatever
    # scratch happened to be present in the checkpoint.
    write_u16(session, 0xA4, case.regs["A7"] & 0xFFFF)
    write_u16(session, 0xA6, (case.regs["A7"] >> 16) & 0xFFFF)
    write_u16(session, 0xA8, 1)
    write_u16(session, 0xAA, 0)
    write_u16(session, 0x4A, 0)
    write_u16(session, 0x4C, 0)
    write_u16(session, 0xAC, 0x7000)
    write_u16(session, 0x0718, 0xFFF8)
    write_u16(session, 0x071A, 1)
    write_u16(session, 0x0712, 0)
    write_u16(session, 0x0714, 0)
    write_u16(session, 0x0702, 0)
    write_u16(session, 0x0704, 1)
    write_u16(session, 0x0734, 1)
    park_snes_cpu(session)


def read_result(
    session: base.McpSession, case: base.Case, cycles: int
) -> base.Result:
    raw_regs = bytes(session.read_memory(base.DP_SPACE, 0x00, 0x40))
    regs = {
        name: int.from_bytes(raw_regs[index * 4:index * 4 + 4], "little")
        for index, name in enumerate(base.REG_NAMES)
    }
    ccr = (
        (1 if session.read_u16(0x6E, base.DP_SPACE) else 0)
        | ((1 if session.read_u16(0x72, base.DP_SPACE) else 0) << 1)
        | ((1 if session.read_u16(0x60, base.DP_SPACE) else 0) << 2)
        | ((1 if session.read_u16(0x70, base.DP_SPACE) else 0) << 3)
        | ((1 if session.read_u16(0xA2, base.DP_SPACE) else 0) << 4)
    )
    return base.Result(
        regs,
        (case.sr & ~base.CCR_MASK) | ccr,
        bytes(session.read_memory(base.SNES_SPACE, 0x400000, 0x4000)),
        [],
        [],
        cycles,
    )


def nexen_result(
    session: base.McpSession, nat: Path, case: base.Case, return_hook: int
) -> base.Result:
    prepare_nexen_case(session, nat, case)
    base._set_sa1_pc(session, ENTRY_NATIVE)
    start = int(session.get_cpu_state("Sa1")["cycleCount"])
    hit = session.run_until(max_frames=120, hook_handle=return_hook)
    session.pause()
    if (hit or {}).get("reason") != "hookFired":
        raise RuntimeError(f"Nexen did not return for {case.name}: {hit!r}")
    end = int(session.get_cpu_state("Sa1")["cycleCount"])
    return read_result(session, case, end - start)


def path_probe(
    session: base.McpSession,
    nat: Path,
    case: base.Case,
    *,
    expected_fast: bool,
) -> dict[str, int]:
    prepare_nexen_case(session, nat, case)
    target = FAST_NATIVE if expected_fast else FALLBACK_NATIVE
    hook = session.add_exec_hook(target, cpu_type="Sa1")
    session.drain_notifications(timeout=0.05)
    try:
        base._set_sa1_pc(session, ENTRY_NATIVE)
        hit = session.run_until(max_frames=120, hook_handle=hook)
        session.pause()
        if (hit or {}).get("reason") != "hookFired":
            raise RuntimeError(
                f"Nexen did not take ${target:06X} for {case.name}: {hit!r}"
            )
    finally:
        session.remove_hook(hook)
        session.drain_notifications(timeout=0.05)
    return {
        "fast": 1 if expected_fast else 0,
        "fallback": 0 if expected_fast else 1,
    }


def compare(case: base.Case, arcade: base.Result, console: base.Result) -> dict:
    reg_mismatches = {
        name: {"mame": arcade.regs[name], "nexen": console.regs[name]}
        for name in base.REG_NAMES
        if arcade.regs[name] != console.regs[name]
    }
    ccr_mismatch = (arcade.sr & base.CCR_MASK) != (console.sr & base.CCR_MASK)
    offsets = [
        offset
        for offset, (left, right) in enumerate(zip(arcade.work, console.work))
        if left != right
    ]
    return {
        "case": case.name,
        "result": "green"
        if not reg_mismatches and not ccr_mismatch and not offsets
        else "red",
        "reg_mismatches": reg_mismatches,
        "mame_ccr": arcade.sr & base.CCR_MASK,
        "nexen_ccr": console.sr & base.CCR_MASK,
        "work_mismatch_count": len(offsets),
        "work_mismatch_first": [
            {
                "address": f"F0{offset:04X}",
                "mame": arcade.work[offset],
                "nexen": console.work[offset],
            }
            for offset in offsets[:32]
        ],
        "sa1_cycles_native_wrapper_to_return": console.cycles,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--rom", type=Path, default=base.DEFAULT_ROM)
    parser.add_argument("--nexen", type=Path, default=base.DEFAULT_NEXEN)
    parser.add_argument("--nat", type=Path, default=base.DEFAULT_NAT)
    parser.add_argument("--port", type=int, default=7682)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    for path in (args.rom, args.nexen, args.nat):
        if not path.exists():
            parser.error(f"missing required input: {path}")

    cases = make_cases()
    provenance = {
        "event": "provenance",
        "scope": "whole-function $C8E0 MAME/Nexen differential; not fps",
        "mame": "/snap/bin/mame 0.287",
        "nexen": str(args.nexen.resolve()),
        "nexen_sha256": base.sha256(args.nexen),
        "rom": str(args.rom.resolve()),
        "rom_sha256": base.sha256(args.rom),
        "nat": str(args.nat.resolve()),
        "nat_sha256": base.sha256(args.nat),
        "native_wrapper": f"{ENTRY_NATIVE:06X}",
        "native_fast": f"{FAST_NATIVE:06X}",
        "native_fallback": f"{FALLBACK_NATIVE:06X}",
        "cases": len(cases),
        "time": time.time(),
    }
    events = [provenance]
    print(json.dumps(provenance, sort_keys=True), flush=True)

    arcade: dict[str, base.Result] = {}
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
        for case in cases:
            arcade[case.name] = mame_result(mame, case)
            print(json.dumps({"event": "mame_case", "case": case.name}), flush=True)
    finally:
        mame.stop()

    stderr_path = (
        args.output.with_suffix(".nexen.stderr.log")
        if args.output
        else ROOT / "build/c8e0-differential.nexen.stderr.log"
    )
    console: dict[str, base.Result] = {}
    with base.McpSession(
        rom=str(args.rom),
        mesen=str(args.nexen),
        cwd=str(ROOT),
        port=args.port,
        boot_wait=8.0,
        socket_timeout=120.0,
        stderr_log=stderr_path,
    ) as nexen:
        return_hook = nexen.add_exec_hook(RETURN_PC, cpu_type="Sa1")
        for case in cases:
            console[case.name] = nexen_result(nexen, args.nat, case, return_hook)

    path_path = (
        args.output.parent / f"{args.output.stem}.path.nexen.stderr.log"
        if args.output
        else ROOT / "build/c8e0-differential-path.nexen.stderr.log"
    )
    traces: dict[str, dict[str, int]] = {}
    fallback = make_fallback_probe()
    with base.McpSession(
        rom=str(args.rom),
        mesen=str(args.nexen),
        cwd=str(ROOT),
        port=args.port + 1,
        boot_wait=8.0,
        socket_timeout=120.0,
        stderr_log=path_path,
    ) as nexen:
        for case in cases:
            traces[case.name] = path_probe(
                nexen, args.nat, case, expected_fast=True
            )
        fallback_trace = path_probe(
            nexen, args.nat, fallback, expected_fast=False
        )

    for case in cases:
        event = {
            "event": "case",
            **compare(case, arcade[case.name], console[case.name]),
            "trace_counts": traces[case.name],
            "trace_expected": {"fast": 1, "fallback": 0},
        }
        if event["trace_counts"] != event["trace_expected"]:
            event["result"] = "red"
        events.append(event)
        print(json.dumps(event, sort_keys=True), flush=True)

    fallback_event = {
        "event": "path_case",
        "case": fallback.name,
        "scope": "guard rejection at generated-body seam; no semantic completion",
        "trace_counts": fallback_trace,
        "trace_expected": {"fast": 0, "fallback": 1},
        "result": "green"
        if fallback_trace == {"fast": 0, "fallback": 1}
        else "red",
    }
    events.append(fallback_event)
    print(json.dumps(fallback_event, sort_keys=True), flush=True)

    green = sum(
        event.get("result") == "green"
        for event in events
        if event.get("event") == "case"
    )
    summary = {
        "event": "summary",
        "green": green,
        "red": len(cases) - green,
        "total": len(cases),
        "result": "green"
        if green == len(cases) and fallback_event["result"] == "green"
        else "red",
        "time": time.time(),
    }
    events.append(summary)
    print(json.dumps(summary, sort_keys=True), flush=True)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(
            "".join(json.dumps(event, sort_keys=True) + "\n" for event in events)
        )
    return 0 if summary["result"] == "green" else 1


if __name__ == "__main__":
    raise SystemExit(main())
