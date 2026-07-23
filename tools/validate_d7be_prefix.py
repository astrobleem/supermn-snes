#!/usr/bin/env python3
"""Organic MAME/Nexen differential for the guarded $00D7BE prefix.

The reference ROM freezes on the organically fetched 68000 PC using the
diagnostic PC ring.  MAME executes the original bounded initializer through
the pre-$00D9A8 seam; Nexen executes both the direct bank-$9E body and the
production fetch-choke/xlat route.  Guard misses compare the choke-on route
against the unchanged interpreter.  This is bounded semantic and local-cycle
evidence, never an FPS result.
"""

from __future__ import annotations

import argparse
import dataclasses
import hashlib
import json
import time
from pathlib import Path

import validate_1c9ae_empty as impl
import validate_1f2e4_native as live


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CAPTURE_ROM = (
    ROOT
    / "build/playability-20260720/fanout-1c9ae-diagnostic-v1/interp.sfc"
)
DEFAULT_ROM = (
    ROOT / "build/playability-20260720/d7be-ccr-diagnostic-v1/interp.sfc"
)
DEFAULT_STATE = (
    ROOT
    / "build/playability-20260720/"
    "fanout-1c9ae-production-v1-coldboot-immediate-v1/"
    "gameplay_detected.mss"
)

ENTRY_PC = 0x00D7BE
NEXT_PC = 0x00D7C4
EXIT_PC = 0x00D9A8
# $00D9A8 is a six-byte JSR.  On MAME 0.287 the read tap at its final operand
# word ($D9AC) observes CURPC=$D9A8 before the call mutates SP; a tap at $D9AE
# is too late and can observe the callee's prefetch instead.
MAME_CAPTURE_PC = 0x00D9AC
ENTRY_NATIVE = 0x9ED800
OJMP_HOOK = impl.OJMP_HOOK
DEBUG_SPIN = impl.DEBUG_SPIN
CAPTURE_BUTTONS = 0x82
FULL_WORK_SIZE = impl.FULL_WORK_SIZE
MAPPED_WORK_SIZE = impl.MAPPED_WORK_SIZE
CCR_MASK = impl.CCR_MASK
HOT_INSTRUCTION_COUNT = 84


def configure_impl() -> None:
    """Point the shared isolated-console harness at this prefix."""

    impl.ENTRY_PC = ENTRY_PC
    impl.NEXT_PC = NEXT_PC
    impl.EXIT_PC = EXIT_PC
    impl.MAME_CAPTURE_PC = MAME_CAPTURE_PC
    impl.ENTRY_NATIVE = ENTRY_NATIVE


def put_be16(data: bytearray, offset: int, value: int) -> None:
    offset &= 0xFFFF
    data[offset] = (value >> 8) & 0xFF
    data[(offset + 1) & 0xFFFF] = value & 0xFF


def capture_case(
    rom: Path,
    state: Path,
    nexen: Path,
    port: int,
    stderr_log: Path,
) -> impl.Case:
    """Freeze the old interpreter before organic $00D7BE executes."""

    with impl.base.McpSession(
        rom=str(rom),
        mesen=str(nexen),
        cwd=ROOT,
        port=port,
        boot_wait=8.0,
        socket_timeout=240.0,
        stderr_log=stderr_log,
    ) as m:
        m.pause()
        m.load_state(str(state))
        m.pause()
        m.tool(
            "set_input",
            {"port": 0, "buttons": CAPTURE_BUTTONS, "hold": True},
        )
        # Diagnostic PC-ring freeze only; game registers, RAM, gates, and
        # scheduler state remain organic until the fetched target is observed.
        live.write_u16(m, 0x0710, ENTRY_PC & 0xFFFF)
        live.write_u16(m, 0x0712, 0)
        live.write_u16(m, 0x0714, 0)
        live.write_u16(m, 0x0716, (ENTRY_PC >> 16) & 0xFF)
        live.write_u16(m, 0x0718, 0xFFF8)
        live.write_u16(m, 0x0730, 0x5A5A)
        hook = m.add_exec_hook(DEBUG_SPIN, cpu_type="Sa1")
        m.drain_notifications(timeout=0.05)
        try:
            hit, frames_advanced = live.run_to_hook(m, hook, attempts=20)
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
            m.read_memory(impl.base.SNES_SPACE, 0x400000, FULL_WORK_SIZE)
        )
        a5 = regs["A5"] & 0xFFFFFF
        a7 = regs["A7"] & 0xFFFFFF
        count = live.work_be16(work, (a7 + 6) & 0xFFFF)
        if a5 != 0xF00000 or (a7 >> 16) != 0xF0 or count != 4:
            raise RuntimeError(
                f"unexpected organic entry shape: A5=${a5:06X}, "
                f"A7=${a7:06X}, 6(A7)={count}"
            )
        return impl.Case(
            regs=regs,
            sr=live.captured_sr(m),
            work=work,
            tick=live.work_be16(work, 0x1C56),
            frame=int(m.get_state().get("frameCount", 0)),
            capture_frames_advanced=frames_advanced,
        )


