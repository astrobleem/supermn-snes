#!/usr/bin/env python3
"""Organic-fixture MAME/Nexen differential for the signed spawn path.

The reference fixture is frozen at fetched 68K PC $024D28 in the last
diagnostic ROM before that address became native.  MAME then executes the
original $024D28 -> TRAP #1/$000466 -> $024D64 path and stops at $024CB6.
Nexen starts the new bank-$9E entry with the same architectural state.  A
retained lab derivative changes only $024D64's terminal JML target from the
real $99:839C continuation to the stable bank-$00 validation loop; the body
and all architectural effects through the seam remain the production bytes.

The comparison is exact for all D/A registers, CCR and interrupt mask, and
the mapped low 16 KiB of work RAM.  No synthetic return slot is involved.
This is bounded semantic and local-cycle evidence, not an FPS result.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import time
from dataclasses import dataclass
from pathlib import Path

import validate_24d98_hle as base
import validate_1f2e4_native as live


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CAPTURE_ROM = (
    ROOT
    / "build/playability-20260720/c172-optional-hot-diagnostic-v4/interp.sfc"
)
DEFAULT_STATE = (
    ROOT
    / "build/playability-20260720/"
    "gameplay-entry-initializers-production-v2-coldboot-immediate-v1/"
    "gameplay_detected.mss"
)
ENTRY_PC = 0x024D28
ENTRY_NATIVE = 0x9E9800
EXIT_PC = 0x024CB6
DEBUG_SPIN = 0x00E2CF
NATIVE_RETURN = base.NATIVE_RETURN
FULL_WORK_SIZE = 0x10000
MAPPED_WORK_SIZE = 0x4000
CAPTURE_BUTTONS = 0
LAB_PATCH_OFFSET = 0x2F1D15
LAB_PATCH_EXPECTED = bytes.fromhex("5c9c8399")
LAB_PATCH_REPLACEMENT = bytes.fromhex("5c5ad100")
TRACE_POINTS = {
    "entry_24d28": ENTRY_NATIVE,
    "trap1_dispatch": 0x00D3A1,
    "entry_466": 0x9E8000,
    "xlat_da_dispatch": 0x9DDA00,
    "entry_24d64": 0x9E9C00,
    "entry_24cb6": 0x99839C,
}


@dataclass
class LiveCase:
    regs: dict[str, int]
    sr: int
    work: bytes
    tick: int
    frame: int
    sa1_cycle: int
    capture_frames_advanced: int


def hook_params(rows: list[dict]) -> list[dict]:
    return [
        dict(row.get("params", {}))
        for row in rows
        if row.get("method") == "notifications/mesen/hookFired"
    ]


def build_capture_lab(parent: Path, target: Path) -> None:
    """Redirect only the final $99:839C JML to a stable validation loop."""

    rom = bytearray(parent.read_bytes())
    actual = bytes(
        rom[LAB_PATCH_OFFSET : LAB_PATCH_OFFSET + len(LAB_PATCH_EXPECTED)]
    )
    if actual != LAB_PATCH_EXPECTED:
        raise RuntimeError(
            f"unexpected $024D64 terminal JML at file ${LAB_PATCH_OFFSET:06X}: "
            f"expected {LAB_PATCH_EXPECTED.hex()}, got {actual.hex()}"
        )
    rom[
        LAB_PATCH_OFFSET : LAB_PATCH_OFFSET + len(LAB_PATCH_EXPECTED)
    ] = LAB_PATCH_REPLACEMENT
    target.write_bytes(rom)


def capture_organic_case(
    capture_rom: Path,
    state: Path,
    nexen: Path,
    port: int,
    stderr_log: Path,
) -> LiveCase:
    """Freeze the reference interpreter exactly at fetched PC $024D28."""

    with base.McpSession(
        rom=str(capture_rom),
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
        work = bytes(
            m.read_memory(base.SNES_SPACE, 0x400000, FULL_WORK_SIZE)
        )
        return LiveCase(
            regs=regs,
            sr=live.captured_sr(m),
            work=work,
            tick=live.work_be16(work, 0x1C56),
            frame=int(m.get_state().get("frameCount", 0)),
            sa1_cycle=int(m.get_cpu_state("Sa1")["cycleCount"]),
            capture_frames_advanced=frames_advanced,
        )


def load_organic_case(fixture_dir: Path) -> LiveCase:
    metadata_path = fixture_dir / "case-00.json"
    work_path = fixture_dir / "case-00.work.bin"
    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    work = work_path.read_bytes()
    if len(work) != FULL_WORK_SIZE:
        raise RuntimeError(
            f"retained fixture is {len(work)} bytes, expected {FULL_WORK_SIZE}: "
            f"{work_path}"
        )
    if hashlib.sha256(work).hexdigest() != metadata["work_sha256"]:
        raise RuntimeError(f"retained fixture hash mismatch: {work_path}")
    return LiveCase(
        regs={name: int(value) for name, value in metadata["regs"].items()},
        sr=int(metadata["sr"]),
        work=work,
        tick=int(metadata["tick"]),
        frame=int(metadata["frame"]),
        sa1_cycle=int(metadata["sa1_cycle"]),
        capture_frames_advanced=int(metadata["capture_frames_advanced"]),
    )


def mame_result(session: base.MameSession, case: LiveCase) -> base.Result:
    session.pause()
    entry_sp = case.regs["A7"] & 0xFFFFFF
    session.write_block(0xF00000, case.work)
    for name in base.REG_NAMES[:-1]:
        session.set_reg(name, case.regs[name])
    # Isolate the bounded call from unrelated VBLANK delivery in both oracles.
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
        exp_sp=entry_sp,
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


def prepare_nexen_case(
    m: base.McpSession,
    nat: Path,
    case: LiveCase,
    choke_gate: int,
) -> None:
    m.load_state(str(nat))
    m.pause()
    reg_blob = b"".join(base.le32(case.regs[name]) for name in base.REG_NAMES)
    m.write_memory(base.DP_SPACE, 0x00, reg_blob.hex())
    for offset in range(0, FULL_WORK_SIZE, 0x4000):
        m.write_memory(
            base.SNES_SPACE,
            0x400000 + offset,
            case.work[offset : offset + 0x4000].hex(),
        )
    live.park_snes_cpu(m)

    flags = case.sr & base.CCR_MASK
    live.write_u16(m, 0x6E, flags & 1)
    live.write_u16(m, 0x72, (flags >> 1) & 1)
    live.write_u16(m, 0x60, (flags >> 2) & 1)
    live.write_u16(m, 0x70, (flags >> 3) & 1)
    live.write_u16(m, 0xA2, (flags >> 4) & 1)
    live.write_u16(m, 0x7C, 7)
    live.write_u16(m, 0x4A, 0)
    live.write_u16(m, 0x4C, 0)
    live.write_u16(m, 0xA4, case.regs["A7"] & 0xFFFF)
    live.write_u16(m, 0xA6, (case.regs["A7"] >> 16) & 0xFFFF)
    live.write_u16(m, 0xA8, 1)
    live.write_u16(m, 0xAA, 0)
    live.write_u16(m, 0xAC, 0x7000)
    live.write_u16(m, 0x0702, 0)
    live.write_u16(m, 0x0704, 1)
    live.write_u16(m, 0x0710, 0)
    live.write_u16(m, 0x0712, 0)
    live.write_u16(m, 0x0714, 0)
    live.write_u16(m, 0x0716, 0)
    live.write_u16(m, 0x0718, 0xFFF8)
    live.write_u16(m, 0x071A, 1)
    live.write_u16(m, 0x0730, 0)
    live.write_u16(m, 0x073A, choke_gate)


def nexen_result(
    m: base.McpSession,
    nat: Path,
    case: LiveCase,
    choke_gate: int,
) -> base.Result:
    prepare_nexen_case(m, nat, case, choke_gate)
    # The retained NAT parks at NATIVE_RETURN.  Move away from that PC before
    # installing the stop hook; otherwise a delayed notification from the
    # base state's spin can satisfy run_until before this case executes.
    live.set_sa1_pc(m, ENTRY_NATIVE)
    stop_hook = m.add_exec_hook(NATIVE_RETURN, cpu_type="Sa1")
    m.drain_notifications(timeout=0.20)
    start_cycles = int(m.get_cpu_state("Sa1")["cycleCount"])
    try:
        hit = m.run_until(max_frames=120, hook_handle=stop_hook)
        m.pause()
    finally:
        m.remove_hook(stop_hook)
        m.drain_notifications(timeout=0.05)
    if (hit or {}).get("reason") != "hookFired":
        raise RuntimeError(
            f"Nexen did not reach the stable post-$024D64 lab seam, "
            f"choke={choke_gate}: hit={hit!r}"
        )
    end_cycles = int(m.get_cpu_state("Sa1")["cycleCount"])
    sr = (
        0x2000
        | ((live.read_u16(m, 0x7C) & 7) << 8)
        | live.captured_ccr(m)
    )
    result = base.Result(
        live.captured_regs(m),
        sr,
        bytes(
            m.read_memory(base.SNES_SPACE, 0x400000, MAPPED_WORK_SIZE)
        ),
        end_cycles - start_cycles,
    )
    return result


def prove_nexen_path(
    m: base.McpSession,
    nat: Path,
    case: LiveCase,
    choke_gate: int,
) -> dict[str, bool]:
    """Prove route points in isolated single-hook replays.

    Nexen run_until stops for *any* installed hook, not just the supplied
    handle.  Each proof therefore reloads the same fixture and installs only
    one hook.  The exact semantic replay is a separate run with only its final
    stable-loop hook.
    """

    targets = {
        ("entry_466" if choke_gate else "trap1_dispatch"): (
            TRACE_POINTS["entry_466"]
            if choke_gate
            else TRACE_POINTS["trap1_dispatch"]
        ),
        "entry_24d64": TRACE_POINTS["entry_24d64"],
    }
    result: dict[str, bool] = {}
    for name, address in targets.items():
        prepare_nexen_case(m, nat, case, choke_gate)
        live.set_sa1_pc(m, ENTRY_NATIVE)
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
    case: LiveCase,
    arcade: base.Result,
    console: base.Result,
    choke_gate: int,
    path_probes: dict[str, bool],
) -> dict:
    reg_mismatches = {
        name: {"mame": arcade.regs[name], "nexen": console.regs[name]}
        for name in base.REG_NAMES
        if arcade.regs[name] != console.regs[name]
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
    failed_probes = [name for name, fired in path_probes.items() if not fired]
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
        "fetch_choke_gate": choke_gate,
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
    parser.add_argument("--port", type=int, default=7828)
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
    lab_rom = fixture_dir / "capture-lab.sfc"
    build_capture_lab(args.rom, lab_rom)

    provenance = {
        "event": "provenance",
        "scope": (
            "organic live-fixture $024D28 -> TRAP #1/$000466 -> $024D64 "
            "MAME/Nexen differential through stable $024CB6 seam; all D/A "
            "registers, CCR/mask, mapped 16 KiB work RAM; not fps"
        ),
        "mame": "/snap/bin/mame 0.287",
        "nexen": str(args.nexen.resolve()),
        "nexen_sha256": base.sha256(args.nexen),
        "rom": str(args.rom.resolve()),
        "rom_sha256": base.sha256(args.rom),
        "nexen_lab_rom": str(lab_rom.resolve()),
        "nexen_lab_rom_sha256": base.sha256(lab_rom),
        "nexen_lab_patch": {
            "file_offset": f"{LAB_PATCH_OFFSET:06X}",
            "expected_production_bytes": LAB_PATCH_EXPECTED.hex(),
            "replacement_bytes": LAB_PATCH_REPLACEMENT.hex(),
            "meaning": (
                "only $024D64 terminal JML target changes from $99:839C to "
                "stable $00:D15A after every compared architectural effect"
            ),
        },
        "capture_rom": str(args.capture_rom.resolve()),
        "capture_rom_sha256": base.sha256(args.capture_rom),
        "capture_method": "PC_RING=1 fetched-PC debug freeze at $024D28",
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
            "meaning": "neutral continuation from retained gameplay state",
        },
        "irq_isolation": "entry interrupt mask forced to 7 in both oracles",
        "variants": [{"fetch_choke_gate": 0}, {"fetch_choke_gate": 1}],
        "time": time.time(),
    }
    events: list[dict] = [provenance]
    print(json.dumps(provenance, sort_keys=True), flush=True)

    if args.reuse_fixture is not None:
        case = load_organic_case(args.reuse_fixture)
    else:
        case = capture_organic_case(
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
        rom=str(lab_rom),
        mesen=str(args.nexen),
        cwd=ROOT,
        port=args.port + 1,
        boot_wait=8.0,
        socket_timeout=180.0,
        stderr_log=fixture_dir / "differential.nexen.stderr.log",
    ) as nexen:
        for choke_gate in (0, 1):
            path_probes = prove_nexen_path(
                nexen, args.nat, case, choke_gate
            )
            console = nexen_result(nexen, args.nat, case, choke_gate)
            event = compare(
                case, arcade, console, choke_gate, path_probes
            )
            events.append(event)
            print(json.dumps(event, sort_keys=True), flush=True)

    cases = [event for event in events if event.get("event") == "case"]
    green = sum(event["result"] == "green" for event in cases)
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
    args.output.write_text(
        "".join(json.dumps(event, sort_keys=True) + "\n" for event in events),
        encoding="utf-8",
    )
    return 0 if summary["result"] == "green" else 1


if __name__ == "__main__":
    raise SystemExit(main())
