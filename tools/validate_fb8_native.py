#!/usr/bin/env python3
"""Function-local MAME/Nexen differential for the native $000FB8 fill.

The legacy jsr hook enters ``entry_fb8`` before the emulated JSR has pushed its
return address.  MAME instead starts at the architectural function entry with
that return already on the 68K stack.  This harness constructs both equivalent
states, runs through the real RTS, and compares every D/A register, CCR/mask,
and the complete mapped 16 KiB work-RAM window including LINK/MOVEM residue.

This is bounded function-semantic and local-cycle evidence, never FPS.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import random
import time
from pathlib import Path

import validate_175a0_native as shared
import validate_d96_hle as base


ROOT = Path(__file__).resolve().parents[1]
ENTRY_PC = 0x000FB8
ENTRY_NATIVE = 0x9286E7
RETURN_PC = 0xF03E80
ENTRY_SP = 0xF03D00          # architectural entry: [A7] is RETURN_PC
MAPPED_WORK_SIZE = 0x4000


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def make_case(
    name: str,
    seed: int,
    *,
    offset: int,
    count: int,
    a5: int = 0xF00000,
    ccr: int = 0,
) -> base.Case:
    rng = random.Random(seed)
    work = bytearray(rng.randrange(256) for _ in range(0x10000))
    regs = {register: rng.randrange(1 << 32) for register in base.REG_NAMES}
    regs["A5"] = a5
    regs["A6"] = 0xF02F40 | (seed & 0x3C)
    regs["A7"] = ENTRY_SP
    stack = ENTRY_SP & 0xFFFF
    work[stack : stack + 4] = base.be32(RETURN_PC)
    work[stack + 4 : stack + 6] = base.be16(offset)
    work[stack + 6 : stack + 8] = base.be16(count)
    work[RETURN_PC & 0xFFFF : (RETURN_PC & 0xFFFF) + 2] = bytes.fromhex("60fe")
    return base.Case(name, regs, 0x2700 | (ccr & base.CCR_MASK), bytes(work))


def make_cases() -> list[base.Case]:
    return [
        make_case("organic-offset-01b6-count-18-x0", 0xFB800, offset=0x01B6, count=0x12),
        make_case("organic-offset-03ac-count-18-x1", 0xFB801, offset=0x03AC, count=0x12, ccr=0x1F),
        make_case("organic-offset-01de-count-18", 0xFB802, offset=0x01DE, count=0x12, ccr=0x0A),
        make_case("organic-offset-03d4-count-18", 0xFB803, offset=0x03D4, count=0x12, ccr=0x15),
        make_case("single-word-count-0", 0xFB804, offset=0x0000, count=0, ccr=0x1F),
        make_case("two-words-count-1", 0xFB805, offset=0x0020, count=1, ccr=0x10),
        make_case("negative-offset-count-31", 0xFB806, offset=0xFFF0, count=0x1F, ccr=0x07),
        make_case(
            "nonzero-a5-low-count-255",
            0xFB807,
            offset=0x0100,
            count=0x00FF,
            a5=0xF00020,
            ccr=0x18,
        ),
    ]


def mame_result(session: base.MameSession, case: base.Case) -> base.Result:
    session.pause()
    session.write_block(0xF00000, case.work[:MAPPED_WORK_SIZE])
    for name in base.REG_NAMES[:-1]:
        session.set_reg(name, case.regs[name])
    session.set_reg("SP", case.regs["A7"])
    session.set_reg("USP", case.regs["A7"])
    session.set_reg("SR", case.sr)
    session.set_reg("PC", ENTRY_PC)
    captured = session.cmd(
        "capture_at_pc",
        pc=RETURN_PC,
        addr=0xF00000,
        len=MAPPED_WORK_SIZE,
        nth=1,
        exp_sp=(case.regs["A7"] + 4) & 0xFFFFFF,
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
    session: base.McpSession,
    nat: Path,
    case: base.Case,
) -> base.Result:
    session.load_state(str(nat))
    session.pause()

    # entry_fb8 is reached before the jsr hook's architectural return push.
    # MAME's case A7 already points at that return, so Nexen starts four bytes
    # higher and the native prologue recreates the identical stack word.
    regs = dict(case.regs)
    regs["A7"] = (regs["A7"] + 4) & 0xFFFFFFFF
    register_blob = b"".join(base.le32(regs[name]) for name in base.REG_NAMES)
    session.write_memory(base.DP_SPACE, 0x00, register_blob.hex())
    for offset in range(0, len(case.work), 0x4000):
        session.write_memory(
            base.SNES_SPACE,
            0x400000 + offset,
            case.work[offset : offset + 0x4000].hex(),
        )
    shared.park_snes_cpu(session)

    flags = case.sr & base.CCR_MASK
    shared.write_u16(session, 0x6E, flags & 1)
    shared.write_u16(session, 0x72, (flags >> 1) & 1)
    shared.write_u16(session, 0x60, (flags >> 2) & 1)
    shared.write_u16(session, 0x70, (flags >> 3) & 1)
    shared.write_u16(session, 0xA2, (flags >> 4) & 1)
    shared.write_u16(session, 0x7C, (case.sr >> 8) & 7)
    shared.write_u16(session, 0x40, RETURN_PC & 0xFFFF)
    shared.write_u16(session, 0x42, (RETURN_PC >> 16) & 0xFF)
    shared.write_u16(session, 0x4A, 0)
    shared.write_u16(session, 0x4C, 0)
    shared.write_u16(session, 0xA4, regs["A7"] & 0xFFFF)
    shared.write_u16(session, 0xA6, (regs["A7"] >> 16) & 0xFFFF)
    shared.write_u16(session, 0xA8, 1)
    shared.write_u16(session, 0xAA, 0)
    shared.write_u16(session, 0xAC, 0x7000)
    shared.write_u16(session, 0x0702, 0)
    shared.write_u16(session, 0x0704, 1)
    shared.write_u16(session, 0x0710, RETURN_PC & 0xFFFF)
    shared.write_u16(session, 0x0712, 0)
    shared.write_u16(session, 0x0714, 0)
    shared.write_u16(session, 0x0716, (RETURN_PC >> 16) & 0xFF)
    shared.write_u16(session, 0x0718, 0xFFF8)
    shared.write_u16(session, 0x071A, 1)
    shared.write_u16(session, 0x072E, 0)
    shared.write_u16(session, 0x0730, 0)
    shared.write_u16(session, 0x0734, 0)
    shared.write_u16(session, 0x0736, 0)
    shared.write_u16(session, 0x0738, 0)
    shared.write_u16(session, 0x073A, 0)
    shared.write_u16(session, 0x073C, 0)

    hook = session.add_exec_hook(shared.DEBUG_SPIN, cpu_type="Sa1")
    session.drain_notifications(timeout=0.05)
    base.set_sa1_pc(session, ENTRY_NATIVE)
    start_cycles = int(session.get_cpu_state("Sa1")["cycleCount"])
    hit = session.run_until(max_frames=30, hook_handle=hook)
    session.pause()
    session.remove_hook(hook)
    if (hit or {}).get("reason") != "hookFired":
        observed = shared.read_u16(session, 0x40) | (
            (shared.read_u16(session, 0x42) & 0xFF) << 16
        )
        raise RuntimeError(
            f"Nexen did not freeze at ${RETURN_PC:06X} for {case.name}: "
            f"{hit!r}; PC=${observed:06X}"
        )
    end_cycles = int(session.get_cpu_state("Sa1")["cycleCount"])
    observed = shared.read_u16(session, 0x40) | (
        (shared.read_u16(session, 0x42) & 0xFF) << 16
    )
    if not shared.read_u16(session, 0x0712) or observed != RETURN_PC:
        raise RuntimeError(
            f"Nexen froze at ${observed:06X}, expected ${RETURN_PC:06X}"
        )
    sr = 0x2000 | (
        (shared.read_u16(session, 0x7C) & 7) << 8
    ) | shared.captured_ccr(session)
    return base.Result(
        shared.captured_regs(session),
        sr,
        bytes(session.read_memory(base.SNES_SPACE, 0x400000, MAPPED_WORK_SIZE)),
        end_cycles - start_cycles,
    )


def compare(case: base.Case, arcade: base.Result, console: base.Result) -> dict:
    register_mismatches = {
        name: {"mame": arcade.regs[name], "nexen": console.regs[name]}
        for name in base.REG_NAMES
        if arcade.regs[name] != console.regs[name]
    }
    work_mismatches = [
        offset
        for offset, (left, right) in enumerate(zip(arcade.work, console.work))
        if left != right
    ]
    sr_mask = 0x071F
    sr_mismatch = (arcade.sr & sr_mask) != (console.sr & sr_mask)
    return {
        "event": "case",
        "case": case.name,
        "result": (
            "green"
            if not register_mismatches and not sr_mismatch and not work_mismatches
            else "red"
        ),
        "register_mismatches": register_mismatches,
        "mame_sr_mask_ccr": arcade.sr & sr_mask,
        "nexen_sr_mask_ccr": console.sr & sr_mask,
        "work_mismatch_count": len(work_mismatches),
        "work_mismatch_first": [
            f"F0{offset:04X}" for offset in work_mismatches[:24]
        ],
        "nexen_cycles": console.cycles,
    }


def emit(events: list[dict], event: dict) -> None:
    events.append(event)
    print(json.dumps(event, sort_keys=True), flush=True)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--rom", type=Path, default=base.DEFAULT_ROM)
    parser.add_argument("--nexen", type=Path, default=base.DEFAULT_NEXEN)
    parser.add_argument("--nat", type=Path, default=base.DEFAULT_NAT)
    parser.add_argument("--port", type=int, default=7662)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    for path in (args.rom, args.nexen, args.nat):
        if not path.is_file():
            parser.error(f"missing required input: {path}")
    if args.output.exists():
        parser.error(f"output already exists: {args.output}")
    args.output.parent.mkdir(parents=True, exist_ok=True)

    cases = make_cases()
    events: list[dict] = []
    emit(
        events,
        {
            "event": "provenance",
            "scope": (
                "function-local $0FB8 MAME/Nexen differential; all D/A "
                "registers, CCR/mask, mapped 16 KiB work RAM including "
                "LINK/MOVEM/RTS stack residue; not fps"
            ),
            "mame": "/snap/bin/mame 0.287",
            "nexen": str(args.nexen.resolve()),
            "nexen_sha256": sha256(args.nexen),
            "rom": str(args.rom.resolve()),
            "rom_sha256": sha256(args.rom),
            "nat": str(args.nat.resolve()),
            "nat_sha256": sha256(args.nat),
            "entry_pc": f"{ENTRY_PC:06X}",
            "entry_native": f"{ENTRY_NATIVE:06X}",
            "return_pc": f"{RETURN_PC:06X}",
            "cases": len(cases),
            "time": time.time(),
        },
    )

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
            emit(events, {"event": "mame_case", "case": case.name})
    finally:
        mame.stop()

    stderr_log = args.output.with_suffix(".nexen.stderr.log")
    with base.McpSession(
        rom=str(args.rom.resolve()),
        mesen=str(args.nexen.resolve()),
        cwd=ROOT,
        port=args.port,
        boot_wait=8.0,
        socket_timeout=180.0,
        stderr_log=stderr_log,
    ) as nexen:
        for case in cases:
            emit(events, compare(case, arcade[case.name], nexen_result(nexen, args.nat, case)))

    case_events = [event for event in events if event.get("event") == "case"]
    green = sum(event["result"] == "green" for event in case_events)
    summary = {
        "event": "summary",
        "green": green,
        "red": len(case_events) - green,
        "total": len(case_events),
        "result": "green" if green == len(case_events) else "red",
        "time": time.time(),
    }
    emit(events, summary)
    args.output.write_text(
        "".join(json.dumps(event, sort_keys=True) + "\n" for event in events),
        encoding="utf-8",
    )
    return 0 if summary["result"] == "green" else 1


if __name__ == "__main__":
    raise SystemExit(main())