def load_case(fixture_dir: Path) -> impl.Case:
    metadata_path = fixture_dir / "case-00.json"
    work_path = fixture_dir / "case-00.work.bin"
    if not metadata_path.is_file() or not work_path.is_file():
        raise RuntimeError(f"incomplete input fixture: {fixture_dir}")
    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    work = work_path.read_bytes()
    if len(work) != FULL_WORK_SIZE:
        raise RuntimeError(
            f"input fixture work image is {len(work)} bytes, expected {FULL_WORK_SIZE}"
        )
    expected_sha = metadata.get("work_sha256")
    actual_sha = hashlib.sha256(work).hexdigest()
    if expected_sha != actual_sha:
        raise RuntimeError(
            f"input fixture work hash mismatch: {expected_sha} != {actual_sha}"
        )
    return impl.Case(
        regs={name: int(value) for name, value in metadata["regs"].items()},
        sr=int(metadata["sr"]),
        work=work,
        tick=int(metadata["tick"]),
        frame=int(metadata["frame"]),
        capture_frames_advanced=int(metadata["capture_frames_advanced"]),
    )


def mame_result(session: impl.base.MameSession, case: impl.Case) -> impl.base.Result:
    session.pause()
    session.write_block(0xF00000, case.work[:MAPPED_WORK_SIZE])
    for name in impl.base.REG_NAMES[:-1]:
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
            f"MAME prefetch mismatch: requested ${MAME_CAPTURE_PC:06X}, "
            f"got CURPC=${regs.get('CURPC', -1) & 0xFFFFFF:06X}"
        )
    result_regs = {
        name: regs[name] & 0xFFFFFFFF for name in impl.base.REG_NAMES[:-1]
    }
    result_regs["A7"] = regs["SP"] & 0xFFFFFFFF
    return impl.base.Result(
        result_regs,
        regs["SR"] & 0xFFFF,
        bytes.fromhex(captured["hex"]),
    )


def console_result(
    m: impl.base.McpSession,
    nat: Path,
    case: impl.Case,
    work: bytes,
    *,
    variant: str,
    target_pc: int,
    choke_gate: int,
    ac: int,
) -> impl.ConsoleResult:
    """Run direct native or the real sparse ojmp/xlat production route."""

    impl.prepare_console(
        m,
        nat,
        case,
        work,
        target_pc=target_pc,
        choke_gate=choke_gate,
        ac=ac,
    )
    start_pc = ENTRY_NATIVE if variant == "native-direct" else OJMP_HOOK
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
    return impl.ConsoleResult(
        regs=live.captured_regs(m),
        sr=0x2700 | live.captured_ccr(m),
        work=bytes(
            m.read_memory(impl.base.SNES_SPACE, 0x400000, MAPPED_WORK_SIZE)
        ),
        cycles=int(m.get_cpu_state("Sa1")["cycleCount"]) - start_cycles,
        ac=live.read_u16(m, 0xAC),
    )


