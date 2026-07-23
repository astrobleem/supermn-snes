#!/usr/bin/env python3
"""Organic-fixture MAME/Nexen differential for native $01F2E4.

The fixture is captured at the real production execution hook $9D:C000 from
an uninterrupted retained gameplay state.  At that point the bank-$01 BSR
hook has committed the real return PC but has not yet pushed it; this is the
exact entry convention consumed by the generated native body.

MAME executes the original MC68000 routine with an equivalent synthetic JSR
return frame.  Nexen executes the native body with the $00FF return sentinel
used by the existing function-local harnesses.  The comparison is exact for
all D/A registers, CCR/mask, and mapped 16 KiB work RAM apart from the four
synthetic return bytes.  This is bounded semantic and local-cycle evidence,
not an FPS result.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import time
from dataclasses import dataclass
from pathlib import Path

import validate_d96_hle as base


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_ROM = ROOT / "build/interp.sfc"
DEFAULT_CAPTURE_ROM = (
    ROOT / "build/playability-20260720/2bda-fast-pc-ring-v1/interp.sfc"
)
DEFAULT_STATE = (
    ROOT
    / "build/playability-20260720/2a86e-native-uninterrupted-coldboot-ordering-v1/final.mss"
)
ENTRY_PC = 0x01F2E4
ENTRY_NATIVE = 0x9DC000
ORGANIC_RETURN_PC = 0x017644
NATIVE_RETURN = base.NATIVE_RETURN
DEBUG_SPIN = 0x00E2CF
SNES_PARK_PC = 0x7EF800
FULL_WORK_SIZE = 0x10000
MAPPED_WORK_SIZE = 0x4000
CAPTURE_BUTTONS = 0


@dataclass
class LiveCase:
    regs: dict[str, int]
    sr: int
    work: bytes
    tick: int
    frame: int
    sa1_cycle: int
    organic_return_pc: int
    capture_calls_seen: int
    rejected_returns: list[int]
    capture_frames_advanced: int


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def read_u16(m: base.McpSession, address: int) -> int:
    return int(m.read_u16(address, base.DP_SPACE))


def write_u16(m: base.McpSession, address: int, value: int) -> None:
    m.write_u16(address, value & 0xFFFF, base.DP_SPACE)


def captured_regs(m: base.McpSession) -> dict[str, int]:
    raw = bytes(m.read_memory(base.DP_SPACE, 0x00, 0x40))
    return {
        name: int.from_bytes(raw[index * 4 : index * 4 + 4], "little")
        for index, name in enumerate(base.REG_NAMES)
    }


def captured_ccr(m: base.McpSession) -> int:
    return (
        (1 if read_u16(m, 0x6E) else 0)
        | ((1 if read_u16(m, 0x72) else 0) << 1)
        | ((1 if read_u16(m, 0x60) else 0) << 2)
        | ((1 if read_u16(m, 0x70) else 0) << 3)
        | ((1 if read_u16(m, 0xA2) else 0) << 4)
    )


def captured_sr(m: base.McpSession) -> int:
    return 0x2000 | ((read_u16(m, 0x7C) & 7) << 8) | captured_ccr(m)


def work_be16(work: bytes, offset: int) -> int:
    offset &= 0xFFFF
    return (work[offset] << 8) | work[(offset + 1) & 0xFFFF]


def park_snes_cpu(m: base.McpSession) -> None:
    """Keep the unrelated 5A22 from touching injected BW-RAM state."""

    m.write_memory("snesWorkRam", SNES_PARK_PC & 0x1FFFF, "80fe")
    m.write_memory("snesMemory", 0x4200, "00")
    m.read_memory("snesMemory", 0x4210, 1)
    state = dict(m.get_cpu_state("Snes"))
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
    m.tool("set_cpu_state", {key: state[key] for key in allowed if key in state})


def set_sa1_pc(m: base.McpSession, address: int) -> None:
    state = dict(m.get_cpu_state("Sa1"))
    state.update(
        {
            "pc": address & 0xFFFF,
            "k": (address >> 16) & 0xFF,
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
    m.tool("set_cpu_state", {key: state[key] for key in allowed if key in state})


def run_to_hook(
    m: base.McpSession,
    hook: int,
    *,
    attempts: int = 8,
) -> tuple[dict, int]:
    """Run in bounded chunks because Nexen may cap one long run request."""

    hit: dict = {}
    frames_advanced = 0
    for _attempt in range(attempts):
        hit = m.run_until(max_frames=120, hook_handle=hook)
        frames_advanced += int((hit or {}).get("framesAdvanced", 0))
        if (hit or {}).get("reason") == "hookFired":
            break
        if (hit or {}).get("reason") != "maxFrames":
            break
    return hit, frames_advanced


def probe_production_dispatch(
    rom: Path,
    state: Path,
    nexen: Path,
    port: int,
    stderr_log: Path,
) -> dict:
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
        # The retained checkpoint initially contains the last latched $8100
        # mailbox value, but the attribution/profile continuation used
        # drive_gameplay=false and did not hold controller input.  Reproduce
        # that neutral external transport explicitly.
        m.tool(
            "set_input",
            {"port": 0, "buttons": CAPTURE_BUTTONS, "hold": True},
        )
        hook = m.add_exec_hook(ENTRY_NATIVE, cpu_type="Sa1")
        m.drain_notifications(timeout=0.05)
        hit, frames_advanced = run_to_hook(m, hook)
        m.pause()
        m.remove_hook(hook)
        if (hit or {}).get("reason") != "hookFired":
            raise RuntimeError(
                f"production run did not execute ${ENTRY_NATIVE:06X} after "
                f"{frames_advanced} video frames: {hit!r}"
            )
        cpu = m.get_cpu_state("Sa1")
        continuation = read_u16(m, 0x40) | ((read_u16(m, 0x42) & 0xFF) << 16)
        return {
            "event": "production_dispatch_probe",
            "native_entry": f"{ENTRY_NATIVE:06X}",
            "hook_fired": True,
            "frames_advanced": frames_advanced,
            "paused_sa1_pc": f"{((int(cpu.get('k', 0)) << 16) | int(cpu.get('pc', 0))):06X}",
            "paused_68k_continuation": f"{continuation:06X}",
            "note": (
                "execution-hook notification proves production dispatch; "
                "paused state may be later than the entry instruction"
            ),
        }


def capture_organic_case(
    capture_rom: Path,
    state: Path,
    nexen: Path,
    port: int,
    stderr_log: Path,
) -> LiveCase:
    """Freeze the reference interpreter exactly at fetched 68K PC $01F2E4."""

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
        write_u16(m, 0x0710, ENTRY_PC & 0xFFFF)
        write_u16(m, 0x0712, 0)
        write_u16(m, 0x0714, 0)
        write_u16(m, 0x0716, (ENTRY_PC >> 16) & 0xFF)
        write_u16(m, 0x0718, 0xFFF8)
        write_u16(m, 0x0730, 0x5A5A)
        hook = m.add_exec_hook(DEBUG_SPIN, cpu_type="Sa1")
        m.drain_notifications(timeout=0.05)
        rejected_returns: list[int] = []
        frames_advanced = 0
        regs: dict[str, int] | None = None
        work: bytes | None = None
        return_pc = -1
        calls_seen = 0
        try:
            for calls_seen in range(1, 17):
                if calls_seen > 1:
                    # Persistent-freeze magic leaves $0710 armed across the
                    # release tail.  Clear the marker and pulse release so the
                    # current call executes before waiting for the next one.
                    write_u16(m, 0x0712, 0)
                    write_u16(m, 0x0714, 1)
                    # Cross one real video-frame boundary before reusing the
                    # same execution hook.  Otherwise run_until can consume
                    # the just-released df_spin notification as though it
                    # were the next call.  If the next call freezes within
                    # this barrier, $0712/$40/$42 identify it exactly.
                    m.run_frames(1)
                    m.pause()
                    frames_advanced += 1
                    m.drain_notifications(timeout=0.02)
                pre_pc = read_u16(m, 0x40) | (
                    (read_u16(m, 0x42) & 0xFF) << 16
                )
                if read_u16(m, 0x0712) and pre_pc == ENTRY_PC:
                    hit, advanced = {"reason": "hookFired", "framesAdvanced": 0}, 0
                else:
                    hit, advanced = run_to_hook(m, hook)
                frames_advanced += advanced
                m.pause()
                observed_pc = read_u16(m, 0x40) | (
                    (read_u16(m, 0x42) & 0xFF) << 16
                )
                if (
                    (hit or {}).get("reason") != "hookFired"
                    or not read_u16(m, 0x0712)
                    or observed_pc != ENTRY_PC
                ):
                    raise RuntimeError(
                        f"reference interpreter did not freeze at ${ENTRY_PC:06X} "
                        f"after {frames_advanced} video frames: hit={hit!r}, "
                        f"marker={read_u16(m, 0x0712)}, pc=${observed_pc:06X}"
                    )
                regs = captured_regs(m)
                work = bytes(
                    m.read_memory(base.SNES_SPACE, 0x400000, FULL_WORK_SIZE)
                )
                stack_offset = regs["A7"] & 0xFFFF
                return_pc = (
                    int.from_bytes(work[stack_offset : stack_offset + 4], "big")
                    & 0xFFFFFF
                )
                if return_pc == ORGANIC_RETURN_PC:
                    break
                rejected_returns.append(return_pc)
        finally:
            m.remove_hook(hook)
        if regs is None or work is None or return_pc != ORGANIC_RETURN_PC:
            rendered = ", ".join(f"${value:06X}" for value in rejected_returns)
            raise RuntimeError(
                f"no ${ENTRY_PC:06X} call returned to ${ORGANIC_RETURN_PC:06X}; "
                f"observed [{rendered}]"
            )
        return LiveCase(
            regs=regs,
            sr=captured_sr(m),
            work=work,
            tick=work_be16(work, 0x1C56),
            frame=int(m.get_state().get("frameCount", 0)),
            sa1_cycle=int(m.get_cpu_state("Sa1")["cycleCount"]),
            organic_return_pc=return_pc,
            capture_calls_seen=calls_seen,
            rejected_returns=rejected_returns,
            capture_frames_advanced=frames_advanced,
        )


def mame_result(session: base.MameSession, case: LiveCase) -> base.Result:
    session.pause()
    entry_sp = case.regs["A7"] & 0xFFFFFF
    expected_sp = (entry_sp + 4) & 0xFFFFFF
    session.write_block(0xF00000, case.work[:MAPPED_WORK_SIZE])
    for name in base.REG_NAMES[:-1]:
        session.set_reg(name, case.regs[name])
    # Mask unrelated organic VBLANK delivery for this bounded injection.  The
    # same mask is supplied to Nexen and the result mask remains compared.
    session.set_reg("SR", case.sr | 0x0700)
    session.set_reg("USP", entry_sp)
    session.set_reg("SP", entry_sp)
    session.set_reg("PC", ENTRY_PC)
    captured = session.cmd(
        "capture_at_pc",
        pc=case.organic_return_pc,
        addr=0xF00000,
        len=MAPPED_WORK_SIZE,
        nth=1,
        exp_sp=expected_sp,
        maxFrames=120,
        timeout=120,
    )
    if not captured.get("registers"):
        raise RuntimeError(f"MAME did not return from ${ENTRY_PC:06X}: {captured!r}")
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
    m: base.McpSession,
    nat: Path,
    case: LiveCase,
    choke_gate: int,
) -> base.Result:
    m.load_state(str(nat))
    m.pause()
    native_regs = dict(case.regs)
    native_regs["A7"] = (native_regs["A7"] + 4) & 0xFFFFFFFF
    reg_blob = b"".join(base.le32(native_regs[name]) for name in base.REG_NAMES)
    m.write_memory(base.DP_SPACE, 0x00, reg_blob.hex())
    for offset in range(0, len(case.work), 0x4000):
        m.write_memory(
            base.SNES_SPACE,
            0x400000 + offset,
            case.work[offset : offset + 0x4000].hex(),
        )
    park_snes_cpu(m)

    flags = case.sr & base.CCR_MASK
    write_u16(m, 0x6E, flags & 1)
    write_u16(m, 0x72, (flags >> 1) & 1)
    write_u16(m, 0x60, (flags >> 2) & 1)
    write_u16(m, 0x70, (flags >> 3) & 1)
    write_u16(m, 0xA2, (flags >> 4) & 1)
    write_u16(m, 0x7C, 7)
    write_u16(m, 0x40, NATIVE_RETURN & 0xFFFF)
    write_u16(m, 0x42, 0x00FF)
    write_u16(m, 0x4A, 0)
    write_u16(m, 0x4C, 0)
    write_u16(m, 0xA4, native_regs["A7"] & 0xFFFF)
    write_u16(m, 0xA6, (native_regs["A7"] >> 16) & 0xFFFF)
    write_u16(m, 0xA8, 1)
    write_u16(m, 0xAA, 0)
    write_u16(m, 0xAC, 0x7000)
    write_u16(m, 0x0702, 0)
    write_u16(m, 0x0704, 1)
    write_u16(m, 0x0718, 0xFFF8)
    write_u16(m, 0x071A, 1)
    write_u16(m, 0x073A, choke_gate)

    hook = m.add_exec_hook(NATIVE_RETURN, cpu_type="Sa1")
    m.drain_notifications(timeout=0.05)
    set_sa1_pc(m, ENTRY_NATIVE)
    start_cycles = int(m.get_cpu_state("Sa1")["cycleCount"])
    hit = m.run_until(max_frames=120, hook_handle=hook)
    m.pause()
    m.remove_hook(hook)
    if (hit or {}).get("reason") != "hookFired":
        raise RuntimeError(
            f"Nexen did not return from ${ENTRY_NATIVE:06X}, "
            f"choke={choke_gate}: {hit!r}"
        )
    end_cycles = int(m.get_cpu_state("Sa1")["cycleCount"])
    sr = 0x2000 | ((read_u16(m, 0x7C) & 7) << 8) | captured_ccr(m)
    return base.Result(
        captured_regs(m),
        sr,
        bytes(m.read_memory(base.SNES_SPACE, 0x400000, MAPPED_WORK_SIZE)),
        end_cycles - start_cycles,
    )


def compare(
    case: LiveCase,
    arcade: base.Result,
    console: base.Result,
    choke_gate: int,
) -> dict:
    reg_mismatches = {
        name: {"mame": arcade.regs[name], "nexen": console.regs[name]}
        for name in base.REG_NAMES
        if arcade.regs[name] != console.regs[name]
    }
    return_slot = case.regs["A7"] & 0xFFFF
    excluded = {(return_slot + offset) & 0xFFFF for offset in range(4)}
    work_mismatches = [
        offset
        for offset, (left, right) in enumerate(zip(arcade.work, console.work))
        if offset not in excluded and left != right
    ]
    ccr_mismatch = (arcade.sr & base.CCR_MASK) != (
        console.sr & base.CCR_MASK
    )
    mask_mismatch = ((arcade.sr >> 8) & 7) != ((console.sr >> 8) & 7)
    return {
        "event": "case",
        "case": f"organic-tick-{case.tick}",
        "fetch_choke_gate": choke_gate,
        "result": (
            "green"
            if not reg_mismatches
            and not ccr_mismatch
            and not mask_mismatch
            and not work_mismatches
            else "red"
        ),
        "reg_mismatches": reg_mismatches,
        "mame_ccr": arcade.sr & base.CCR_MASK,
        "nexen_ccr": console.sr & base.CCR_MASK,
        "mame_mask": (arcade.sr >> 8) & 7,
        "nexen_mask": (console.sr >> 8) & 7,
        "synthetic_return_excluded": [
            f"F0{offset:04X}" for offset in sorted(excluded)
        ],
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
        "nexen_cycles": console.cycles,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--rom", type=Path, default=DEFAULT_ROM)
    parser.add_argument("--capture-rom", type=Path, default=DEFAULT_CAPTURE_ROM)
    parser.add_argument("--state", type=Path, default=DEFAULT_STATE)
    parser.add_argument("--nexen", type=Path, default=base.DEFAULT_NEXEN)
    parser.add_argument("--nat", type=Path, default=base.DEFAULT_NAT)
    parser.add_argument("--port", type=int, default=7770)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    for path in (args.rom, args.capture_rom, args.state, args.nexen, args.nat):
        if not path.is_file():
            parser.error(f"missing required input: {path}")
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
            "organic live-fixture function-local $01F2E4 MAME/Nexen "
            "differential; all D/A registers, CCR/mask, mapped 16 KiB work "
            "RAM; not fps"
        ),
        "mame": "/snap/bin/mame 0.287",
        "nexen": str(args.nexen.resolve()),
        "nexen_sha256": sha256(args.nexen),
        "rom": str(args.rom.resolve()),
        "rom_sha256": sha256(args.rom),
        "capture_rom": str(args.capture_rom.resolve()),
        "capture_rom_sha256": sha256(args.capture_rom),
        "capture_method": (
            "PC_RING=1 lab debug-freeze at fetched 68K PC, conditional on "
            "the real $017644 JSR return"
        ),
        "state": str(args.state.resolve()),
        "state_sha256": sha256(args.state),
        "nat": str(args.nat.resolve()),
        "nat_sha256": sha256(args.nat),
        "entry_pc": f"{ENTRY_PC:06X}",
        "entry_native": f"{ENTRY_NATIVE:06X}",
        "organic_capture_hook": f"{ENTRY_NATIVE:06X}",
        "organic_capture_input": {
            "port": 0,
            "buttons": CAPTURE_BUTTONS,
            "meaning": (
                "neutral continuation (profile drive_gameplay=false); "
                "checkpoint begins with previously latched mailbox $8100"
            ),
        },
        "mame_irq_isolation": "entry interrupt mask forced to 7 in both oracles",
        "variants": [{"fetch_choke_gate": 0}, {"fetch_choke_gate": 1}],
        "time": time.time(),
    }
    events: list[dict] = [provenance]
    print(json.dumps(provenance, sort_keys=True), flush=True)

    dispatch_probe = probe_production_dispatch(
        args.rom,
        args.state,
        args.nexen,
        args.port,
        fixture_dir / "dispatch-probe.nexen.stderr.log",
    )
    events.append(dispatch_probe)
    print(json.dumps(dispatch_probe, sort_keys=True), flush=True)

    case = capture_organic_case(
        args.capture_rom,
        args.state,
        args.nexen,
        args.port + 1,
        fixture_dir / "capture.nexen.stderr.log",
    )
    fixture = {
        "event": "fixture",
        "name": f"organic-tick-{case.tick}",
        "tick": case.tick,
        "frame": case.frame,
        "sa1_cycle": case.sa1_cycle,
        "organic_return_pc": f"{case.organic_return_pc:06X}",
        "mame_entry_sp": f"{case.regs['A7'] & 0xFFFFFF:06X}",
        "native_pre_jsr_sp": f"{((case.regs['A7'] + 4) & 0xFFFFFF):06X}",
        "capture_calls_seen": case.capture_calls_seen,
        "capture_rejected_returns": [
            f"{value:06X}" for value in case.rejected_returns
        ],
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
        mame_event = {
            "event": "mame_case",
            "case": f"organic-tick-{case.tick}",
            "oracle_return_pc": f"{case.organic_return_pc:06X}",
        }
        events.append(mame_event)
        print(json.dumps(mame_event, sort_keys=True), flush=True)
    finally:
        mame.stop()

    with base.McpSession(
        rom=str(args.rom),
        mesen=str(args.nexen),
        cwd=ROOT,
        port=args.port + 2,
        boot_wait=8.0,
        socket_timeout=180.0,
        stderr_log=fixture_dir / "differential.nexen.stderr.log",
    ) as nexen:
        for choke_gate in (0, 1):
            console = nexen_result(nexen, args.nat, case, choke_gate)
            event = compare(case, arcade, console, choke_gate)
            events.append(event)
            print(json.dumps(event, sort_keys=True), flush=True)

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
    events.append(summary)
    print(json.dumps(summary, sort_keys=True), flush=True)
    args.output.write_text(
        "".join(json.dumps(event, sort_keys=True) + "\n" for event in events),
        encoding="utf-8",
    )
    return 0 if summary["result"] == "green" else 1


if __name__ == "__main__":
    raise SystemExit(main())
