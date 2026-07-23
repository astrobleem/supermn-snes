#!/usr/bin/env python3
"""Organic MAME/Nexen differential for the guarded $01C9AE empty pass.

Capture the one-shot production input at fetched PC $01C9AE from the last
diagnostic ROM that still interpreted the loop.  MAME executes the original
sixteen MOVE.B/BEQ/ADDA/DBRA records to $01CD40.  Nexen executes both the
direct bank-$9E body and the real bank-$01 fetch-choke/xlat route.

Two synthetic guard misses (an active first record and an imminent virtual
IRQ) compare choke-on against the unchanged interpreter at $01C9B0.  The
script also proves that $02A190 still reaches its native body through the
sparse bank-$02 route after donating its dense xlat page.  This is bounded
semantic and local-cycle evidence, not FPS evidence.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import time
from dataclasses import dataclass
from pathlib import Path

import validate_d96_hle as base
import validate_1f2e4_native as live


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CAPTURE_ROM = (
    ROOT
    / "build/playability-20260720/fanout-native-diagnostic-v1/interp.sfc"
)
DEFAULT_ROM = (
    ROOT
    / "build/playability-20260720/1c9ae-empty-diagnostic-v4/interp.sfc"
)
DEFAULT_STATE = (
    ROOT
    / "build/playability-20260720/"
    "11752-direct-charge-production-v1-coldboot-immediate-v1/"
    "gameplay_detected.mss"
)
ENTRY_PC = 0x01C9AE
NEXT_PC = 0x01C9B0
EXIT_PC = 0x01CD40
# MAME's exposed PC is the post-prefetch address while CURPC is the current
# instruction.  Request the next sequential PC so the captured CURPC is the
# desired pre-$01CD40 seam (and the final DBRA has already committed D5=$FFFF).
MAME_CAPTURE_PC = 0x01CD44
ENTRY_NATIVE = 0x9ED400
ENTRY_2A190 = 0x95B660
IRQ_NONE = 0x0080CB
OJMP_HOOK = 0x00D1B3
DEBUG_SPIN = 0x00E2CF
CAPTURE_BUTTONS = 0x82
FULL_WORK_SIZE = 0x10000
MAPPED_WORK_SIZE = 0x4000
CCR_MASK = base.CCR_MASK


@dataclass
class Case:
    regs: dict[str, int]
    sr: int
    work: bytes
    tick: int
    frame: int
    capture_frames_advanced: int


@dataclass
class ConsoleResult:
    regs: dict[str, int]
    sr: int
    work: bytes
    cycles: int
    ac: int


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def capture_case(
    rom: Path,
    state: Path,
    nexen: Path,
    port: int,
    stderr_log: Path,
) -> Case:
    """Freeze the old interpreter before the first $01C9AE instruction."""

    with base.McpSession(
        rom=str(rom),
        mesen=str(nexen),
        cwd=ROOT,
        port=port,
        boot_wait=8.0,
        socket_timeout=180.0,
        stderr_log=stderr_log,
    ) as m:
        m.pause()
        m.load_state(str(state))
        m.pause()
        m.tool(
            "set_input",
            {"port": 0, "buttons": CAPTURE_BUTTONS, "hold": True},
        )
        live.write_u16(m, 0x0710, ENTRY_PC & 0xFFFF)
        live.write_u16(m, 0x0712, 0)
        live.write_u16(m, 0x0714, 0)
        live.write_u16(m, 0x0716, (ENTRY_PC >> 16) & 0xFF)
        live.write_u16(m, 0x0718, 0xFFF8)
        live.write_u16(m, 0x0730, 0x5A5A)
        hook = m.add_exec_hook(DEBUG_SPIN, cpu_type="Sa1")
        m.drain_notifications(timeout=0.05)
        try:
            hit, frames_advanced = live.run_to_hook(m, hook, attempts=16)
            m.pause()
        finally:
            m.remove_hook(hook)
        observed_pc = live.read_u16(m, 0x40) | (
            (live.read_u16(m, 0x42) & 0xFF) << 16
        )
        if (
            (hit or {}).get("reason") != "hookFired"
            or not live.read_u16(m, 0x0712)
            or observed_pc != ENTRY_PC
        ):
            raise RuntimeError(
                f"reference did not freeze at ${ENTRY_PC:06X} after "
                f"{frames_advanced} frames: hit={hit!r}, "
                f"marker={live.read_u16(m, 0x0712)}, pc=${observed_pc:06X}"
            )
        regs = live.captured_regs(m)
        work = bytes(m.read_memory(base.SNES_SPACE, 0x400000, FULL_WORK_SIZE))
        a0 = regs["A0"] & 0xFFFFFF
        statuses = [work[(a0 + offset) & 0xFFFF] for offset in range(0, 0x300, 0x30)]
        if (a0 >> 16) != 0xF0 or (regs["D5"] & 0xFFFFFFFF) != 0x0000000F:
            raise RuntimeError(
                f"unexpected organic loop shape: A0=${a0:06X}, "
                f"D5=${regs['D5']:08X}"
            )
        if any(statuses):
            raise RuntimeError(f"organic record statuses are not all zero: {statuses}")
        return Case(
            regs=regs,
            sr=live.captured_sr(m),
            work=work,
            tick=live.work_be16(work, 0x1C56),
            frame=int(m.get_state().get("frameCount", 0)),
            capture_frames_advanced=frames_advanced,
        )


def mame_result(session: base.MameSession, case: Case) -> base.Result:
    session.pause()
    session.write_block(0xF00000, case.work[:MAPPED_WORK_SIZE])
    for name in base.REG_NAMES[:-1]:
        session.set_reg(name, case.regs[name])
    entry_sp = case.regs["A7"] & 0xFFFFFF
    session.set_reg("SP", entry_sp)
    session.set_reg("USP", entry_sp)
    session.set_reg("SR", case.sr | 0x0700)
    session.set_reg("PC", ENTRY_PC)
    captured = session.cmd(
        "capture_at_pc",
        pc=MAME_CAPTURE_PC,
        addr=0xF00000,
        len=MAPPED_WORK_SIZE,
        nth=1,
        exp_sp=entry_sp,
        maxFrames=60,
        timeout=60,
    )
    if not captured.get("registers"):
        raise RuntimeError(
            f"MAME did not reach ${EXIT_PC:06X} from ${ENTRY_PC:06X}: "
            f"{captured!r}"
        )
    regs = captured["registers"]
    if (regs.get("CURPC", -1) & 0xFFFFFF) != EXIT_PC:
        raise RuntimeError(
            f"MAME prefetch seam mismatch: requested exposed PC "
            f"${MAME_CAPTURE_PC:06X}, got CURPC "
            f"${regs.get('CURPC', -1) & 0xFFFFFF:06X}"
        )
    result_regs = {
        name: regs[name] & 0xFFFFFFFF for name in base.REG_NAMES[:-1]
    }
    result_regs["A7"] = regs["SP"] & 0xFFFFFFFF
    return base.Result(
        result_regs,
        regs["SR"] & 0xFFFF,
        bytes.fromhex(captured["hex"]),
    )


def prepare_console(
    m: base.McpSession,
    nat: Path,
    case: Case,
    work: bytes,
    *,
    target_pc: int,
    choke_gate: int,
    ac: int,
) -> None:
    m.load_state(str(nat))
    m.pause()
    reg_blob = b"".join(base.le32(case.regs[name]) for name in base.REG_NAMES)
    m.write_memory(base.DP_SPACE, 0x00, reg_blob.hex())
    for offset in range(0, FULL_WORK_SIZE, 0x4000):
        m.write_memory(
            base.SNES_SPACE,
            0x400000 + offset,
            work[offset : offset + 0x4000].hex(),
        )
    live.park_snes_cpu(m)

    flags = case.sr & CCR_MASK
    live.write_u16(m, 0x6E, flags & 1)
    live.write_u16(m, 0x72, (flags >> 1) & 1)
    live.write_u16(m, 0x60, (flags >> 2) & 1)
    live.write_u16(m, 0x70, (flags >> 3) & 1)
    live.write_u16(m, 0xA2, (flags >> 4) & 1)
    live.write_u16(m, 0x7C, 7)
    live.write_u16(m, 0x40, ENTRY_PC & 0xFFFF)
    live.write_u16(m, 0x42, (ENTRY_PC >> 16) & 0xFF)
    live.write_u16(m, 0x4A, 0)
    live.write_u16(m, 0x4C, 0)
    live.write_u16(m, 0xA4, case.regs["A7"] & 0xFFFF)
    live.write_u16(m, 0xA6, (case.regs["A7"] >> 16) & 0xFFFF)
    live.write_u16(m, 0xA8, 1)
    live.write_u16(m, 0xAA, 0)
    live.write_u16(m, 0xAC, ac)
    live.write_u16(m, 0x0702, 0)
    live.write_u16(m, 0x0704, 1)
    live.write_u16(m, 0x0710, target_pc & 0xFFFF)
    live.write_u16(m, 0x0712, 0)
    live.write_u16(m, 0x0714, 0)
    live.write_u16(m, 0x0716, (target_pc >> 16) & 0xFF)
    live.write_u16(m, 0x0718, 0xFFF8)
    live.write_u16(m, 0x071A, 1)
    live.write_u16(m, 0x072E, 0)
    live.write_u16(m, 0x0730, 0x5A5A)
    live.write_u16(m, 0x0734, 0)
    live.write_u16(m, 0x0736, 0)
    live.write_u16(m, 0x0738, 0)
    live.write_u16(m, 0x073A, choke_gate)
    live.write_u16(m, 0x073C, 0)


def console_result(
    m: base.McpSession,
    nat: Path,
    case: Case,
    work: bytes,
    *,
    variant: str,
    target_pc: int,
    choke_gate: int,
    ac: int,
) -> ConsoleResult:
    prepare_console(
        m,
        nat,
        case,
        work,
        target_pc=target_pc,
        choke_gate=choke_gate,
        ac=ac,
    )
    start_pc = ENTRY_NATIVE if variant == "native-direct" else IRQ_NONE
    live.set_sa1_pc(m, start_pc)
    hook = m.add_exec_hook(DEBUG_SPIN, cpu_type="Sa1")
    m.drain_notifications(timeout=0.05)
    start_cycles = int(m.get_cpu_state("Sa1")["cycleCount"])
    try:
        hit = m.run_until(max_frames=24, hook_handle=hook)
        m.pause()
    finally:
        m.remove_hook(hook)
    if (hit or {}).get("reason") != "hookFired":
        raise RuntimeError(
            f"Nexen {variant} did not freeze at ${target_pc:06X}: {hit!r}"
        )
    observed_pc = live.read_u16(m, 0x40) | (
        (live.read_u16(m, 0x42) & 0xFF) << 16
    )
    if not live.read_u16(m, 0x0712) or observed_pc != target_pc:
        raise RuntimeError(
            f"Nexen {variant} froze at ${observed_pc:06X}, "
            f"expected ${target_pc:06X}"
        )
    end_cycles = int(m.get_cpu_state("Sa1")["cycleCount"])
    sr = 0x2700 | live.captured_ccr(m)
    return ConsoleResult(
        regs=live.captured_regs(m),
        sr=sr,
        work=bytes(
            m.read_memory(base.SNES_SPACE, 0x400000, MAPPED_WORK_SIZE)
        ),
        cycles=end_cycles - start_cycles,
        ac=live.read_u16(m, 0xAC),
    )


def compare_results(
    name: str,
    left: base.Result | ConsoleResult,
    right: ConsoleResult,
    *,
    compare_ac: bool = False,
) -> dict:
    reg_mismatches = {
        reg: {"reference": left.regs[reg], "candidate": right.regs[reg]}
        for reg in base.REG_NAMES
        if left.regs[reg] != right.regs[reg]
    }
    work_mismatches = [
        offset
        for offset, (a, b) in enumerate(zip(left.work, right.work))
        if a != b
    ]
    ccr_mismatch = (left.sr & CCR_MASK) != (right.sr & CCR_MASK)
    ac_mismatch = compare_ac and getattr(left, "ac") != right.ac
    return {
        "event": "case",
        "case": name,
        "result": (
            "green"
            if not reg_mismatches
            and not ccr_mismatch
            and not work_mismatches
            and not ac_mismatch
            else "red"
        ),
        "reg_mismatches": reg_mismatches,
        "reference_ccr": left.sr & CCR_MASK,
        "candidate_ccr": right.sr & CCR_MASK,
        "work_mismatch_count": len(work_mismatches),
        "work_mismatch_first": [f"F0{x:04X}" for x in work_mismatches[:24]],
        "reference_ac": getattr(left, "ac", None),
        "candidate_ac": right.ac,
        "nexen_cycles": right.cycles,
    }


def probe_2a190_sparse_route(
    m: base.McpSession,
    nat: Path,
    case: Case,
) -> dict:
    prepare_console(
        m,
        nat,
        case,
        case.work,
        target_pc=EXIT_PC,
        choke_gate=1,
        ac=0x7000,
    )
    live.write_u16(m, 0x40, 0xA190)
    live.write_u16(m, 0x42, 0x0002)
    live.write_u16(m, 0x0712, 0)
    live.set_sa1_pc(m, OJMP_HOOK)
    hook = m.add_exec_hook(ENTRY_2A190, cpu_type="Sa1")
    m.drain_notifications(timeout=0.05)
    start = int(m.get_cpu_state("Sa1")["cycleCount"])
    try:
        hit = m.run_until(max_frames=4, hook_handle=hook)
        m.pause()
    finally:
        m.remove_hook(hook)
    fired = (hit or {}).get("reason") == "hookFired"
    event = {
        "event": "route_probe",
        "route": "$02A190 ojmp_hook -> xlat -> sparse $9D:DA00 -> $95:B660",
        "result": "green" if fired else "red",
        "hook_fired": fired,
        "cycles": int(m.get_cpu_state("Sa1")["cycleCount"]) - start,
        "hit": hit,
    }
    if not fired:
        raise RuntimeError(f"$02A190 sparse route did not fire: {hit!r}")
    return event


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--capture-rom", type=Path, default=DEFAULT_CAPTURE_ROM)
    parser.add_argument("--rom", type=Path, default=DEFAULT_ROM)
    parser.add_argument("--state", type=Path, default=DEFAULT_STATE)
    parser.add_argument("--nexen", type=Path, default=base.DEFAULT_NEXEN)
    parser.add_argument("--nat", type=Path, default=base.DEFAULT_NAT)
    parser.add_argument("--port", type=int, default=7523)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    for path in (args.capture_rom, args.rom, args.state, args.nexen, args.nat):
        if not path.is_file():
            parser.error(f"missing required input: {path}")
    if args.output.exists():
        parser.error(f"output already exists: {args.output}")

    args.output.parent.mkdir(parents=True, exist_ok=True)
    fixture_dir = args.output.parent / f"{args.output.stem}-fixture"
    if fixture_dir.exists():
        parser.error(f"fixture directory already exists: {fixture_dir}")
    fixture_dir.mkdir()

    events: list[dict] = []
    provenance = {
        "event": "provenance",
        "scope": (
            "organic $01C9AE MAME/Nexen bounded differential, two guard-miss "
            "A/Bs, and $02A190 sparse-route proof; not fps"
        ),
        "mame": "/snap/bin/mame 0.287",
        "nexen": str(args.nexen.resolve()),
        "nexen_sha256": sha256(args.nexen),
        "capture_rom": str(args.capture_rom.resolve()),
        "capture_rom_sha256": sha256(args.capture_rom),
        "candidate_rom": str(args.rom.resolve()),
        "candidate_rom_sha256": sha256(args.rom),
        "state": str(args.state.resolve()),
        "state_sha256": sha256(args.state),
        "nat": str(args.nat.resolve()),
        "nat_sha256": sha256(args.nat),
        "entry_pc": f"{ENTRY_PC:06X}",
        "entry_native": f"{ENTRY_NATIVE:06X}",
        "exit_pc": f"{EXIT_PC:06X}",
        "mame_capture_pc": f"{MAME_CAPTURE_PC:06X}",
        "time": time.time(),
    }
    events.append(provenance)
    print(json.dumps(provenance, sort_keys=True), flush=True)

    case = capture_case(
        args.capture_rom,
        args.state,
        args.nexen,
        args.port,
        fixture_dir / "capture.nexen.stderr.log",
    )
    fixture = {
        "event": "fixture",
        "tick": case.tick,
        "frame": case.frame,
        "capture_frames_advanced": case.capture_frames_advanced,
        "sr": case.sr,
        "regs": case.regs,
        "work_sha256": hashlib.sha256(case.work).hexdigest(),
    }
    (fixture_dir / "case-00.work.bin").write_bytes(case.work)
    (fixture_dir / "case-00.json").write_text(
        json.dumps(fixture, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    events.append(fixture)
    print(json.dumps(fixture, sort_keys=True), flush=True)

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
        arcade = mame_result(mame, case)
    finally:
        mame.stop()
    mame_event = {
        "event": "mame_case",
        "entry_pc": f"{ENTRY_PC:06X}",
        "exit_pc": f"{EXIT_PC:06X}",
        "ccr": arcade.sr & CCR_MASK,
    }
    events.append(mame_event)
    print(json.dumps(mame_event, sort_keys=True), flush=True)

    with base.McpSession(
        rom=str(args.rom),
        mesen=str(args.nexen),
        cwd=ROOT,
        port=args.port + 1,
        boot_wait=8.0,
        socket_timeout=180.0,
        stderr_log=fixture_dir / "differential.nexen.stderr.log",
    ) as nexen:
        for variant in ("native-direct", "production-route"):
            result = console_result(
                nexen,
                args.nat,
                case,
                case.work,
                variant=variant,
                target_pc=EXIT_PC,
                choke_gate=1,
                ac=0x7000,
            )
            event = compare_results(variant, arcade, result)
            event["expected_ac"] = 0x7000 - 64
            event["ac_charge_green"] = result.ac == 0x7000 - 64
            if not event["ac_charge_green"]:
                event["result"] = "red"
            events.append(event)
            print(json.dumps(event, sort_keys=True), flush=True)

        active_work = bytearray(case.work)
        active_work[case.regs["A0"] & 0xFFFF] = 1
        for name, work, ac in (
            ("guard-active-record", bytes(active_work), 0x7000),
            ("guard-imminent-irq", case.work, 0x003F),
        ):
            interpreted = console_result(
                nexen,
                args.nat,
                case,
                work,
                variant="production-route",
                target_pc=NEXT_PC,
                choke_gate=0,
                ac=ac,
            )
            guarded = console_result(
                nexen,
                args.nat,
                case,
                work,
                variant="production-route",
                target_pc=NEXT_PC,
                choke_gate=1,
                ac=ac,
            )
            event = compare_results(
                name,
                interpreted,
                guarded,
                compare_ac=True,
            )
            events.append(event)
            print(json.dumps(event, sort_keys=True), flush=True)

        route_event = probe_2a190_sparse_route(nexen, args.nat, case)
        events.append(route_event)
        print(json.dumps(route_event, sort_keys=True), flush=True)

    checks = [event for event in events if event.get("event") in ("case", "route_probe")]
    green = sum(event["result"] == "green" for event in checks)
    summary = {
        "event": "summary",
        "green": green,
        "red": len(checks) - green,
        "total": len(checks),
        "result": "green" if green == len(checks) else "red",
        "time": time.time(),
    }
    events.append(summary)
    print(json.dumps(summary, sort_keys=True), flush=True)
    args.output.write_text(
        "".join(json.dumps(event, sort_keys=True) + "\n" for event in events),
        encoding="utf-8",
    )
    return 0 if summary["result"] == "green" else 1


if __name__ == "__main__":
    raise SystemExit(main())