def run_guard_case(
    nexen: impl.base.McpSession,
    nat: Path,
    case: impl.Case,
    *,
    name: str,
    target_pc: int,
    ac: int,
) -> dict:
    interpreted = console_result(
        nexen,
        nat,
        case,
        case.work,
        variant="production-route",
        target_pc=target_pc,
        choke_gate=0,
        ac=ac,
    )
    guarded = console_result(
        nexen,
        nat,
        case,
        case.work,
        variant="production-route",
        target_pc=target_pc,
        choke_gate=1,
        ac=ac,
    )
    return impl.compare_results(name, interpreted, guarded, compare_ac=True)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--capture-rom", type=Path, default=DEFAULT_CAPTURE_ROM)
    parser.add_argument("--rom", type=Path, default=DEFAULT_ROM)
    parser.add_argument("--state", type=Path, default=DEFAULT_STATE)
    parser.add_argument(
        "--input-fixture",
        type=Path,
        help="reuse a previously captured case-00.json/work.bin fixture",
    )
    parser.add_argument("--nexen", type=Path, default=impl.base.DEFAULT_NEXEN)
    parser.add_argument("--nat", type=Path, default=impl.base.DEFAULT_NAT)
    parser.add_argument("--port", type=int, default=7650)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    for path in (args.capture_rom, args.rom, args.state, args.nexen, args.nat):
        if not path.is_file():
            parser.error(f"missing required input: {path}")
    if args.input_fixture is not None and not args.input_fixture.is_dir():
        parser.error(f"missing input fixture directory: {args.input_fixture}")
    if args.output.exists():
        parser.error(f"output already exists: {args.output}")

    args.output.parent.mkdir(parents=True, exist_ok=True)
    fixture_dir = args.output.parent / f"{args.output.stem}-fixture"
    if fixture_dir.exists():
        parser.error(f"fixture directory already exists: {fixture_dir}")
    fixture_dir.mkdir()
    configure_impl()

    events: list[dict] = []
    provenance = {
        "event": "provenance",
        "scope": (
            "organic $00D7BE MAME/Nexen bounded differential plus three "
            "guard-miss interpreter A/Bs; not fps"
        ),
        "mame": "/snap/bin/mame 0.287",
        "nexen": str(args.nexen.resolve()),
        "nexen_sha256": impl.sha256(args.nexen),
        "capture_rom": str(args.capture_rom.resolve()),
        "capture_rom_sha256": impl.sha256(args.capture_rom),
        "candidate_rom": str(args.rom.resolve()),
        "candidate_rom_sha256": impl.sha256(args.rom),
        "state": str(args.state.resolve()),
        "state_sha256": impl.sha256(args.state),
        "nat": str(args.nat.resolve()),
        "nat_sha256": impl.sha256(args.nat),
        "entry_pc": f"{ENTRY_PC:06X}",
        "entry_native": f"{ENTRY_NATIVE:06X}",
        "exit_pc": f"{EXIT_PC:06X}",
        "mame_capture_pc": f"{MAME_CAPTURE_PC:06X}",
        "hot_instruction_count": HOT_INSTRUCTION_COUNT,
        "input_fixture": (
            str(args.input_fixture.resolve())
            if args.input_fixture is not None
            else None
        ),
        "time": time.time(),
    }
    events.append(provenance)
    print(json.dumps(provenance, sort_keys=True), flush=True)

    case = (
        load_case(args.input_fixture)
        if args.input_fixture is not None
        else capture_case(
            args.capture_rom,
            args.state,
            args.nexen,
            args.port,
            fixture_dir / "capture.nexen.stderr.log",
        )
    )
    fixture = {
        "event": "fixture",
        "tick": case.tick,
        "frame": case.frame,
        "capture_frames_advanced": case.capture_frames_advanced,
        "sr": case.sr,
        "regs": case.regs,
        "stack_arg_4": live.work_be16(
            case.work, (case.regs["A7"] + 4) & 0xFFFF
        ),
        "stack_arg_6": live.work_be16(
            case.work, (case.regs["A7"] + 6) & 0xFFFF
        ),
        "work_sha256": hashlib.sha256(case.work).hexdigest(),
        "source_fixture": (
            str(args.input_fixture.resolve())
            if args.input_fixture is not None
            else None
        ),
    }
    (fixture_dir / "case-00.work.bin").write_bytes(case.work)
    (fixture_dir / "case-00.json").write_text(
        json.dumps(fixture, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    events.append(fixture)
    print(json.dumps(fixture, sort_keys=True), flush=True)

    mame = impl.base.MameSession(
        mame="/snap/bin/mame",
        system="superman",
        rompath=str(impl.base.MAME_TRACE / "roms"),
        workdir=str(impl.base.MAME_TRACE),
        state_directory=str(impl.base.MAME_TRACE / "sta"),
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

    with impl.base.McpSession(
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
            event = impl.compare_results(variant, arcade, result)
            event["expected_ac"] = 0x7000 - HOT_INSTRUCTION_COUNT
            event["ac_charge_green"] = result.ac == event["expected_ac"]
            if not event["ac_charge_green"]:
                event["result"] = "red"
            events.append(event)
            print(json.dumps(event, sort_keys=True), flush=True)

        count_work = bytearray(case.work)
        put_be16(count_work, (case.regs["A7"] + 6) & 0xFFFF, 3)
        count_case = dataclasses.replace(case, work=bytes(count_work))
        guard_cases = [
            run_guard_case(
                nexen,
                args.nat,
                count_case,
                name="guard-count-not-four",
                target_pc=EXIT_PC,
                ac=0x7000,
            ),
            run_guard_case(
                nexen,
                args.nat,
                dataclasses.replace(
                    case,
                    regs={**case.regs, "A5": (case.regs["A5"] + 2) & 0xFFFFFFFF},
                ),
                name="guard-noncanonical-a5",
                target_pc=EXIT_PC,
                ac=0x7000,
            ),
            run_guard_case(
                nexen,
                args.nat,
                case,
                name="guard-imminent-irq",
                target_pc=NEXT_PC,
                ac=HOT_INSTRUCTION_COUNT - 1,
            ),
        ]
        for event in guard_cases:
            events.append(event)
            print(json.dumps(event, sort_keys=True), flush=True)

    checks = [event for event in events if event.get("event") == "case"]
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
