#!/usr/bin/env python3
"""Live-fixture MAME/Nexen differential for the native $02A190 task root.

Capture real production inputs at the bank-$95 native entry, run the original
MC68000 code in MAME through the hot BSR to the common $02A194 return PC, and
compare against the zero-byte post-BSR seam in the coroutine-convention body.
Each fixture runs with nested xlat both disabled (so the dynamic $00111A call
is interpreted) and enabled (the production composition).

The gate is exact across every D/A register, CCR X/N/Z/V/C, and the complete
mapped 16 KiB work-RAM window, including all BSR/JSR stack residue.  This is
bounded function-semantic and local-cycle evidence, not an FPS measurement.
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
DEFAULT_ROM = ROOT / "build" / "interp.sfc"
DEFAULT_STATE = (
    ROOT
    / "build/playability-20260720/111a-table-active-cold-boot-v1/final.mss"
)
ENTRY_PC = 0x02A190
POST_BSR_PC = 0x02A194
EXIT_IDLE_PC = 0x02A18E
EXIT_ACTIVE_PC = 0x02A19A
ENTRY_NATIVE = 0x95B660
POST_BSR_NATIVE = 0x95B68A
DEBUG_SPIN = 0x00E2CF
SNES_PARK_PC = 0x7EF800
MAPPED_WORK_SIZE = 0x4000


@dataclass
class LiveCase:
    name: str
    regs: dict[str, int]
    sr: int
    work: bytes
    tick: int
    state_byte: int
    exit_pc: int


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


def captured_ccr(m: base.McpSession) -> int:
    return (
        (1 if read_u16(m, 0x6E) else 0)
        | ((1 if read_u16(m, 0x72) else 0) << 1)
        | ((1 if read_u16(m, 0x60) else 0) << 2)
        | ((1 if read_u16(m, 0x70) else 0) << 3)
        | ((1 if read_u16(m, 0xA2) else 0) << 4)
    )


def captured_regs(m: base.McpSession) -> dict[str, int]:
    raw = bytes(m.read_memory(base.DP_SPACE, 0x00, 0x40))
    return {
        name: int.from_bytes(raw[index * 4 : index * 4 + 4], "little")
        for index, name in enumerate(base.REG_NAMES)
    }


def capture_live_cases(
    rom: Path,
    state: Path,
    nexen: Path,
    port: int,
    count: int,
    stderr_log: Path,
) -> list[LiveCase]:
    cases: list[LiveCase] = []
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
        hook = m.add_exec_hook(ENTRY_NATIVE, cpu_type="Sa1")
        m.drain_notifications(timeout=0.05)
        previous_cycles = -1
        try:
            for index in range(count):
                hit = m.run_until(max_frames=180, hook_handle=hook)
                if (hit or {}).get("reason") != "hookFired":
                    raise RuntimeError(
                        f"production capture {index} did not reach native entry: {hit!r}"
                    )
                m.pause()
                cycles = int(m.get_cpu_state("Sa1")["cycleCount"])
                if cycles <= previous_cycles:
                    raise RuntimeError("native-entry capture did not advance")
                previous_cycles = cycles
                regs = captured_regs(m)
                work = bytes(
                    m.read_memory(base.SNES_SPACE, 0x400000, 0x10000)
                )
                a4 = regs["A4"] & 0xFFFFFF
                if (a4 >> 16) != 0xF0:
                    raise RuntimeError(
                        f"capture {index} has non-work-RAM A4 ${a4:06X}"
                    )
                state_byte = work[((a4 & 0xFFFF) + 0x16) & 0xFFFF]
                if state_byte != 0:
                    raise RuntimeError(
                        f"capture {index} dispatch state is {state_byte}, expected 0"
                    )
                tick_raw = work[0x1C56:0x1C58]
                tick = int.from_bytes(tick_raw, "big")
                active_offset = ((a4 & 0xFFFF) + 0x1A) & 0xFFFF
                active_word = int.from_bytes(
                    work[active_offset : active_offset + 2], "big"
                )
                exit_pc = EXIT_ACTIVE_PC if active_word else EXIT_IDLE_PC
                cases.append(
                    LiveCase(
                        name=f"live-{index:02d}-tick-{tick}",
                        regs=regs,
                        sr=0x2700 | captured_ccr(m),
                        work=work,
                        tick=tick,
                        state_byte=state_byte,
                        exit_pc=exit_pc,
                    )
                )
        finally:
            m.remove_hook(hook)
    return cases


def mame_result(session: base.MameSession, case: LiveCase) -> base.Result:
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
        pc=POST_BSR_PC,
        addr=0xF00000,
        len=MAPPED_WORK_SIZE,
        nth=1,
        exp_sp=case.regs["A7"] & 0xFFFFFF,
        maxFrames=60,
        timeout=60,
    )
    if not captured.get("registers"):
        raise RuntimeError(
            f"MAME did not reach post-BSR PC ${POST_BSR_PC:06X} "
            f"for {case.name}: {captured!r}"
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


def park_snes_cpu(m: base.McpSession) -> None:
    """Keep the unrelated 5A22 from writing shared BW-RAM in this local lab."""

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


def nexen_result(
    m: base.McpSession,
    nat: Path,
    case: LiveCase,
    *,
    xlat_gate: int,
) -> base.Result:
    m.load_state(str(nat))
    m.pause()

    reg_blob = b"".join(base.le32(case.regs[name]) for name in base.REG_NAMES)
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
    write_u16(m, 0x40, ENTRY_PC & 0xFFFF)
    write_u16(m, 0x42, (ENTRY_PC >> 16) & 0xFF)
    write_u16(m, 0x4A, 0)
    write_u16(m, 0x4C, 0)
    write_u16(m, 0x7C, 7)
    write_u16(m, 0xA4, case.regs["A7"] & 0xFFFF)
    write_u16(m, 0xA6, (case.regs["A7"] >> 16) & 0xFFFF)
    write_u16(m, 0xA8, 1)
    write_u16(m, 0xAA, 0)
    write_u16(m, 0x0702, 0)
    write_u16(m, 0x0704, 1)
    write_u16(m, 0x0710, POST_BSR_PC & 0xFFFF)
    write_u16(m, 0x0712, 0)
    write_u16(m, 0x0714, 0)
    write_u16(m, 0x0716, (POST_BSR_PC >> 16) & 0xFF)
    write_u16(m, 0x0718, 0xFFF8)
    write_u16(m, 0x071A, xlat_gate)
    write_u16(m, 0x072E, 0)
    write_u16(m, 0x0730, 0)
    write_u16(m, 0x0734, 0x2A19)
    write_u16(m, 0x0736, 0)
    write_u16(m, 0x0738, 0)
    write_u16(m, 0x073A, 0)
    write_u16(m, 0x073C, 0)

    seam_hook = m.add_exec_hook(DEBUG_SPIN, cpu_type="Sa1")
    m.drain_notifications(timeout=0.05)
    base.set_sa1_pc(m, ENTRY_NATIVE)
    start_cycles = int(m.get_cpu_state("Sa1")["cycleCount"])
    hit = m.run_until(max_frames=12, hook_handle=seam_hook)
    m.pause()
    m.remove_hook(seam_hook)
    if (hit or {}).get("reason") != "hookFired":
        raise RuntimeError(
            f"Nexen did not freeze at post-BSR PC ${POST_BSR_PC:06X} "
            f"for {case.name}, xlat={xlat_gate}: {hit!r}"
        )
    end_cycles = int(m.get_cpu_state("Sa1")["cycleCount"])
    observed_pc = read_u16(m, 0x40) | ((read_u16(m, 0x42) & 0xFF) << 16)
    if not read_u16(m, 0x0712) or observed_pc != POST_BSR_PC:
        raise RuntimeError(
            f"Nexen froze at ${observed_pc:06X}, expected ${POST_BSR_PC:06X}"
        )
    return base.Result(
        captured_regs(m),
        (case.sr & ~base.CCR_MASK) | captured_ccr(m),
        bytes(m.read_memory(base.SNES_SPACE, 0x400000, MAPPED_WORK_SIZE)),
        end_cycles - start_cycles,
    )


def compare(
    case: LiveCase,
    arcade: base.Result,
    console: base.Result,
    xlat_gate: int,
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
    ccr_mismatch = (
        arcade.sr & base.CCR_MASK
    ) != (console.sr & base.CCR_MASK)
    return {
        "event": "case",
        "case": case.name,
        "tick": case.tick,
        "dispatch_state": case.state_byte,
        "post_bsr_pc": f"{POST_BSR_PC:06X}",
        "post_bsr_native": f"{POST_BSR_NATIVE:06X}",
        "nested_xlat_gate": xlat_gate,
        "result": (
            "green"
            if not reg_mismatches
            and not ccr_mismatch
            and not work_mismatches
            else "red"
        ),
        "reg_mismatches": reg_mismatches,
        "mame_ccr": arcade.sr & base.CCR_MASK,
        "nexen_ccr": console.sr & base.CCR_MASK,
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
    parser.add_argument("--state", type=Path, default=DEFAULT_STATE)
    parser.add_argument("--nexen", type=Path, default=base.DEFAULT_NEXEN)
    parser.add_argument("--nat", type=Path, default=base.DEFAULT_NAT)
    parser.add_argument("--port", type=int, default=7572)
    parser.add_argument("--cases", type=int, default=6)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    for path in (args.rom, args.state, args.nexen, args.nat):
        if not path.is_file():
            parser.error(f"missing required input: {path}")
    if args.cases < 1:
        parser.error("--cases must be positive")
    if args.output.exists():
        parser.error(f"output already exists: {args.output}")

    args.output.parent.mkdir(parents=True, exist_ok=True)
    fixture_dir = args.output.parent / f"{args.output.stem}-fixtures"
    if fixture_dir.exists():
        parser.error(f"fixture directory already exists: {fixture_dir}")
    fixture_dir.mkdir()

    events: list[dict] = []
    provenance = {
        "event": "provenance",
        "scope": (
            "live-fixture function-local $02A190 MAME/Nexen differential; "
            "all D/A registers, CCR, mapped 16 KiB work RAM; not fps"
        ),
        "mame": "/snap/bin/mame 0.287",
        "nexen": str(args.nexen.resolve()),
        "nexen_sha256": sha256(args.nexen),
        "rom": str(args.rom.resolve()),
        "rom_sha256": sha256(args.rom),
        "state": str(args.state.resolve()),
        "state_sha256": sha256(args.state),
        "nat": str(args.nat.resolve()),
        "nat_sha256": sha256(args.nat),
        "entry_pc": f"{ENTRY_PC:06X}",
        "post_bsr_pc": f"{POST_BSR_PC:06X}",
        "post_bsr_native": f"{POST_BSR_NATIVE:06X}",
        "entry_native": f"{ENTRY_NATIVE:06X}",
        "fixtures": args.cases,
        "variants_per_fixture": 2,
        "time": time.time(),
    }
    events.append(provenance)
    print(json.dumps(provenance, sort_keys=True), flush=True)

    cases = capture_live_cases(
        args.rom,
        args.state,
        args.nexen,
        args.port,
        args.cases,
        fixture_dir / "capture.nexen.stderr.log",
    )
    for index, case in enumerate(cases):
        (fixture_dir / f"case-{index:02d}.work.bin").write_bytes(case.work)
        fixture = {
            "name": case.name,
            "tick": case.tick,
            "dispatch_state": case.state_byte,
            "entry_exit_hint_pc": f"{case.exit_pc:06X}",
            "sr": case.sr,
            "regs": case.regs,
            "work_sha256": hashlib.sha256(case.work).hexdigest(),
        }
        (fixture_dir / f"case-{index:02d}.json").write_text(
            json.dumps(fixture, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        event = {"event": "fixture", **fixture}
        events.append(event)
        print(json.dumps(event, sort_keys=True), flush=True)

    arcade: dict[str, base.Result] = {}
    for case in cases:
        # A failed/alternate terminal trap can leave MAME's synthetic direct
        # execution context suspended even after registers are rewritten.
        # One process per retained fixture removes that cross-case state.
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
            arcade[case.name] = mame_result(mame, case)
            event = {
                "event": "mame_case",
                "case": case.name,
                "oracle_post_bsr_pc": f"{POST_BSR_PC:06X}",
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
        for case in cases:
            for xlat_gate in (0, 1):
                console = nexen_result(
                    nexen,
                    args.nat,
                    case,
                    xlat_gate=xlat_gate,
                )
                event = compare(
                    case,
                    arcade[case.name],
                    console,
                    xlat_gate,
                )
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
