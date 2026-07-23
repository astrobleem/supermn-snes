#!/usr/bin/env python3
"""Organic-fixture differential for the $01D51A spawn initializer chain.

The reference fixture is frozen at fetched 68K PC $01D51A in the last
diagnostic ROM before that coroutine entry became native.  MAME executes the
original initializer through the allocator/table helper and stops at the
TRAP #5 handler entry, $000532.  That post-exception seam avoids MAME's opcode
prefetch tap observing the immediately preceding $01D5E8 store before it
retires.  Nexen replays the same state through both the gate-off interpreter
path and the bank-$9E native path.

The comparison is exact for all D/A registers, CCR and interrupt mask, and the
mapped low 16 KiB of work RAM.  This is bounded semantic and local-cycle
evidence, not an FPS result.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import time
from pathlib import Path

import validate_spawn_spike_native as spike
import validate_1f2e4_native as live


ROOT = Path(__file__).resolve().parents[1]
base = spike.base
DEFAULT_CAPTURE_ROM = spike.DEFAULT_CAPTURE_ROM
DEFAULT_STATE = spike.DEFAULT_STATE
ENTRY_PC = 0x01D51A
ENTRY_NATIVE = 0x9E9000
EXIT_PC = 0x000532
INEXT = 0x00D128
DEBUG_SPIN = spike.DEBUG_SPIN
FULL_WORK_SIZE = spike.FULL_WORK_SIZE
MAPPED_WORK_SIZE = spike.MAPPED_WORK_SIZE
CAPTURE_BUTTONS = 130
TRACE_POINTS = {
    "entry_1f2e4": 0x9DC000,
    "entry_1f4b0t": 0x9EA000,
    "entry_1d53a": 0x9E90F2,
    "entry_1d54c": 0x9E9175,
}


def capture_case(
    capture_rom: Path,
    state: Path,
    nexen: Path,
    port: int,
    stderr_log: Path,
) -> spike.LiveCase:
    """Use the shared fetched-PC freezer with this entry and input stream."""

    old_pc = spike.ENTRY_PC
    old_buttons = spike.CAPTURE_BUTTONS
    try:
        spike.ENTRY_PC = ENTRY_PC
        spike.CAPTURE_BUTTONS = CAPTURE_BUTTONS
        return spike.capture_organic_case(
            capture_rom, state, nexen, port, stderr_log
        )
    finally:
        spike.ENTRY_PC = old_pc
        spike.CAPTURE_BUTTONS = old_buttons


def mame_result(
    session: base.MameSession, case: spike.LiveCase
) -> base.Result:
    session.pause()
    entry_sp = case.regs["A7"] & 0xFFFFFF
    session.write_block(0xF00000, case.work)
    for name in base.REG_NAMES[:-1]:
        session.set_reg(name, case.regs[name])
    session.set_reg("SR", case.sr | 0x0700)
    session.set_reg("USP", entry_sp)
    session.set_reg("SP", entry_sp)
    session.set_reg("PC", ENTRY_PC)
    captured = session.cmd(
        "capture_at_pc",
        pc=EXIT_PC,
        addr=0xF00000,
        len=MAPPED_WORK_SIZE,
        nth=1,
        maxFrames=120,
        timeout=120,
    )
    if not captured.get("registers"):
        raise RuntimeError(
            f"MAME did not reach ${EXIT_PC:06X} from ${ENTRY_PC:06X}: "
            f"{captured!r}"
        )
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


def prepare_case(
    m: base.McpSession,
    nat: Path,
    case: spike.LiveCase,
    *,
    native: bool,
) -> None:
    spike.prepare_nexen_case(m, nat, case, choke_gate=1 if native else 0)
    live.write_u16(m, 0x071A, 1 if native else 0)
    live.write_u16(m, 0x0710, EXIT_PC & 0xFFFF)
    live.write_u16(m, 0x0712, 0)
    live.write_u16(m, 0x0714, 0)
    live.write_u16(m, 0x0716, (EXIT_PC >> 16) & 0xFF)
    live.write_u16(m, 0x0718, 0xFFF8)
    live.write_u16(m, 0x0730, 0)
    if native:
        live.set_sa1_pc(m, ENTRY_NATIVE)
    else:
        live.write_u16(m, 0x40, ENTRY_PC & 0xFFFF)
        live.write_u16(m, 0x42, (ENTRY_PC >> 16) & 0xFF)
        live.set_sa1_pc(m, INEXT)


def nexen_result(
    m: base.McpSession,
    nat: Path,
    case: spike.LiveCase,
    *,
    native: bool,
) -> base.Result:
    prepare_case(m, nat, case, native=native)
    stop_hook = m.add_exec_hook(DEBUG_SPIN, cpu_type="Sa1")
    m.drain_notifications(timeout=0.20)
    start_cycles = int(m.get_cpu_state("Sa1")["cycleCount"])
    try:
        hit = m.run_until(max_frames=120, hook_handle=stop_hook)
        m.pause()
    finally:
        m.remove_hook(stop_hook)
        m.drain_notifications(timeout=0.05)
    observed_pc = live.read_u16(m, 0x40) | (
        (live.read_u16(m, 0x42) & 0xFF) << 16
    )
    if (
        (hit or {}).get("reason") != "hookFired"
        or not live.read_u16(m, 0x0712)
        or observed_pc != EXIT_PC
    ):
        raise RuntimeError(
            f"Nexen did not freeze at ${EXIT_PC:06X}, native={native}: "
            f"hit={hit!r}, marker={live.read_u16(m, 0x0712)}, "
            f"pc=${observed_pc:06X}"
        )
    end_cycles = int(m.get_cpu_state("Sa1")["cycleCount"])
    sr = (
        0x2000
        | ((live.read_u16(m, 0x7C) & 7) << 8)
        | live.captured_ccr(m)
    )
    return base.Result(
        live.captured_regs(m),
        sr,
        bytes(m.read_memory(base.SNES_SPACE, 0x400000, MAPPED_WORK_SIZE)),
        end_cycles - start_cycles,
    )


def prove_native_path(
    m: base.McpSession,
    nat: Path,
    case: spike.LiveCase,
) -> dict[str, bool]:
    """Replay once per target because Nexen stops on any installed hook."""

    result: dict[str, bool] = {}
    for name, address in TRACE_POINTS.items():
        prepare_case(m, nat, case, native=True)
        hook = m.add_exec_hook(address, cpu_type="Sa1")
        m.drain_notifications(timeout=0.20)
        try:
            hit = m.run_until(max_frames=120, hook_handle=hook)
            m.pause()
        finally:
            m.remove_hook(hook)
            m.drain_notifications(timeout=0.05)
        result[name] = (hit or {}).get("reason") == "hookFired"
    return result


def compare(
    name: str,
    case: spike.LiveCase,
    arcade: base.Result,
    console: base.Result,
    path_probes: dict[str, bool],
) -> dict:
    reg_mismatches = {
        reg: {"mame": arcade.regs[reg], "nexen": console.regs[reg]}
        for reg in base.REG_NAMES
        if arcade.regs[reg] != console.regs[reg]
    }
    work_mismatches = [
        offset
        for offset, (left, right) in enumerate(zip(arcade.work, console.work))
        if left != right
    ]
    ccr_mismatch = (arcade.sr & base.CCR_MASK) != (
        console.sr & base.CCR_MASK
    )
    mask_mismatch = ((arcade.sr >> 8) & 7) != ((console.sr >> 8) & 7)
    failed_probes = [key for key, fired in path_probes.items() if not fired]
    green = not (
        reg_mismatches
        or work_mismatches
        or ccr_mismatch
        or mask_mismatch
        or failed_probes
    )
    return {
        "event": "case",
        "case": f"organic-tick-{case.tick}",
        "variant": name,
        "result": "green" if green else "red",
        "reg_mismatches": reg_mismatches,
        "mame_ccr": arcade.sr & base.CCR_MASK,
        "nexen_ccr": console.sr & base.CCR_MASK,
        "mame_mask": (arcade.sr >> 8) & 7,
        "nexen_mask": (console.sr >> 8) & 7,
        "work_mismatch_count": len(work_mismatches),
        "work_mismatch_first": [
            f"F0{offset:04X}" for offset in work_mismatches[:24]
        ],
        "work_mismatch_values": [
            {
                "address": f"F0{offset:04X}",
                "mame": arcade.work[offset],
                "nexen": console.work[offset],
            }
            for offset in work_mismatches[:24]
        ],
        "path_probes": path_probes,
        "failed_path_probes": failed_probes,
        "nexen_cycles": console.cycles,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--rom", type=Path, default=base.DEFAULT_ROM)
    parser.add_argument("--capture-rom", type=Path, default=DEFAULT_CAPTURE_ROM)
    parser.add_argument("--state", type=Path, default=DEFAULT_STATE)
    parser.add_argument("--nexen", type=Path, default=base.DEFAULT_NEXEN)
    parser.add_argument("--nat", type=Path, default=base.DEFAULT_NAT)
    parser.add_argument(
        "--reuse-fixture",
        type=Path,
        help="retained directory containing case-00.json/work.bin",
    )
    parser.add_argument("--port", type=int, default=7832)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    for path in (args.rom, args.capture_rom, args.state, args.nexen, args.nat):
        if not path.is_file():
            parser.error(f"missing required input: {path}")
    if args.reuse_fixture is not None:
        for name in ("case-00.json", "case-00.work.bin"):
            path = args.reuse_fixture / name
            if not path.is_file():
                parser.error(f"missing retained fixture input: {path}")
    if args.output.exists():
        parser.error(f"output already exists: {args.output}")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    fixture_dir = args.output.parent / f"{args.output.stem}-fixtures"
    if fixture_dir.exists():
        parser.error(f"fixture directory already exists: {fixture_dir}")
    fixture_dir.mkdir()

    provenance = {
        "event": "provenance",
        "scope": (
            "organic live-fixture $01D51A -> $01F2E4/$01F4B0 -> "
            "$01D53A/$01D54C differential through the committed TRAP-$5 "
            "handler-entry $000532 seam; all D/A registers, CCR/mask, mapped 16 KiB "
            "work RAM; not fps"
        ),
        "mame": "/snap/bin/mame 0.287",
        "nexen": str(args.nexen.resolve()),
        "nexen_sha256": base.sha256(args.nexen),
        "rom": str(args.rom.resolve()),
        "rom_sha256": base.sha256(args.rom),
        "capture_rom": str(args.capture_rom.resolve()),
        "capture_rom_sha256": base.sha256(args.capture_rom),
        "capture_method": "PC_RING=1 fetched-PC debug freeze at $01D51A",
        "retained_fixture": (
            {
                "directory": str(args.reuse_fixture.resolve()),
                "metadata_sha256": base.sha256(
                    args.reuse_fixture / "case-00.json"
                ),
                "work_sha256": base.sha256(
                    args.reuse_fixture / "case-00.work.bin"
                ),
            }
            if args.reuse_fixture is not None
            else None
        ),
        "state": str(args.state.resolve()),
        "state_sha256": base.sha256(args.state),
        "nat": str(args.nat.resolve()),
        "nat_sha256": base.sha256(args.nat),
        "entry_pc": f"{ENTRY_PC:06X}",
        "entry_native": f"{ENTRY_NATIVE:06X}",
        "exit_pc": f"{EXIT_PC:06X}",
        "capture_input": {
            "port": 0,
            "buttons": CAPTURE_BUTTONS,
            "meaning": "same real gameplay input used by the spike profile",
        },
        "irq_isolation": "entry interrupt mask forced to 7 in both oracles",
        "variants": ["escape-gate-off-interpreter", "native-chain"],
        "time": time.time(),
    }
    events: list[dict] = [provenance]
    print(json.dumps(provenance, sort_keys=True), flush=True)

    if args.reuse_fixture is not None:
        case = spike.load_organic_case(args.reuse_fixture)
    else:
        case = capture_case(
            args.capture_rom,
            args.state,
            args.nexen,
            args.port,
            fixture_dir / "capture.nexen.stderr.log",
        )
    fixture = {
        "event": "fixture",
        "name": f"organic-tick-{case.tick}",
        "tick": case.tick,
        "frame": case.frame,
        "sa1_cycle": case.sa1_cycle,
        "entry_sp": f"{case.regs['A7'] & 0xFFFFFF:06X}",
        "capture_frames_advanced": case.capture_frames_advanced,
        "sr": case.sr,
        "regs": case.regs,
        "work_sha256": hashlib.sha256(case.work).hexdigest(),
        "reference_debug_freeze_marker": True,
    }
    events.append(fixture)
    print(json.dumps(fixture, sort_keys=True), flush=True)
    (fixture_dir / "case-00.work.bin").write_bytes(case.work)
    (fixture_dir / "case-00.json").write_text(
        json.dumps(fixture, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )

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
        event = {
            "event": "mame_case",
            "case": f"organic-tick-{case.tick}",
            "oracle_exit_pc": f"{EXIT_PC:06X}",
        }
        events.append(event)
        print(json.dumps(event, sort_keys=True), flush=True)
    finally:
        mame.stop()

    with base.McpSession(
        rom=str(args.rom),
        mesen=str(args.nexen),
        cwd=ROOT,
        port=args.port + 1,
        boot_wait=8.0,
        socket_timeout=180.0,
        stderr_log=fixture_dir / "differential.nexen.stderr.log",
    ) as nexen:
        control = nexen_result(nexen, args.nat, case, native=False)
        event = compare(
            "escape-gate-off-interpreter", case, arcade, control, {}
        )
        events.append(event)
        print(json.dumps(event, sort_keys=True), flush=True)

        path_probes = prove_native_path(nexen, args.nat, case)
        native = nexen_result(nexen, args.nat, case, native=True)
        event = compare("native-chain", case, arcade, native, path_probes)
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
    args.output.write_text(
        "".join(json.dumps(event, sort_keys=True) + "\n" for event in events),
        encoding="utf-8",
    )
    return 0 if summary["result"] == "green" else 1


if __name__ == "__main__":
    raise SystemExit(main())
