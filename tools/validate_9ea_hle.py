#!/usr/bin/env python3
"""Function-local MAME/Nexen differential for the $0009EA transition loop.

MAME executes the original 68000 subroutine through RTS.  Nexen enters the
production bank-$99 callable escape before its skipped JSR return has been
materialized, matching the jsr.l hook contract.  The comparison covers all
D/A registers, CCR X/N/Z/V/C, and mapped low-16K work RAM apart from the
synthetic return word.  Cases exercise zero, saturated, mixed, and component
boundary values across all 496 transformed words.

This is bounded semantic/cycle evidence, not an end-to-end performance claim.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import random
import time
from pathlib import Path

import validate_d96_hle as base


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_ROM = ROOT / "build" / "interp.sfc"
ENTRY_PC = 0x0009EA
ENTRY_NATIVE = 0x99C500
CALLER_SP = 0xF03D04
RETURN_PC = 0xF03E80
NATIVE_RETURN = 0x00D15A
TABLE_START = 0x1732
TABLE_WORDS = 0x1F0
DIRTY_LONG = 0x1B12
SNES_PARK_PC = 0x7EF800


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def put32(work: bytearray, offset: int, value: int) -> None:
    work[offset : offset + 4] = base.be32(value)


def build_case(
    name: str,
    seed: int,
    words: list[int],
    *,
    dirty: int,
    x_flag: int,
) -> base.Case:
    if len(words) != TABLE_WORDS:
        raise ValueError(f"{name}: expected {TABLE_WORDS} words, got {len(words)}")
    rng = random.Random(seed)
    work = bytearray(rng.randrange(256) for _ in range(0x4000))
    regs = {reg: rng.randrange(1 << 32) for reg in base.REG_NAMES}
    regs["A5"] = 0x00F00000
    regs["A7"] = CALLER_SP
    sr = 0x2700 | rng.randrange(0x10) | ((x_flag & 1) << 4)

    work[TABLE_START:DIRTY_LONG] = b"".join(base.be16(word) for word in words)
    put32(work, DIRTY_LONG, dirty)
    put32(work, (CALLER_SP - 4) & 0xFFFF, RETURN_PC)
    work[RETURN_PC & 0xFFFF : (RETURN_PC & 0xFFFF) + 2] = bytes.fromhex("60fe")
    return base.Case(name, regs, sr, bytes(work))


def make_cases() -> list[base.Case]:
    mixed_rng = random.Random(0x09EA02)
    boundaries = [
        0x0000,
        0x0001,
        0x0002,
        0x001E,
        0x0020,
        0x0040,
        0x03C0,
        0x0400,
        0x0800,
        0x7800,
        0x8000,
        0xFFFF,
    ]
    return [
        build_case(
            "all-zero-dirty-even-x0",
            0x09EA00,
            [0] * TABLE_WORDS,
            dirty=0x00000000,
            x_flag=0,
        ),
        build_case(
            "all-zero-dirty-odd-x1",
            0x09EA04,
            [0] * TABLE_WORDS,
            dirty=0x00000001,
            x_flag=1,
        ),
        build_case(
            "noncomponent-bits-only-x1",
            0x09EA05,
            [0x8001 if index & 1 else 0x0401 for index in range(TABLE_WORDS)],
            dirty=0x01020304,
            x_flag=1,
        ),
        build_case(
            "all-components-saturated-dirty-odd-x1",
            0x09EA01,
            [0x7BDE] * TABLE_WORDS,
            dirty=0x00000001,
            x_flag=1,
        ),
        build_case(
            "mixed-full-range",
            0x09EA02,
            [mixed_rng.randrange(0x10000) for _ in range(TABLE_WORDS)],
            dirty=0x8000A5A4,
            x_flag=1,
        ),
        build_case(
            "component-boundaries",
            0x09EA03,
            [boundaries[index % len(boundaries)] for index in range(TABLE_WORDS)],
            dirty=0x40005A5B,
            x_flag=0,
        ),
        build_case(
            "active-prefix-final-zero-x1",
            0x09EA06,
            [0x7BDE] * (TABLE_WORDS - 1) + [0],
            dirty=0x89ABCDEF,
            x_flag=1,
        ),
        build_case(
            "active-prefix-final-noncomponent-x1",
            0x09EA07,
            [0x7BDE] * (TABLE_WORDS - 1) + [0x8001],
            dirty=0x76543210,
            x_flag=1,
        ),
    ]


def mame_result(session: base.MameSession, case: base.Case) -> base.Result:
    session.pause()
    session.write_block(0xF00000, case.work)
    for name in base.REG_NAMES[:-1]:
        session.set_reg(name, case.regs[name])
    entry_sp = (case.regs["A7"] - 4) & 0xFFFFFFFF
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
        exp_sp=case.regs["A7"] & 0xFFFFFF,
        maxFrames=30,
        timeout=30,
    )
    if not captured.get("registers"):
        raise RuntimeError(f"MAME did not return for {case.name}: {captured!r}")
    regs = captured["registers"]
    result_regs = {name: regs[name] & 0xFFFFFFFF for name in base.REG_NAMES[:-1]}
    result_regs["A7"] = regs["SP"] & 0xFFFFFFFF
    return base.Result(
        result_regs,
        regs["SR"] & 0xFFFF,
        bytes.fromhex(captured["hex"]),
    )


def park_snes_cpu(session: base.McpSession) -> None:
    """Keep the unrelated 5A22 from executing randomized synthetic BW-RAM.

    The legacy native checkpoint has the 5A22 parked in a BW-RAM execution
    context.  Replacing the complete low-16K test window with randomized case
    data therefore turns that CPU loose on random opcodes during longer native
    cases.  Park it in a private WRAM BRA loop, disable NMI, and mask IRQ for
    this function-local lab.  The production cold-boot validation does not use
    this intervention.
    """

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


def nexen_result(
    session: base.McpSession,
    nat: Path,
    case: base.Case,
) -> base.Result:
    session.load_state(str(nat))
    session.pause()
    reg_blob = b"".join(base.le32(case.regs[f"D{i}"]) for i in range(8))
    reg_blob += b"".join(base.le32(case.regs[f"A{i}"]) for i in range(8))
    session.write_memory(base.DP_SPACE, 0x00, reg_blob.hex())
    session.write_memory(base.SNES_SPACE, 0x400000, case.work.hex())

    flags = case.sr & base.CCR_MASK
    base.write_u16(session, 0x6E, flags & 1)
    base.write_u16(session, 0x72, (flags >> 1) & 1)
    base.write_u16(session, 0x60, (flags >> 2) & 1)
    base.write_u16(session, 0x70, (flags >> 3) & 1)
    base.write_u16(session, 0xA2, (flags >> 4) & 1)
    base.write_u16(session, 0x40, NATIVE_RETURN & 0xFFFF)
    base.write_u16(session, 0x42, 0x00FF)
    base.write_u16(session, 0x7C, 7)
    base.write_u16(session, 0xA4, case.regs["A7"] & 0xFFFF)
    base.write_u16(session, 0xA6, (case.regs["A7"] >> 16) & 0xFFFF)
    base.write_u16(session, 0xA8, 1)
    base.write_u16(session, 0xAA, 0)
    base.write_u16(session, 0x4A, 0)
    base.write_u16(session, 0x4C, 0)
    base.write_u16(session, 0xAC, 0x7000)
    base.write_u16(session, 0x0718, 0xFFF8)
    base.write_u16(session, 0x071A, 1)
    base.write_u16(session, 0x0702, 0)
    base.write_u16(session, 0x0704, 1)
    park_snes_cpu(session)

    hook = session.add_exec_hook(NATIVE_RETURN, cpu_type="Sa1")
    session.drain_notifications(timeout=0.05)
    base.set_sa1_pc(session, ENTRY_NATIVE)
    start_cycles = int(session.get_cpu_state("Sa1")["cycleCount"])
    hit = session.run_until(max_frames=120, hook_handle=hook)
    if (hit or {}).get("reason") != "hookFired":
        raise RuntimeError(f"Nexen did not return for {case.name}: {hit!r}")
    session.pause()
    session.remove_hook(hook)
    end_cycles = int(session.get_cpu_state("Sa1")["cycleCount"])

    raw_regs = bytes(session.read_memory(base.DP_SPACE, 0x00, 0x40))
    result_regs = {
        name: int.from_bytes(raw_regs[index * 4 : index * 4 + 4], "little")
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
        result_regs,
        (case.sr & ~base.CCR_MASK) | ccr,
        bytes(session.read_memory(base.SNES_SPACE, 0x400000, 0x4000)),
        end_cycles - start_cycles,
    )


def compare(case: base.Case, arcade: base.Result, console: base.Result) -> dict:
    reg_mismatches = {
        name: {"mame": arcade.regs[name], "nexen": console.regs[name]}
        for name in base.REG_NAMES
        if arcade.regs[name] != console.regs[name]
    }
    return_slot = (case.regs["A7"] - 4) & 0xFFFF
    excluded = set(range(return_slot, return_slot + 4))
    offsets = [
        offset
        for offset, (left, right) in enumerate(zip(arcade.work, console.work))
        if offset not in excluded and left != right
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
        "nexen_cycles": console.cycles,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--rom", type=Path, default=DEFAULT_ROM)
    parser.add_argument("--nexen", type=Path, default=base.DEFAULT_NEXEN)
    parser.add_argument("--nat", type=Path, default=base.DEFAULT_NAT)
    parser.add_argument("--port", type=int, default=7650)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    for path in (args.rom, args.nexen, args.nat):
        if not path.is_file():
            parser.error(f"missing required input: {path}")

    cases = make_cases()
    events: list[dict] = []
    provenance = {
        "event": "provenance",
        "scope": "function-local 9EA MAME/Nexen differential; not fps",
        "mame": "/snap/bin/mame 0.287",
        "nexen": str(args.nexen.resolve()),
        "nexen_sha256": sha256(args.nexen),
        "rom": str(args.rom.resolve()),
        "rom_sha256": sha256(args.rom),
        "nat": str(args.nat.resolve()),
        "nat_sha256": sha256(args.nat),
        "entry_native": f"{ENTRY_NATIVE:06X}",
        "snes_isolation": {
            "pc": f"{SNES_PARK_PC:06X}",
            "code": "bra -2",
            "nmi_disabled": True,
            "irq_masked": True,
            "reason": "legacy native checkpoint executes from randomized BW-RAM",
        },
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

    stderr_log = (
        ROOT / "build" / "playability-20260720" / "9ea-differential-nexen.stderr.log"
    )
    stderr_log.parent.mkdir(parents=True, exist_ok=True)
    with base.McpSession(
        rom=str(args.rom),
        mesen=str(args.nexen),
        cwd=ROOT,
        port=args.port,
        boot_wait=8.0,
        socket_timeout=120.0,
        stderr_log=stderr_log,
    ) as nexen:
        for case in cases:
            console = nexen_result(nexen, args.nat, case)
            event = {"event": "case", **compare(case, arcade_results[case.name], console)}
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
