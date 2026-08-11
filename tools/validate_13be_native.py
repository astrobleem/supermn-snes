#!/usr/bin/env python3
"""Organic three-way differential for the $0013BE collision helper.

The retained MAME movie capture observes the failing Stage-1 call while the
CPU fetches ``JSR (A0)``'s target.  MAME's program-space read tap runs before
the JSR return push retires, so this harness derives the architectural helper
entry by subtracting four from A7 and installing the reported next PC as the
big-endian return long.  No other register, CCR bit, or work-RAM byte changes.

MAME executes the original helper through RTS.  Nexen replays that identical
entry twice: once through the interpreter with gameplay xlat disabled, and
once through the production table body at $94:AB04.  Both SNES arms freeze on
the fetched organic return PC before the caller executes.  Every D/A register,
CCR/X bit, interrupt mask, and mapped low 16 KiB work-RAM byte is compared.

This is a focused state-injected differential, not fresh-boot or performance
evidence.  The retained controller campaign supplies the separate organic
lineage.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import validate_1f2e4_native as live
import validate_render_helpers as base


ROOT = Path(__file__).resolve().parents[1]
EVIDENCE = ROOT / "build" / "playtest-investigation-20260725"
DEFAULT_FIXTURE = EVIDENCE / "failure-3662-mame-entry13be-tick3277-v1"
DEFAULT_ROM = ROOT / "build" / "interp.sfc"
DEFAULT_NAT = Path("/tmp/b0_native.mss")
ENTRY_PC = 0x0013BE
ENTRY_NATIVE = 0x94AB04
INEXT = 0x00D128
DEBUG_SPIN = 0x00E2CF
OP_ILLEGAL = 0x00CDED
MAPPED_WORK_SIZE = 0x4000
FULL_WORK_SIZE = 0x10000
CASE_SCOPE = (
    "organic Stage-1 $0013BE collision-helper MAME/interpreter/native "
    "differential; focused injected state, not fresh boot or fps"
)


@dataclass
class OrganicCase:
    name: str
    regs: dict[str, int]
    sr: int
    work: bytes
    tick: int
    frame: int
    ordinal: int
    pre_jsr_sp: int
    return_pc: int
    source_row: dict[str, Any]

    @property
    def entry_sp(self) -> int:
        return self.regs["A7"]


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def load_case(directory: Path, ordinal: int) -> OrganicCase:
    log_path = directory / "capture.jsonl"
    if not log_path.is_file():
        raise RuntimeError(f"missing MAME capture log: {log_path}")
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
            f"expected one $0013BE ordinal-{ordinal} capture, got {len(matches)}"
        )
    row = matches[0]
    work_path = directory / f"{row['name']}.work.bin"
    work = bytearray(work_path.read_bytes())
    if len(work) != FULL_WORK_SIZE:
        raise RuntimeError(f"{work_path}: expected 65536 bytes")

    pre_jsr_sp = int(row["A7"]) & 0xFFFFFFFF
    entry_sp = (pre_jsr_sp - 4) & 0xFFFFFFFF
    if (pre_jsr_sp >> 16) != 0x00F0 or (entry_sp >> 16) != 0x00F0:
        raise RuntimeError(
            f"fixture stack is not mapped work RAM: "
            f"pre=${pre_jsr_sp:08X}, entry=${entry_sp:08X}"
        )
    # At the indirect JSR target-fetch tap, MAME has selected the target and
    # advanced PC to the caller continuation, but the return push is not yet
    # visible in the dumped work bytes.  Reconstruct exactly that sole
    # architectural JSR effect.
    return_pc = int(row["PC"]) & 0xFFFFFF
    stack = entry_sp & 0xFFFF
    work[stack : stack + 4] = return_pc.to_bytes(4, "big")

    regs = {
        name: int(row[name]) & 0xFFFFFFFF
        for name in base.REG_NAMES[:-1]
    }
    regs["A7"] = entry_sp
    return OrganicCase(
        name=f"mame-tick-{int(row['tick']):05d}-call-{ordinal}",
        regs=regs,
        sr=int(row["SR"]) & 0xFFFF,
        work=bytes(work),
        tick=int(row["tick"]),
        frame=int(row["frame"]),
        ordinal=ordinal,
        pre_jsr_sp=pre_jsr_sp,
        return_pc=return_pc,
        source_row=row,
    )


def mame_result(
    session: base.MameSession,
    case: OrganicCase,
) -> base.Result:
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
        exp_sp=case.pre_jsr_sp & 0xFFFFFF,
        maxFrames=30,
        timeout=30,
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
    case: OrganicCase,
    *,
    native: bool,
) -> None:
    session.load_state(str(nat))
    session.pause()
    registers = b"".join(
        base.le32(case.regs[name]) for name in base.REG_NAMES
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
    live.write_u16(session, 0xA4, case.entry_sp & 0xFFFF)
    live.write_u16(session, 0xA6, (case.entry_sp >> 16) & 0xFFFF)
    live.write_u16(session, 0xA8, 1)
    live.write_u16(session, 0xAA, 0)
    live.write_u16(session, 0x4A, 0)
    live.write_u16(session, 0x4C, 0)
    live.write_u16(session, 0x4E, 0)
    live.write_u16(session, 0xAC, 0x7000)
    live.write_u16(session, 0x0700, 0)
    live.write_u16(session, 0x0702, 0)
    live.write_u16(session, 0x0704, 1)
    # Production packs the per-fetch debug-freeze call to NOPs.  The caller
    # return opcode is patched to ILLEGAL below, so leave the unavailable
    # $0710 mechanism disarmed.
    live.write_u16(session, 0x0710, 0)
    live.write_u16(session, 0x0712, 0)
    live.write_u16(session, 0x0714, 0)
    live.write_u16(session, 0x0716, (case.return_pc >> 16) & 0xFF)
    live.write_u16(session, 0x0718, 0xFFF8)
    live.write_u16(session, 0x071A, 1 if native else 0)
    live.write_u16(session, 0x072E, 0)
    live.write_u16(session, 0x0730, 0)
    live.write_u16(session, 0x0734, 0)
    live.write_u16(session, 0x0736, 0)
    live.write_u16(session, 0x073A, 0)
    live.write_u16(session, 0x073C, 0)
    live.write_u16(session, 0x40, ENTRY_PC & 0xFFFF)
    live.write_u16(session, 0x42, (ENTRY_PC >> 16) & 0xFF)
    live.set_sa1_pc(session, ENTRY_NATIVE if native else INEXT)


def nexen_result(
    session: base.McpSession,
    nat: Path,
    case: OrganicCase,
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
        hit = session.run_until(max_frames=120, hook_handle=hook)
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
            f"Nexen did not freeze at organic return, native={native}: "
            f"hit={hit!r}, pc=${observed_pc:06X}, "
            f"halt=${halt:04X}"
        )
    sr = (
        0x2000
        | ((live.read_u16(session, 0x7C) & 7) << 8)
        | live.captured_ccr(session)
    )
    result = base.Result(
        live.captured_regs(session),
        sr,
        bytes(
            session.read_memory(
                base.SNES_SPACE, 0x400000, MAPPED_WORK_SIZE
            )
        ),
        [],
        [],
        end_cycles - start_cycles,
    )
    route = {
        "variant": "native" if native else "interpreter",
        "entry": f"{ENTRY_NATIVE if native else INEXT:06X}",
        "hit": hit,
        "stop": (
            f"patched ${case.return_pc:06X} to ILLEGAL and "
            f"self-looped op_illegal ${OP_ILLEGAL:06X}"
        ),
        "return_pc": f"{observed_pc:06X}",
        "halt": halt,
        "cycles": result.cycles,
    }
    return result, route


def compare(
    case: OrganicCase,
    oracle: base.Result,
    observed: base.Result,
    variant: str,
    route: dict[str, Any],
) -> dict[str, Any]:
    reg_mismatches = {
        name: {
            "mame": oracle.regs[name],
            "nexen": observed.regs[name],
        }
        for name in base.REG_NAMES
        if oracle.regs[name] != observed.regs[name]
    }
    ccr_mismatch = (oracle.sr & base.CCR_MASK) != (
        observed.sr & base.CCR_MASK
    )
    mask_mismatch = ((oracle.sr >> 8) & 7) != ((observed.sr >> 8) & 7)
    offsets = [
        index
        for index, (left, right) in enumerate(
            zip(oracle.work, observed.work)
        )
        if left != right
    ]
    green = not (
        reg_mismatches or ccr_mismatch or mask_mismatch or offsets
    )
    return {
        "event": "case",
        "case": case.name,
        "variant": variant,
        "result": "green" if green else "red",
        "reg_mismatches": reg_mismatches,
        "mame_ccr": oracle.sr & base.CCR_MASK,
        "nexen_ccr": observed.sr & base.CCR_MASK,
        "mame_mask": (oracle.sr >> 8) & 7,
        "nexen_mask": (observed.sr >> 8) & 7,
        "work_mismatch_count": len(offsets),
        "work_mismatch_first": [
            {
                "address": f"F0{offset:04X}",
                "mame": oracle.work[offset],
                "nexen": observed.work[offset],
            }
            for offset in offsets[:32]
        ],
        "route": route,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--rom", type=Path, default=DEFAULT_ROM)
    parser.add_argument("--fixture", type=Path, default=DEFAULT_FIXTURE)
    parser.add_argument("--ordinal", type=int, default=3)
    parser.add_argument("--nexen", type=Path, default=base.DEFAULT_NEXEN)
    parser.add_argument("--nat", type=Path, default=DEFAULT_NAT)
    parser.add_argument("--port", type=int, default=9268)
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
        args.fixture.resolve()
        / f"{case.source_row['name']}.work.bin"
    )
    provenance = {
        "event": "provenance",
        "scope": CASE_SCOPE,
        "mame": "/snap/bin/mame 0.287",
        "nexen": str(args.nexen.resolve()),
        "nexen_sha256": sha256(args.nexen),
        "rom": str(args.rom.resolve()),
        "rom_sha256": sha256(args.rom),
        "nat": str(args.nat.resolve()),
        "nat_sha256": sha256(args.nat),
        "fixture_directory": str(args.fixture.resolve()),
        "fixture_log_sha256": sha256(
            args.fixture.resolve() / "capture.jsonl"
        ),
        "fixture_work": str(source_work),
        "fixture_work_sha256": sha256(source_work),
        "fixture_tick": case.tick,
        "fixture_frame": case.frame,
        "fixture_ordinal": case.ordinal,
        "fixture_transform": {
            "pre_jsr_sp": f"{case.pre_jsr_sp:08X}",
            "entry_sp": f"{case.entry_sp:08X}",
            "return_pc": f"{case.return_pc:06X}",
            "operation": (
                "A7 -= 4; write reported next PC as big-endian return long"
            ),
        },
        "entry_pc": f"{ENTRY_PC:06X}",
        "native_entry": f"{ENTRY_NATIVE:06X}",
        "irq_isolation": "interrupt mask forced to 7 in all three arms",
        "variants": ["mame-original", "snes-interpreter", "snes-native"],
        "time": time.time(),
    }
    events: list[dict[str, Any]] = [provenance]
    print(json.dumps(provenance, sort_keys=True), flush=True)

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
        socket_timeout=180.0,
        stderr_log=stderr,
    ) as nexen:
        for native in (False, True):
            result, route = nexen_result(
                nexen, args.nat.resolve(), case, native=native
            )
            event = compare(
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
