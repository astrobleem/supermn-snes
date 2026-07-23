#!/usr/bin/env python3
"""MAME/Nexen differential for guarded callable $00CB9E fast path.

MAME runs the original 68000 leaf through RTS.  Nexen enters the production
bank-$97 callable entry before its skipped BSR has been materialized.  The
comparison covers every emulated register, CCR X/N/Z/V/C, and mapped low-16K
work RAM apart from the deliberately different synthetic return longword.
This is bounded semantic/cycle evidence, not an FPS measurement.
"""

from __future__ import annotations

import argparse
import json
import random
import time
from pathlib import Path

import validate_d96_hle as base


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_ROM = ROOT / "build/interp.sfc"
ENTRY_PC = 0x00CB9E
ENTRY_NATIVE = 0x97E800
CALLER_SP = 0xF03D00
RETURN_PC = 0xF03E80
NATIVE_RETURN = 0x00D15A
A1_RECORD = 0xF02A00
A2_RECORD = 0xF02B00
A6_FRAME = 0xF03A00


def put16(work: bytearray, address: int, value: int) -> None:
    offset = address & 0xFFFF
    work[offset : offset + 2] = base.be16(value)


def put32(work: bytearray, address: int, value: int) -> None:
    offset = address & 0xFFFF
    work[offset : offset + 4] = base.be32(value)


def build_case(
    name: str,
    seed: int,
    *,
    status: int,
    source: int,
    mirrored: bool,
    a2_pointer: int = A2_RECORD,
    source_bytes: bytes | None = None,
) -> base.Case:
    rng = random.Random(seed)
    work = bytearray(rng.randrange(256) for _ in range(0x10000))
    regs = {reg: rng.randrange(1 << 32) for reg in base.REG_NAMES}
    regs.update(
        {
            "A0": source,
            "A1": A1_RECORD,
            "A5": 0x00F00000,
            "A6": A6_FRAME,
            # The native callable entry sees the pre-BSR stack value.
            "A7": CALLER_SP,
        }
    )
    sr = 0x2700 | rng.randrange(0x20)

    put16(work, A1_RECORD, status)
    put16(work, A6_FRAME - 0x22, 0x0014)
    work[(A6_FRAME - 0x24) & 0xFFFF] = 0x80 if mirrored else 0x00
    put16(work, A6_FRAME - 0x1E, 0x0124)
    put32(work, A6_FRAME - 0x54, a2_pointer)
    put16(work, A2_RECORD + 0, 0xAAAA)
    put16(work, A2_RECORD + 2, 0xBBBB)
    put16(work, A2_RECORD + 4, 0xCCCC)

    if source_bytes is not None:
        offset = source & 0xFFFF
        work[offset : offset + len(source_bytes)] = source_bytes

    # MAME begins at SP=CALLER_SP-4.  The native bridge begins at CALLER_SP
    # and materializes its own $00FF sentinel at the same location.
    put32(work, CALLER_SP - 4, RETURN_PC)
    work[RETURN_PC & 0xFFFF : (RETURN_PC & 0xFFFF) + 2] = bytes.fromhex("60fe")
    return base.Case(name, regs, sr, bytes(work))


def make_cases() -> list[base.Case]:
    return [
        build_case(
            "early-zero-preserves-registers",
            0xCB9E00,
            status=0,
            source=0x00032FCA,
            mirrored=False,
        ),
        build_case(
            "early-negative-preserves-registers",
            0xCB9E01,
            status=0x8000,
            source=0x00032FBA,
            mirrored=True,
        ),
        build_case(
            "rom-32fca-normal",
            0xCB9E02,
            status=1,
            source=0x00032FCA,
            mirrored=False,
        ),
        build_case(
            "rom-32fba-mirrored",
            0xCB9E03,
            status=2,
            source=0x00032FBA,
            mirrored=True,
        ),
        build_case(
            "rom-32f8a-normal",
            0xCB9E04,
            status=0x7FFF,
            source=0x00032F8A,
            mirrored=False,
        ),
        build_case(
            "work-source-interpreted-fallback",
            0xCB9E05,
            status=3,
            source=0x00F02C00,
            mirrored=True,
            source_bytes=bytes.fromhex(
                "00010002fffc000300040005112200330000"
            ),
        ),
        build_case(
            "nonwork-a2-early-interpreted-fallback",
            0xCB9E06,
            status=0,
            source=0x00032FCA,
            mirrored=False,
            a2_pointer=0x00F10000,
        ),
    ]


