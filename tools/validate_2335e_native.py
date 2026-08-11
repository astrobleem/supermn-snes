#!/usr/bin/env python3
"""Three-way differential for the organic $02335E collision producer call.

The retained MAME program-fetch fixture is the first Stage-1 call at movie
tick 3276.  Its real BSR return is already present on the MC68000 stack.
MAME and the SNES interpreter start at that architectural entry.  The native
arm starts four bytes above it because the direct escape's prologue recreates
the skipped call return from the emulated PC.

All D/A registers, CCR/X, interrupt mask, and mapped 16 KiB work RAM are
compared at the original $023358 return.  This is focused injected-state
evidence, not a fresh-boot or performance claim.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import validate_13be_native as shared


base = shared.base
live = shared.live
ROOT = shared.ROOT
EVIDENCE = shared.EVIDENCE
DEFAULT_FIXTURE = EVIDENCE / "failure-3662-mame-entry2335e-tick3277-v1"
DEFAULT_ROM = ROOT / "build" / "interp.sfc"
DEFAULT_NAT = Path("/tmp/b0_native.mss")
ENTRY_PC = 0x02335E
ENTRY_NATIVE = 0x988400
INEXT = shared.INEXT
OP_ILLEGAL = shared.OP_ILLEGAL
MAPPED_WORK_SIZE = shared.MAPPED_WORK_SIZE
FULL_WORK_SIZE = shared.FULL_WORK_SIZE
CASE_SCOPE = (
    "organic Stage-1 $02335E collision-producer MAME/interpreter/native "
    "differential; focused injected state, not fresh boot or fps"
)


@dataclass
class Case:
    name: str
    regs: dict[str, int]
    sr: int
    work: bytes
    tick: int
    frame: int
    ordinal: int
    return_pc: int
    source_row: dict[str, Any]

    @property
    def entry_sp(self) -> int:
        return self.regs["A7"]


def load_case(directory: Path, ordinal: int) -> Case:
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
        and int(row.get("ordinal", -1)) == ordinal
    ]
    if len(matches) != 1:
        raise RuntimeError(
            f"expected one $02335E ordinal-{ordinal} capture, got "
            f"{len(matches)}"
        )
    row = matches[0]
    work_path = directory / f"{row['name']}.work.bin"
    work = work_path.read_bytes()
    if len(work) != FULL_WORK_SIZE:
        raise RuntimeError(f"{work_path}: expected 65536 bytes")
    regs = {
        name: int(row[name]) & 0xFFFFFFFF
        for name in base.REG_NAMES
    }
    entry_sp = regs["A7"] & 0xFFFF
    return_pc = int.from_bytes(work[entry_sp : entry_sp + 4], "big")
    return_pc &= 0xFFFFFF
    if return_pc != 0x023358:
        raise RuntimeError(
            f"unexpected organic return ${return_pc:06X}, wanted $023358"
        )
    return Case(
        name=f"mame-tick-{int(row['tick']):05d}-call-{ordinal}",
        regs=regs,
        sr=int(row["SR"]) & 0xFFFF,
        work=work,
        tick=int(row["tick"]),
        frame=int(row["frame"]),
        ordinal=ordinal,
        return_pc=return_pc,
        source_row=row,
    )


def mame_result(session: base.MameSession, case: Case) -> base.Result:
    session.pause()
    session.write_block(0xF00000, case.work)
    for name in base.REG_NAMES[:-1]:
        session.set_reg(name, case.regs[name])
    session.set_reg("SP", case.entry_sp)
    session.set_reg("USP", case.entry_sp)
    session.set_reg("SR", case.sr | 0x0700)
    session.set_reg("PC", ENTRY_PC)
    capture = session.cmd(
        "capture_at_pc",
        pc=case.return_pc,
        addr=0xF00000,
        len=MAPPED_WORK_SIZE,
        nth=1,
        exp_sp=(case.entry_sp + 4) & 0xFFFFFF,
        maxFrames=120,
        timeout=120,
    )
    if not capture.get("registers"):
        raise RuntimeError(
            f"MAME did not return from ${ENTRY_PC:06X}: {capture!r}"
        )
    raw = capture["registers"]
    regs = {
        name: int(raw[name]) & 0xFFFFFFFF
        for name in base.REG_NAMES[:-1]
    }
    regs["A7"] = int(raw["SP"]) & 0xFFFFFFFF
    return base.Result(
        regs,
        int(raw["SR"]) & 0xFFFF,
        bytes.fromhex(capture["hex"]),
        [],
        [],
    )


def prepare_nexen(
    session: base.McpSession,
    nat: Path,
    case: Case,
    *,
    native: bool,
) -> None:
    session.load_state(str(nat))
    session.pause()
    launch_regs = dict(case.regs)
    if native:
        launch_regs["A7"] = (case.entry_sp + 4) & 0xFFFFFFFF
    registers = b"".join(
        base.le32(launch_regs[name]) for name in base.REG_NAMES
    )
    session.write_memory(base.DP_SPACE, 0x0000, registers.hex())
    for offset in range(0, FULL_WORK_SIZE, 0x4000):
        session.write_memory(
            base.SNES_SPACE,
            0x400000 + offset,
            case.work[offset : offset + 0x4000].hex(),
        )
    live.park_snes_cpu(session)

    flags = case.sr & base.CCR_MASK
    live.write_u16(session, 0x6E, flags & 1)
    live.write_u16(session, 0x72, (flags >> 1) & 1)
    live.write_u16(session, 0x60, (flags >> 2) & 1)
    live.write_u16(session, 0x70, (flags >> 3) & 1)
    live.write_u16(session, 0xA2, (flags >> 4) & 1)
    live.write_u16(session, 0x7C, 7)
    live.write_u16(session, 0x7E, 0)
    live.write_u16(session, 0xA4, launch_regs["A7"] & 0xFFFF)
    live.write_u16(
        session, 0xA6, (launch_regs["A7"] >> 16) & 0xFFFF
    )
    live.write_u16(session, 0xA8, 1)
    live.write_u16(session, 0xAA, 0)
    live.write_u16(session, 0x4A, 0)
    live.write_u16(session, 0x4C, 0)
    live.write_u16(session, 0x4E, 0)
    live.write_u16(session, 0xAC, 0x7000)
    live.write_u16(session, 0x0700, 0)
    live.write_u16(session, 0x0702, 0)
    live.write_u16(session, 0x0704, 1)
    live.write_u16(session, 0x0710, 0)
    live.write_u16(session, 0x0712, 0)
    live.write_u16(session, 0x0714, 0)
    live.write_u16(session, 0x0716, (case.return_pc >> 16) & 0xFF)
    live.write_u16(session, 0x0718, 0xFFF8)
    live.write_u16(session, 0x071A, 1 if native else 0)
    for address in (0x072E, 0x0730, 0x0734, 0x0736, 0x0738, 0x073A, 0x073C):
        live.write_u16(session, address, 0)
    live.write_u16(
        session,
        0x40,
        (case.return_pc if native else ENTRY_PC) & 0xFFFF,
    )
    live.write_u16(
        session,
        0x42,
        (
            (case.return_pc if native else ENTRY_PC) >> 16
        ) & 0xFF,
    )
    live.set_sa1_pc(session, ENTRY_NATIVE if native else INEXT)


def nexen_result(
    session: base.McpSession,
    nat: Path,
    case: Case,
    *,
    native: bool,
) -> tuple[base.Result, dict[str, Any]]:
    prepare_nexen(session, nat, case, native=native)
    return_offset = 0x10000 + case.return_pc
    illegal_offset = OP_ILLEGAL - 0x8000
    return_original = bytes(
        session.read_memory("snesPrgRom", return_offset, 2)
    )
    illegal_original = bytes(
        session.read_memory("snesPrgRom", illegal_offset, 2)
    )
    session.write_memory("snesPrgRom", return_offset, "4afc")
    session.write_memory("snesPrgRom", illegal_offset, "80fe")
    hook = session.add_exec_hook(OP_ILLEGAL, cpu_type="Sa1")
    session.drain_notifications(timeout=0.10)
    start_cycles = int(session.get_cpu_state("Sa1")["cycleCount"])
    try:
        hit = session.run_until(max_frames=240, hook_handle=hook)
        session.pause()
    finally:
        session.remove_hook(hook)
        session.write_memory(
            "snesPrgRom", return_offset, return_original.hex()
        )
        session.write_memory(
            "snesPrgRom", illegal_offset, illegal_original.hex()
        )
        session.drain_notifications(timeout=0.05)
    end_cycles = int(session.get_cpu_state("Sa1")["cycleCount"])
    observed_pc = live.read_u16(session, 0x40) | (
        (live.read_u16(session, 0x42) & 0xFF) << 16
    )
    halt = live.read_u16(session, 0x4E)
    if (
        (hit or {}).get("reason") != "hookFired"
        or observed_pc != case.return_pc
        or halt
    ):
        raise RuntimeError(
            f"Nexen did not return, native={native}: hit={hit!r}, "
            f"pc=${observed_pc:06X}, halt=${halt:04X}"
        )
    result = base.Result(
        live.captured_regs(session),
        (
            0x2000
            | ((live.read_u16(session, 0x7C) & 7) << 8)
            | live.captured_ccr(session)
        ),
        bytes(
            session.read_memory(
                base.SNES_SPACE, 0x400000, MAPPED_WORK_SIZE
            )
        ),
        [],
        [],
        end_cycles - start_cycles,
    )
    return result, {
        "variant": "native" if native else "interpreter",
        "entry": f"{ENTRY_NATIVE if native else INEXT:06X}",
        "hit": hit,
        "return_pc": f"{observed_pc:06X}",
        "halt": halt,
        "cycles": result.cycles,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--rom", type=Path, default=DEFAULT_ROM)
    parser.add_argument("--fixture", type=Path, default=DEFAULT_FIXTURE)
    parser.add_argument("--ordinal", type=int, default=1)
    parser.add_argument("--nexen", type=Path, default=base.DEFAULT_NEXEN)
    parser.add_argument("--nat", type=Path, default=DEFAULT_NAT)
    parser.add_argument("--port", type=int, default=9273)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    for label, path in (
        ("ROM", args.rom),
        ("MAME fixture", args.fixture),
        ("Nexen", args.nexen),
        ("NAT", args.nat),
    ):
        if not path.exists():
            parser.error(f"missing {label}: {path}")
    if args.output.exists():
        parser.error(f"output already exists: {args.output}")

    case = load_case(args.fixture.resolve(), args.ordinal)
    source_work = (
        args.fixture.resolve() / f"{case.source_row['name']}.work.bin"
    )
    events: list[dict[str, Any]] = [
        {
            "event": "provenance",
            "scope": CASE_SCOPE,
            "mame": "/snap/bin/mame 0.287",
            "nexen": str(args.nexen.resolve()),
            "nexen_sha256": shared.sha256(args.nexen),
            "rom": str(args.rom.resolve()),
            "rom_sha256": shared.sha256(args.rom),
            "nat": str(args.nat.resolve()),
            "nat_sha256": shared.sha256(args.nat),
            "fixture_directory": str(args.fixture.resolve()),
            "fixture_log_sha256": shared.sha256(
                args.fixture.resolve() / "capture.jsonl"
            ),
            "fixture_work": str(source_work),
            "fixture_work_sha256": shared.sha256(source_work),
            "fixture_tick": case.tick,
            "fixture_frame": case.frame,
            "fixture_ordinal": case.ordinal,
            "entry_pc": f"{ENTRY_PC:06X}",
            "native_entry": f"{ENTRY_NATIVE:06X}",
            "return_pc": f"{case.return_pc:06X}",
            "native_stack_transform": (
                "launch A7 = architectural entry A7 + 4; native prologue "
                "recreates the skipped return"
            ),
            "irq_isolation": "interrupt mask forced to 7 in all three arms",
            "variants": [
                "mame-original",
                "snes-interpreter",
                "snes-native",
            ],
            "time": time.time(),
        }
    ]
    print(json.dumps(events[0], sort_keys=True), flush=True)

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
        oracle = mame_result(mame, case)
        event = {
            "event": "mame_case",
            "case": case.name,
            "return_pc": f"{case.return_pc:06X}",
            "work_sha256": hashlib.sha256(oracle.work).hexdigest(),
        }
        events.append(event)
        print(json.dumps(event, sort_keys=True), flush=True)
    finally:
        mame.stop()

    stderr = args.output.with_suffix(".nexen.stderr.log")
    stderr.parent.mkdir(parents=True, exist_ok=True)
    with base.McpSession(
        rom=str(args.rom.resolve()),
        mesen=str(args.nexen.resolve()),
        cwd=str(ROOT),
        port=args.port,
        boot_wait=8.0,
        socket_timeout=240.0,
        stderr_log=stderr,
    ) as nexen:
        for native in (False, True):
            result, route = nexen_result(
                nexen, args.nat.resolve(), case, native=native
            )
            event = shared.compare(
                case,
                oracle,
                result,
                "snes-native" if native else "snes-interpreter",
                route,
            )
            events.append(event)
            print(json.dumps(event, sort_keys=True), flush=True)

    cases = [event for event in events if event.get("event") == "case"]
    green = sum(event["result"] == "green" for event in cases)
    summary = {
        "event": "summary",
        "result": "green" if green == len(cases) else "red",
        "green": green,
        "red": len(cases) - green,
        "total": len(cases),
        "time": time.time(),
    }
    events.append(summary)
    print(json.dumps(summary, sort_keys=True), flush=True)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        "".join(
            json.dumps(event, sort_keys=True) + "\n"
            for event in events
        ),
        encoding="utf-8",
    )
    return 0 if summary["result"] == "green" else 1


if __name__ == "__main__":
    raise SystemExit(main())
