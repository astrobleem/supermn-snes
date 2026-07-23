#!/usr/bin/env python3
"""MAME/Nexen differential for the guarded $00CD1A/$000FB8 fusion.

MAME begins at the architectural $00CD1A entry with its caller return already
on the 68000 stack.  Nexen begins at ``hcd1a_fb8`` with the same state, exactly
as the native $00CE58 bridge enters it after pushing its bank-$FE continuation.
The comparison covers every D/A register, CCR/mask, and the complete mapped
16 KiB work-RAM window including the final nested JSR/LINK/MOVEM residue.

Canonical-work-RAM/$0FB8 cases exercise every fused skip decision.  A shifted
A5 and a RAM-resident alternate callback exercise restart-exact interpreter
fallback.  This is bounded semantic/local-cycle evidence, never an end-to-end
FPS result.
"""

from __future__ import annotations

import argparse
import json
import random
import time
from pathlib import Path

import validate_175a0_native as shared
import validate_d96_hle as base
import validate_fb8_native as fb8


ROOT = Path(__file__).resolve().parents[1]
ENTRY_PC = 0x00CD1A
ENTRY_NATIVE = 0x9DE000
FB8_PC = 0x000FB8
RAM_RTS_PC = 0xF03E40
RETURN_PC = 0xF03E80
ENTRY_SP = 0xF03D00
MAPPED_WORK_SIZE = 0x4000


def make_case(
    name: str,
    seed: int,
    *,
    flags_word: int,
    a5: int = 0xF00000,
    callback: int = FB8_PC,
    ccr: int = 0,
) -> base.Case:
    rng = random.Random(seed)
    work = bytearray(rng.randrange(256) for _ in range(0x10000))
    regs = {register: rng.randrange(1 << 32) for register in base.REG_NAMES}
    regs["A5"] = a5
    regs["A6"] = 0xF02F40 | (seed & 0x3C)
    regs["A7"] = ENTRY_SP

    a5_low = a5 & 0xFFFF
    pointer = (a5_low + 0x1C9A) & 0xFFFF
    flags = (a5_low + 0x2A48) & 0xFFFF
    work[pointer : pointer + 4] = base.be32(callback)
    work[flags : flags + 2] = base.be16(flags_word)
    stack = ENTRY_SP & 0xFFFF
    work[stack : stack + 4] = base.be32(RETURN_PC)
    work[RETURN_PC & 0xFFFF : (RETURN_PC & 0xFFFF) + 2] = bytes.fromhex("60fe")
    if callback == RAM_RTS_PC:
        work[RAM_RTS_PC & 0xFFFF : (RAM_RTS_PC & 0xFFFF) + 2] = bytes.fromhex(
            "4e75"
        )
    return base.Case(name, regs, 0x2700 | (ccr & base.CCR_MASK), bytes(work))


def make_cases() -> list[base.Case]:
    return [
        make_case("hot-zero-x0", 0xCD1A00, flags_word=0x0000, ccr=0x00),
        make_case("hot-zero-x1-all-entry-flags", 0xCD1A01, flags_word=0x0000, ccr=0x1F),
        make_case("hot-zero-random-registers", 0xCD1A02, flags_word=0x0000, ccr=0x12),
        make_case("hot-skip-first", 0xCD1A03, flags_word=0x0001, ccr=0x0B),
        make_case("hot-skip-second", 0xCD1A04, flags_word=0x0002, ccr=0x14),
        make_case("hot-skip-third", 0xCD1A05, flags_word=0x0004, ccr=0x07),
        make_case("hot-skip-fourth", 0xCD1A06, flags_word=0x0008, ccr=0x1A),
        make_case("hot-skip-all", 0xCD1A07, flags_word=0x000F, ccr=0x1F),
        # CD1A reads only the low flag byte, so this still performs all four
        # fills while proving that the stricter whole-word guard restarts it.
        make_case("hot-upper-byte-only", 0xCD1A08, flags_word=0x8000, ccr=0x10),
        make_case(
            "fallback-shifted-a5",
            0xCD1A09,
            flags_word=0x0000,
            a5=0xF00020,
            ccr=0x05,
        ),
        # A tiny RTS in work RAM gives the pointer guard a safe non-$0FB8
        # target and also exercises the interpreter's RAM-resident-PC path.
        make_case(
            "fallback-ram-rts-callback",
            0xCD1A0A,
            flags_word=0x0000,
            callback=RAM_RTS_PC,
            ccr=0x19,
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
    return base.Result(result_regs, regs["SR"] & 0xFFFF, bytes.fromhex(captured["hex"]))


def nexen_result(
    session: base.McpSession,
    nat: Path,
    case: base.Case,
) -> base.Result:
    session.load_state(str(nat))
    session.pause()

    register_blob = b"".join(base.le32(case.regs[name]) for name in base.REG_NAMES)
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
    shared.write_u16(session, 0x40, ENTRY_PC & 0xFFFF)
    shared.write_u16(session, 0x42, (ENTRY_PC >> 16) & 0xFF)
    shared.write_u16(session, 0x4A, 0)
    shared.write_u16(session, 0x4C, 0)
    shared.write_u16(session, 0xA4, case.regs["A7"] & 0xFFFF)
    shared.write_u16(session, 0xA6, (case.regs["A7"] >> 16) & 0xFFFF)
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
    sr = 0x2000 | ((shared.read_u16(session, 0x7C) & 7) << 8) | shared.captured_ccr(
        session
    )
    return base.Result(
        shared.captured_regs(session),
        sr,
        bytes(session.read_memory(base.SNES_SPACE, 0x400000, MAPPED_WORK_SIZE)),
        end_cycles - start_cycles,
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--rom", type=Path, default=base.DEFAULT_ROM)
    parser.add_argument("--nexen", type=Path, default=base.DEFAULT_NEXEN)
    parser.add_argument("--nat", type=Path, default=base.DEFAULT_NAT)
    parser.add_argument("--port", type=int, default=7663)
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
    fb8.emit(
        events,
        {
            "event": "provenance",
            "scope": (
                "bounded $00CD1A/$000FB8 MAME/Nexen differential; all D/A "
                "registers, CCR/mask, mapped 16 KiB work RAM including nested "
                "stack residue; hot and restart-exact fallback cases; not fps"
            ),
            "mame": "/snap/bin/mame 0.287",
            "nexen": str(args.nexen.resolve()),
            "nexen_sha256": fb8.sha256(args.nexen),
            "rom": str(args.rom.resolve()),
            "rom_sha256": fb8.sha256(args.rom),
            "nat": str(args.nat.resolve()),
            "nat_sha256": fb8.sha256(args.nat),
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
            fb8.emit(events, {"event": "mame_case", "case": case.name})
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
            fb8.emit(
                events,
                fb8.compare(
                    case,
                    arcade[case.name],
                    nexen_result(nexen, args.nat, case),
                ),
            )

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
    fb8.emit(events, summary)
    args.output.write_text(
        "".join(json.dumps(event, sort_keys=True) + "\n" for event in events),
        encoding="utf-8",
    )
    return 0 if summary["result"] == "green" else 1


if __name__ == "__main__":
    raise SystemExit(main())