def mame_result(session: base.MameSession, case: base.Case) -> base.Result:
    session.pause()
    session.write_block(0xF00000, case.work)
    for name in base.REG_NAMES[:-1]:
        session.set_reg(name, case.regs[name])
    entry_sp = case.regs["A7"] - 4
    session.set_reg("SP", entry_sp)
    session.set_reg("USP", entry_sp)
    session.set_reg("SR", case.sr)
    session.set_reg("PC", ENTRY_PC)
    captured = session.cmd(
        "capture_at_pc",
        pc=RETURN_PC,
        addr=0xF00000,
        len=0x4000,
        nth=1,
        exp_sp=case.regs["A7"],
        maxFrames=30,
        timeout=30,
    )
    if not captured.get("registers"):
        raise RuntimeError(f"MAME did not return for {case.name}: {captured!r}")
    regs = captured["registers"]
    result_regs = {
        name: regs[name] & 0xFFFFFFFF for name in base.REG_NAMES[:-1]
    }
    result_regs["A7"] = regs["SP"] & 0xFFFFFFFF
    return base.Result(
        result_regs,
        regs["SR"] & 0xFFFF,
        bytes.fromhex(captured["hex"]),
    )


def nexen_result(
    m: base.McpSession, nat: Path, case: base.Case
) -> base.Result:
    m.load_state(str(nat))
    m.pause()
    reg_blob = b"".join(base.le32(case.regs[f"D{i}"]) for i in range(8))
    reg_blob += b"".join(base.le32(case.regs[f"A{i}"]) for i in range(8))
    m.write_memory(base.DP_SPACE, 0x00, reg_blob.hex())
    for offset in range(0, 0x10000, 0x4000):
        m.write_memory(
            base.SNES_SPACE,
            0x400000 + offset,
            case.work[offset : offset + 0x4000].hex(),
        )

    flags = case.sr & base.CCR_MASK
    base.write_u16(m, 0x6E, flags & 1)
    base.write_u16(m, 0x72, (flags >> 1) & 1)
    base.write_u16(m, 0x60, (flags >> 2) & 1)
    base.write_u16(m, 0x70, (flags >> 3) & 1)
    base.write_u16(m, 0xA2, (flags >> 4) & 1)
    base.write_u16(m, 0x40, NATIVE_RETURN & 0xFFFF)
    base.write_u16(m, 0x42, 0x00FF)
    base.write_u16(m, 0x7C, 7)
    base.write_u16(m, 0xA4, case.regs["A7"] & 0xFFFF)
    base.write_u16(m, 0xA6, (case.regs["A7"] >> 16) & 0xFFFF)
    base.write_u16(m, 0xA8, 1)
    base.write_u16(m, 0xAA, 0)
    base.write_u16(m, 0x4A, 0)
    base.write_u16(m, 0x4C, 0)
    base.write_u16(m, 0xAC, 0x7000)
    base.write_u16(m, 0x0718, 0xFFF8)
    base.write_u16(m, 0x071A, 1)
    base.write_u16(m, 0x0702, 0)
    base.write_u16(m, 0x0704, 1)

    hook = m.add_exec_hook(NATIVE_RETURN, cpu_type="Sa1")
    m.drain_notifications(timeout=0.05)
    base.set_sa1_pc(m, ENTRY_NATIVE)
    start_cycles = int(m.get_cpu_state("Sa1")["cycleCount"])
    hit = m.run_until(max_frames=120, hook_handle=hook)
    if (hit or {}).get("reason") != "hookFired":
        raise RuntimeError(f"Nexen did not return for {case.name}: {hit!r}")
    m.pause()
    m.remove_hook(hook)
    end_cycles = int(m.get_cpu_state("Sa1")["cycleCount"])

    raw_regs = bytes(m.read_memory(base.DP_SPACE, 0x00, 0x40))
    result_regs = {
        name: int.from_bytes(raw_regs[index * 4 : index * 4 + 4], "little")
        for index, name in enumerate(base.REG_NAMES)
    }
    ccr = (
        (1 if m.read_u16(0x6E, base.DP_SPACE) else 0)
        | ((1 if m.read_u16(0x72, base.DP_SPACE) else 0) << 1)
        | ((1 if m.read_u16(0x60, base.DP_SPACE) else 0) << 2)
        | ((1 if m.read_u16(0x70, base.DP_SPACE) else 0) << 3)
        | ((1 if m.read_u16(0xA2, base.DP_SPACE) else 0) << 4)
    )
    return base.Result(
        result_regs,
        (case.sr & ~base.CCR_MASK) | ccr,
        bytes(m.read_memory(base.SNES_SPACE, 0x400000, 0x4000)),
        end_cycles - start_cycles,
    )


