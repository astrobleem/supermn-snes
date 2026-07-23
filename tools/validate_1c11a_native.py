#!/usr/bin/env python3
"""Live-fixture MAME/Nexen differential for native coroutine $01C11A.

The source state is captured organically at the bank-$95 entry.  MAME then
executes the original MC68000 body to the preceding yield opcode at $01C118;
Nexen executes the generated native body to the same PC.  Compare every D/A
register, CCR and interrupt mask, plus the complete mapped 16 KiB work-RAM
window.  Each fixture is run with nested xlat disabled and enabled.

This is bounded function-semantic and local-cycle evidence, not FPS.  MAME can
have a held VBLANK IRQ6 at injection time, so its local span starts masked at
seven.  $01C11A-$01C5B8 contains no SR-mask writer; the reported mask is
therefore restored to the organically captured entry value after execution.
No ROM byte is patched.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import time
from pathlib import Path

import validate_175a0_native as shared


base = shared.base
ROOT = shared.ROOT
DEFAULT_ROM = shared.DEFAULT_ROM
DEFAULT_STATE = shared.DEFAULT_STATE
ENTRY_PC = 0x01C11A
ENTRY_NATIVE = 0x95D041
EXIT_PC = 0x01C118
DEBUG_SPIN = shared.DEBUG_SPIN
MAPPED_WORK_SIZE = shared.MAPPED_WORK_SIZE
FULL_WORK_SIZE = shared.FULL_WORK_SIZE


def capture_live_cases(
    rom: Path,
    state: Path,
    nexen: Path,
    port: int,
    count: int,
    stderr_log: Path,
) -> list[shared.LiveCase]:
    cases: list[shared.LiveCase] = []
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
                regs = shared.captured_regs(m)
                work = bytes(
                    m.read_memory(base.SNES_SPACE, 0x400000, FULL_WORK_SIZE)
                )
                tick = shared.be16(work, 0x1C56)
                cases.append(
                    shared.LiveCase(
                        name=f"live-{index:02d}-tick-{tick}",
                        regs=regs,
                        sr=shared.captured_sr(m),
                        work=work,
                        tick=tick,
                        exit_pc=EXIT_PC,
                    )
                )
        finally:
            m.remove_hook(hook)
    return cases


def load_cases(fixture_dir: Path, count: int) -> list[shared.LiveCase]:
    """Load retained organic fixtures for an exact post-fix replay."""

    cases: list[shared.LiveCase] = []
    metadata_paths = sorted(fixture_dir.glob("case-*.json"))
    if len(metadata_paths) < count:
        raise RuntimeError(
            f"fixture directory has {len(metadata_paths)} cases, need {count}: "
            f"{fixture_dir}"
        )
    for metadata_path in metadata_paths[:count]:
        metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
        work_path = metadata_path.with_suffix(".work.bin")
        work = work_path.read_bytes()
        if len(work) != FULL_WORK_SIZE:
            raise RuntimeError(
                f"fixture {work_path} is {len(work)} bytes, expected "
                f"{FULL_WORK_SIZE}"
            )
        cases.append(
            shared.LiveCase(
                name=metadata["name"],
                regs={name: int(value) for name, value in metadata["regs"].items()},
                sr=int(metadata["sr"]),
                work=work,
                tick=int(metadata["tick"]),
                exit_pc=int(metadata["terminal_pc"], 16),
            )
        )
    return cases


def mame_result(
    session: base.MameSession, case: shared.LiveCase
) -> base.Result:
    session.pause()
    session.write_block(0xF00000, case.work[:MAPPED_WORK_SIZE])
    for name in base.REG_NAMES[:-1]:
        session.set_reg(name, case.regs[name])
    # Prevent a held real IRQ6 from escaping this local injected span.  The
    # function does not write the interrupt mask, so normalize it on readback.
    session.set_reg("SR", case.sr | 0x0700)
    session.set_reg("USP", case.regs["A7"])
    session.set_reg("SP", case.regs["A7"])
    session.set_reg("PC", ENTRY_PC)
    captured = session.cmd(
        "capture_at_pc",
        pc=EXIT_PC,
        addr=0xF00000,
        len=MAPPED_WORK_SIZE,
        nth=1,
        exp_sp=case.regs["A7"] & 0xFFFFFF,
        maxFrames=60,
        timeout=60,
    )
    if not captured.get("registers"):
        raise RuntimeError(
            f"MAME did not reach terminal PC ${EXIT_PC:06X} "
            f"for {case.name}: {captured!r}"
        )
    regs = captured["registers"]
    result_regs = {
        name: regs[name] & 0xFFFFFFFF for name in base.REG_NAMES[:-1]
    }
    result_regs["A7"] = regs["SP"] & 0xFFFFFFFF
    result_sr = ((regs["SR"] & 0xFFFF) & ~0x0700) | (case.sr & 0x0700)
    return base.Result(
        result_regs,
        result_sr,
        bytes.fromhex(captured["hex"]),
    )


def nexen_result(
    m: base.McpSession,
    nat: Path,
    case: shared.LiveCase,
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
    shared.park_snes_cpu(m)

    flags = case.sr & base.CCR_MASK
    shared.write_u16(m, 0x6E, flags & 1)
    shared.write_u16(m, 0x72, (flags >> 1) & 1)
    shared.write_u16(m, 0x60, (flags >> 2) & 1)
    shared.write_u16(m, 0x70, (flags >> 3) & 1)
    shared.write_u16(m, 0xA2, (flags >> 4) & 1)
    shared.write_u16(m, 0x7C, (case.sr >> 8) & 7)
    shared.write_u16(m, 0x40, ENTRY_PC & 0xFFFF)
    shared.write_u16(m, 0x42, (ENTRY_PC >> 16) & 0xFF)
    shared.write_u16(m, 0x4A, 0)
    shared.write_u16(m, 0x4C, 0)
    shared.write_u16(m, 0xA4, case.regs["A7"] & 0xFFFF)
    shared.write_u16(m, 0xA6, (case.regs["A7"] >> 16) & 0xFFFF)
    shared.write_u16(m, 0xA8, 1)
    shared.write_u16(m, 0xAA, 0)
    shared.write_u16(m, 0xAC, 0x7000)
    shared.write_u16(m, 0x0702, 0)
    shared.write_u16(m, 0x0704, 1)
    shared.write_u16(m, 0x0710, EXIT_PC & 0xFFFF)
    shared.write_u16(m, 0x0712, 0)
    shared.write_u16(m, 0x0714, 0)
    shared.write_u16(m, 0x0716, (EXIT_PC >> 16) & 0xFF)
    shared.write_u16(m, 0x0718, 0xFFF8)
    shared.write_u16(m, 0x071A, xlat_gate)
    shared.write_u16(m, 0x072E, 0)
    shared.write_u16(m, 0x0730, 0)
    shared.write_u16(m, 0x0734, 0)
    shared.write_u16(m, 0x0736, 0)
    shared.write_u16(m, 0x0738, 0)
    shared.write_u16(m, 0x073A, 0)
    shared.write_u16(m, 0x073C, 0)

    seam_hook = m.add_exec_hook(DEBUG_SPIN, cpu_type="Sa1")
    m.drain_notifications(timeout=0.05)
    base.set_sa1_pc(m, ENTRY_NATIVE)
    start_cycles = int(m.get_cpu_state("Sa1")["cycleCount"])
    hit = m.run_until(max_frames=24, hook_handle=seam_hook)
    m.pause()
    m.remove_hook(seam_hook)
    if (hit or {}).get("reason") != "hookFired":
        raise RuntimeError(
            f"Nexen did not freeze at terminal PC ${EXIT_PC:06X} "
            f"for {case.name}, xlat={xlat_gate}: {hit!r}"
        )
    end_cycles = int(m.get_cpu_state("Sa1")["cycleCount"])
    observed_pc = shared.read_u16(m, 0x40) | (
        (shared.read_u16(m, 0x42) & 0xFF) << 16
    )
    if not shared.read_u16(m, 0x0712) or observed_pc != EXIT_PC:
        raise RuntimeError(
            f"Nexen froze at ${observed_pc:06X}, expected ${EXIT_PC:06X}"
        )
    sr = 0x2000 | ((shared.read_u16(m, 0x7C) & 7) << 8) | shared.captured_ccr(m)
    return base.Result(
        shared.captured_regs(m),
        sr,
        bytes(m.read_memory(base.SNES_SPACE, 0x400000, MAPPED_WORK_SIZE)),
        end_cycles - start_cycles,
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--rom", type=Path, default=DEFAULT_ROM)
    parser.add_argument("--state", type=Path, default=DEFAULT_STATE)
    parser.add_argument("--nexen", type=Path, default=base.DEFAULT_NEXEN)
    parser.add_argument("--nat", type=Path, default=base.DEFAULT_NAT)
    parser.add_argument("--port", type=int, default=7660)
    parser.add_argument("--cases", type=int, default=12)
    parser.add_argument(
        "--fixture-dir",
        type=Path,
        help="replay retained case-*.json/.work.bin fixtures instead of recapturing",
    )
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
    if args.fixture_dir is not None:
        fixture_dir = args.fixture_dir
        if not fixture_dir.is_dir():
            parser.error(f"fixture directory does not exist: {fixture_dir}")
    else:
        fixture_dir = args.output.parent / f"{args.output.stem}-fixtures"
        if fixture_dir.exists():
            parser.error(f"fixture directory already exists: {fixture_dir}")
        fixture_dir.mkdir()

    events: list[dict] = []
    provenance = {
        "event": "provenance",
        "scope": (
            "live-fixture function-local $01C11A MAME/Nexen differential; "
            "all D/A registers, CCR/mask, mapped 16 KiB work RAM; not fps"
        ),
        "mame": "/snap/bin/mame 0.287",
        "mame_irq_isolation": {
            "reason": "prevent unrelated held VBLANK IRQ6 during local injection",
            "entry_mask": 7,
            "reported_mask": "organic entry mask; function has no SR-mask writer",
            "rom_file_modified": False,
        },
        "nexen": str(args.nexen.resolve()),
        "nexen_sha256": shared.sha256(args.nexen),
        "rom": str(args.rom.resolve()),
        "rom_sha256": shared.sha256(args.rom),
        "state": str(args.state.resolve()),
        "state_sha256": shared.sha256(args.state),
        "nat": str(args.nat.resolve()),
        "nat_sha256": shared.sha256(args.nat),
        "entry_pc": f"{ENTRY_PC:06X}",
        "entry_native": f"{ENTRY_NATIVE:06X}",
        "terminal_pc": f"{EXIT_PC:06X}",
        "jump_tables": ["01C130:0:26", "01C2BC:0:26"],
        "fixtures": args.cases,
        "fixture_source": (
            str(fixture_dir.resolve())
            if args.fixture_dir is not None
            else "fresh production capture"
        ),
        "variants_per_fixture": 2,
        "time": time.time(),
    }
    events.append(provenance)
    print(json.dumps(provenance, sort_keys=True), flush=True)

    cases = (
        load_cases(fixture_dir, args.cases)
        if args.fixture_dir is not None
        else capture_live_cases(
            args.rom,
            args.state,
            args.nexen,
            args.port,
            args.cases,
            fixture_dir / "capture.nexen.stderr.log",
        )
    )
    for index, case in enumerate(cases):
        fixture = {
            "name": case.name,
            "tick": case.tick,
            "terminal_pc": f"{case.exit_pc:06X}",
            "sr": case.sr,
            "regs": case.regs,
            "work_sha256": hashlib.sha256(case.work).hexdigest(),
        }
        if args.fixture_dir is None:
            (fixture_dir / f"case-{index:02d}.work.bin").write_bytes(case.work)
            (fixture_dir / f"case-{index:02d}.json").write_text(
                json.dumps(fixture, indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )
        event = {"event": "fixture", **fixture}
        events.append(event)
        print(json.dumps(event, sort_keys=True), flush=True)

    arcade: dict[str, base.Result] = {}
    for case in cases:
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
                "oracle_terminal_pc": f"{EXIT_PC:06X}",
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
                event = shared.compare(
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
