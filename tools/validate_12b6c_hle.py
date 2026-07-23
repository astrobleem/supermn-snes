#!/usr/bin/env python3
"""MAME/Nexen differential for the hot $012B6C -> $12B84 -> $0CE4 tree.

The arcade oracle enters the original $012B6C with its real $01177C BSR
return on the stack.  Nexen enters hle_12b6c using the production hook
contract (that push was consumed, A7 is the caller value, and $40/$42 hold
$01177C).  A validation-only runtime xlat poke routes the final $01177C
dispatch to the inert bank-$00 spin loop, so state is sampled before the real
native caller continuation can mutate it.
All D/A registers, CCR X/N/Z/V/C, and the full low-16-KiB work window are
compared.  This is bounded semantic/cycle evidence, not FPS.
"""

from __future__ import annotations

import argparse
import json
import random
import time
from pathlib import Path

import validate_d96_hle as base

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_ROM = ROOT / "build" / "interp.sfc"
ENTRY_PC = 0x012B6C
ENTRY_NATIVE = 0x94E000
RETURN_PC = 0x01177C
RETURN_NATIVE = 0x00D15A
RETURN_XLAT_FILE_OFFSET = 0x2B3D74
CALLER_SP = 0xF03D00
A4_RECORD = 0xF02C00
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
    frame_table: int,
    cursor: int,
    record_x: int,
    record_y: int,
    attr_select: int,
    x_flag: int,
) -> base.Case:
    rng = random.Random(seed)
    work = bytearray(rng.randrange(256) for _ in range(0x10000))
    regs = {reg: rng.randrange(1 << 32) for reg in base.REG_NAMES}
    regs.update(
        {
            "A3": frame_table,
            "A4": A4_RECORD,
            "A5": 0x00F00000,
            "A6": A6_FRAME,
            # Production HLE entry sees the pre-BSR caller stack value.
            "A7": CALLER_SP,
        }
    )
    sr = 0x2700 | rng.randrange(0x10) | ((x_flag & 1) << 4)

    # Global renderer slots used by the original and HLE trees.
    put32(work, 0xF01C8A, 0x00000CE4)
    put32(work, 0xF01C8E, 0x00000D96)

    # Select the $12B84 path with no blink-counter fallback.
    put16(work, A6_FRAME - 0x72, 0)
    put16(work, A6_FRAME - 0x18, 0)
    put16(work, A6_FRAME - 0x50, attr_select)
    put16(work, A6_FRAME - 0x68, 0)
    put16(work, A6_FRAME - 0x58, cursor)

    work[A4_RECORD & 0xFFFF] = 0                 # bit 7 clear -> CE4
    put16(work, A4_RECORD + 2, record_x)
    put16(work, A4_RECORD + 4, record_y)

    # The real BSR return is part of the expected final stack residue.  MAME
    # begins at SP=CALLER_SP-4; the native hook begins at SP=CALLER_SP and
    # hle_12b6c materializes this word itself.
    put32(work, CALLER_SP - 4, RETURN_PC)
    return base.Case(name, regs, sr, bytes(work))