def compare(case: base.Case, arcade: base.Result, console: base.Result) -> dict:
    reg_mismatches = {
        name: {"mame": arcade.regs[name], "nexen": console.regs[name]}
        for name in base.REG_NAMES
        if arcade.regs[name] != console.regs[name]
    }
    return_offset = (case.regs["A7"] - 4) & 0xFFFF
    excluded = set(range(return_offset, return_offset + 4))
    offsets = [
        offset
        for offset, (left, right) in enumerate(zip(arcade.work, console.work))
        if offset not in excluded and left != right
    ]
    ccr_mismatch = (arcade.sr & base.CCR_MASK) != (
        console.sr & base.CCR_MASK
    )
    return {
        "case": case.name,
        "result": (
            "green"
            if not reg_mismatches and not ccr_mismatch and not offsets
            else "red"
        ),
        "reg_mismatches": reg_mismatches,
        "mame_ccr": arcade.sr & base.CCR_MASK,
        "nexen_ccr": console.sr & base.CCR_MASK,
        "work_mismatch_count": len(offsets),
        "work_mismatch_first": [f"F0{offset:04X}" for offset in offsets[:24]],
        "nexen_cycles": console.cycles,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--rom", type=Path, default=DEFAULT_ROM)
    parser.add_argument("--nexen", type=Path, default=base.DEFAULT_NEXEN)
    parser.add_argument("--nat", type=Path, default=base.DEFAULT_NAT)
    parser.add_argument("--port", type=int, default=7549)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    for path in (args.rom, args.nexen, args.nat):
        if not path.is_file():
            parser.error(f"missing required input: {path}")

    cases = make_cases()
    events: list[dict] = []
    provenance = {
        "event": "provenance",
        "scope": "function-local CB9E MAME/Nexen differential; not fps",
        "mame": "/snap/bin/mame 0.287",
        "nexen": str(args.nexen.resolve()),
        "nexen_sha256": base.sha256(args.nexen),
        "rom": str(args.rom.resolve()),
        "rom_sha256": base.sha256(args.rom),
        "nat": str(args.nat.resolve()),
        "nat_sha256": base.sha256(args.nat),
        "entry_native": f"{ENTRY_NATIVE:06X}",
        "cases": len(cases),
        "time": time.time(),
    }
    events.append(provenance)
    print(json.dumps(provenance, sort_keys=True), flush=True)

    arcade_results: dict[str, base.Result] = {}
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
            arcade_results[case.name] = mame_result(mame, case)
            print(json.dumps({"event": "mame_case", "case": case.name}), flush=True)
    finally:
        mame.stop()

    with base.McpSession(
        rom=str(args.rom),
        mesen=str(args.nexen),
        cwd=ROOT,
        port=args.port,
        boot_wait=8.0,
        socket_timeout=120.0,
        stderr_log=ROOT / "build/playability-20260719/cb9e-nexen.stderr.log",
    ) as nexen:
        for case in cases:
            console = nexen_result(nexen, args.nat, case)
            event = {
                "event": "case",
                **compare(case, arcade_results[case.name], console),
            }
            events.append(event)
            print(json.dumps(event, sort_keys=True), flush=True)

    green = sum(event.get("result") == "green" for event in events)
    summary = {
        "event": "summary",
        "green": green,
        "red": len(cases) - green,
        "total": len(cases),
        "result": "green" if green == len(cases) else "red",
        "time": time.time(),
    }
    events.append(summary)
    print(json.dumps(summary, sort_keys=True), flush=True)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(
            "".join(json.dumps(event, sort_keys=True) + "\n" for event in events)
        )
    return 0 if green == len(cases) else 1


if __name__ == "__main__":
    raise SystemExit(main())