def make_cases() -> list[base.Case]:
    return [
        # ROM $3478A contains longword $0000084A; frame header 0,3.
        build_case(
            "rom-frame-084a-visible",
            0x12B600,
            frame_table=0x0003478A,
            cursor=0x0000,
            record_x=0x0080,
            record_y=0x0060,
            attr_select=0,
            x_flag=0,
        ),
        # ROM $481A -> $00004E36; frame header 0,7.  Negative cursor and Y
        # clipping exercise signed output placement and final X replacement.
        build_case(
            "rom-frame-4e36-negative-cursor-offscreen",
            0x12B601,
            frame_table=0x0000481A,
            cursor=0xFFF0,
            record_x=0x0020,
            record_y=0x01B0,
            attr_select=1,
            x_flag=1,
        ),
        # ROM $70F4 -> $00005BB0; frame header 1,4 (two columns).
        build_case(
            "rom-frame-5bb0-two-columns",
            0x12B602,
            frame_table=0x000070F4,
            cursor=0x0010,
            record_x=0x00F5,
            record_y=0x0010,
            attr_select=0,
            x_flag=1,
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
    result_regs = {name: regs[name] & 0xFFFFFFFF for name in base.REG_NAMES[:-1]}
    result_regs["A7"] = regs["SP"] & 0xFFFFFFFF
    return base.Result(result_regs, regs["SR"] & 0xFFFF, bytes.fromhex(captured["hex"]))


def nexen_result(m: base.McpSession, nat: Path, case: base.Case) -> base.Result:
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
    base.write_u16(m, 0x40, RETURN_PC & 0xFFFF)
    base.write_u16(m, 0x42, (RETURN_PC >> 16) & 0xFFFF)
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

    # xlat[$01177C] normally enters the active bank-$99 caller continuation.
    # Redirect only this loaded emulator instance to the inert $00:D15A loop
    # so run_until cannot race past the comparison point.
    m.write_memory("snesPrgRom", RETURN_XLAT_FILE_OFFSET, "5ad100")

    hook = m.add_exec_hook(RETURN_NATIVE, cpu_type="Sa1")
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
    offsets = [
        offset
        for offset, (left, right) in enumerate(zip(arcade.work, console.work))
        if left != right
    ]
    ccr_mismatch = (arcade.sr & base.CCR_MASK) != (console.sr & base.CCR_MASK)
    return {
        "case": case.name,
        "result": "green" if not reg_mismatches and not ccr_mismatch and not offsets else "red",
        "reg_mismatches": reg_mismatches,
        "mame_ccr": arcade.sr & base.CCR_MASK,
        "nexen_ccr": console.sr & base.CCR_MASK,
        "work_mismatch_count": len(offsets),
        "work_mismatch_first": [f"F0{offset:04X}" for offset in offsets[:24]],
        "work_mismatch_values": [
            {
                "address": f"F0{offset:04X}",
                "mame": arcade.work[offset],
                "nexen": console.work[offset],
            }
            for offset in offsets[:24]
        ],
        "nexen_cycles": console.cycles,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--rom", type=Path, default=DEFAULT_ROM)
    parser.add_argument("--nexen", type=Path, default=base.DEFAULT_NEXEN)
    parser.add_argument("--nat", type=Path, default=base.DEFAULT_NAT)
    parser.add_argument("--port", type=int, default=7548)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    for path in (args.rom, args.nexen, args.nat):
        if not path.is_file():
            parser.error(f"missing required input: {path}")

    cases = make_cases()
    events: list[dict] = []
    provenance = {
        "event": "provenance",
        "scope": "function-local 12B6C->12B84->CE4 MAME/Nexen differential; not fps",
        "mame": "/snap/bin/mame 0.287",
        "nexen": str(args.nexen.resolve()),
        "nexen_sha256": base.sha256(args.nexen),
        "rom": str(args.rom.resolve()),
        "rom_sha256": base.sha256(args.rom),
        "nat": str(args.nat.resolve()),
        "nat_sha256": base.sha256(args.nat),
        "entry_native": f"{ENTRY_NATIVE:06X}",
        "return_native": f"{RETURN_NATIVE:06X}",
        "runtime_xlat_redirect": {
            "file_offset": f"{RETURN_XLAT_FILE_OFFSET:06X}",
            "target": f"{RETURN_NATIVE:06X}",
        },
        "cases": len(cases),
        "time": time.time(),
    }
    events.append(provenance)
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

    with base.McpSession(
        rom=str(args.rom),
        mesen=str(args.nexen),
        cwd=ROOT,
        port=args.port,
        boot_wait=8.0,
        socket_timeout=120.0,
        stderr_log=ROOT / "build" / "playability-20260719" / "12b6c-nexen.stderr.log",
    ) as nexen:
        for case in cases:
            console = nexen_result(nexen, args.nat, case)
            event = {"event": "case", **compare(case, arcade[case.name], console)}
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
