#!/usr/bin/env python3
"""Live MAME/Nexen differential for the $DA72 task-yield span.

Capture organic sustained-gameplay state before the native $DA72 continuation,
run the original MC68000 code from $DA72 to the pre-execution $DA70 trap #5
boundary in MAME, and compare it with the candidate native path in Nexen.
Each fixture runs with nested xlat dispatch disabled and enabled.

The gate compares every D/A register, CCR and interrupt mask, plus the complete
mapped 16 KiB work-RAM window (including task-stack residue).  This is bounded
checkpoint semantic/cycle evidence, never an FPS or playability result.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import time
from dataclasses import replace
from pathlib import Path

import validate_175a0_native as shared
import validate_d96_hle as base


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_ROM = (
    ROOT
    / "build/playability-20260720/da72-yield-safe-task-diagnostic-v2/interp.sfc"
)
DEFAULT_STATE = (
    ROOT
    / "build/playability-20260720/"
    "nmi-preserve-a-uninterrupted-coldboot-ordering-v1/final.mss"
)
DEFAULT_CAPTURE_ROM = (
    ROOT
    / "build/playability-20260720/25110-stage2-signed-diagnostic-v1/interp.sfc"
)
ENTRY_PC = 0x00DA72
ENTRY_NATIVE = 0x9DCC00
EXIT_PC = 0x00DA70
RETURN_PC = 0x00D8B4
MAPPED_WORK_SIZE = 0x4000
FULL_WORK_SIZE = 0x10000
INPUT_BUTTONS = 0x82
SYNTHETIC_MUTATIONS = (
    ("counter-0", {0x2AB6: 0x0000}, None),
    ("counter-5", {0x2AB6: 0x0005}, None),
    ("counter-6", {0x2AB6: 0x0006}, None),
    ("counter-9-full-ccr", {0x2AB6: 0x0009}, 0x1F),
    ("counter-10", {0x2AB6: 0x000A}, None),
    ("mode-7-counter-0", {0x2AB0: 0x0007, 0x2AB6: 0x0000}, None),
    ("mode-7-counter-10", {0x2AB0: 0x0007, 0x2AB6: 0x000A}, None),
)

# Reuse the proven Nexen injection/freeze implementation.  Its function reads
# these module globals at call time; the case-specific exit remains on LiveCase.
shared.ENTRY_PC = ENTRY_PC
shared.ENTRY_NATIVE = ENTRY_NATIVE
shared.MAPPED_WORK_SIZE = MAPPED_WORK_SIZE
shared.FULL_WORK_SIZE = FULL_WORK_SIZE


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def capture_live_cases(
    capture_rom: Path,
    state: Path,
    nexen: Path,
    port: int,
    count: int,
    stderr_log: Path,
) -> list[shared.LiveCase]:
    cases: list[shared.LiveCase] = []
    with base.McpSession(
        rom=str(capture_rom),
        mesen=str(nexen),
        cwd=ROOT,
        port=port,
        boot_wait=8.0,
        socket_timeout=180.0,
        stderr_log=stderr_log,
    ) as session:
        session.pause()
        session.load_state(str(state))
        session.pause()
        session.tool(
            "set_input",
            {"port": 0, "buttons": INPUT_BUTTONS, "hold": True},
        )
        # Capture through the reference interpreter's pre-fetch barrier.  An
        # execution-hook notification alone is not atomic: Nexen can advance
        # beyond a native entry before the client pause arrives.
        shared.write_u16(session, 0x0710, ENTRY_PC & 0xFFFF)
        shared.write_u16(session, 0x0712, 0)
        shared.write_u16(session, 0x0714, 0)
        shared.write_u16(session, 0x0716, (ENTRY_PC >> 16) & 0xFF)
        shared.write_u16(session, 0x0718, 0xFFF8)
        shared.write_u16(session, 0x0730, 0x5A5A)
        hook = session.add_exec_hook(shared.DEBUG_SPIN, cpu_type="Sa1")
        session.drain_notifications(timeout=0.05)
        calls_seen = 0
        rejected_returns: list[int] = []
        try:
            while len(cases) < count and calls_seen < count * 8 + 16:
                if calls_seen:
                    # Leave the persistent target armed, execute the frozen
                    # instruction, and allow the next organic call to stop.
                    shared.write_u16(session, 0x0712, 0)
                    shared.write_u16(session, 0x0714, 1)
                    session.run_frames(1)
                    session.pause()
                    session.drain_notifications(timeout=0.02)
                calls_seen += 1
                observed_pc = shared.read_u16(session, 0x40) | (
                    (shared.read_u16(session, 0x42) & 0xFF) << 16
                )
                if shared.read_u16(session, 0x0712) and observed_pc == ENTRY_PC:
                    hit = {"reason": "hookFired"}
                else:
                    hit = session.run_until(max_frames=240, hook_handle=hook)
                    session.pause()
                    observed_pc = shared.read_u16(session, 0x40) | (
                        (shared.read_u16(session, 0x42) & 0xFF) << 16
                    )
                if (
                    (hit or {}).get("reason") != "hookFired"
                    or not shared.read_u16(session, 0x0712)
                    or observed_pc != ENTRY_PC
                ):
                    raise RuntimeError(
                        f"reference capture did not freeze at ${ENTRY_PC:06X}: "
                        f"hit={hit!r}, marker={shared.read_u16(session, 0x0712)}, "
                        f"pc=${observed_pc:06X}"
                    )
                regs = shared.captured_regs(session)
                work = bytes(
                    session.read_memory(base.SNES_SPACE, 0x400000, FULL_WORK_SIZE)
                )
                stack = regs["A7"] & 0xFFFF
                return_pc = int.from_bytes(work[stack : stack + 4], "big") & 0xFFFFFF
                if return_pc != RETURN_PC:
                    rejected_returns.append(return_pc)
                    continue
                tick = shared.be16(work, 0x1C56)
                index = len(cases)
                cases.append(
                    shared.LiveCase(
                        name=f"live-{index:02d}-tick-{tick}",
                        regs=regs,
                        sr=shared.captured_sr(session),
                        work=work,
                        tick=tick,
                        exit_pc=EXIT_PC,
                    )
                )
        finally:
            session.remove_hook(hook)
        if len(cases) != count:
            rendered = ", ".join(f"${value:06X}" for value in rejected_returns)
            raise RuntimeError(
                f"captured only {len(cases)}/{count} $DA72 calls with real "
                f"return $D8B4; rejected [{rendered}]"
            )
    return cases


def mame_result(session: base.MameSession, case: shared.LiveCase) -> base.Result:
    session.pause()
    # MAME's capture_at_pc is an opcode-prefetch tap.  Capturing the trap word
    # itself can observe the preceding JSR/RTS pipeline before its architectural
    # state has retired.  Replace only the fetched trap with a validation NOP
    # and capture the following $DA72 fetch.  The injected entry prefetch is
    # already complete before capture_at_pc arms, so this is the post-span hit.
    session.exec_lua(
        "MCP_DA72_EXIT_NOP = machine.devices[':maincpu'].spaces['program']"
        ":install_read_tap(0x00da70, 0x00da71, 'mcp_da72_exit_nop', "
        "function(offset, data, mask) return 0x4e71 end); return true"
    )
    session.write_block(0xF00000, case.work[:MAPPED_WORK_SIZE])
    for name in base.REG_NAMES[:-1]:
        session.set_reg(name, case.regs[name])

    # Prevent an unrelated pending MAME VBLANK IRQ6 from entering the local
    # injected span.  $DA72..$DA70 does not change the interrupt mask, so the
    # reported result restores the organic entry mask after capture.
    session.set_reg("SR", case.sr | 0x0700)
    session.set_reg("USP", case.regs["A7"])
    session.set_reg("SP", case.regs["A7"])
    session.set_reg("PC", ENTRY_PC)
    captured = session.cmd(
        "capture_at_pc",
        pc=ENTRY_PC,
        addr=0xF00000,
        len=MAPPED_WORK_SIZE,
        nth=1,
        exp_sp=case.regs["A7"] & 0xFFFFFF,
        maxFrames=60,
        timeout=60,
    )
    if not captured.get("registers"):
        raise RuntimeError(
            f"MAME did not reach committed post-trap seam ${ENTRY_PC:06X} "
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


def expand_cases(base_case: shared.LiveCase, total: int) -> list[shared.LiveCase]:
    """Add explicit branch fixtures derived from one atomic organic capture."""

    cases = [base_case]
    for label, word_mutations, incoming_ccr in SYNTHETIC_MUTATIONS[: total - 1]:
        work = bytearray(base_case.work)
        for offset, value in word_mutations.items():
            work[offset : offset + 2] = value.to_bytes(2, "big")
        sr = base_case.sr
        if incoming_ccr is not None:
            sr = (sr & ~base.CCR_MASK) | incoming_ccr
        cases.append(
            replace(
                base_case,
                name=f"synth-{label}-from-tick-{base_case.tick}",
                work=bytes(work),
                sr=sr,
            )
        )
    return cases


def emit(events: list[dict], event: dict) -> None:
    events.append(event)
    print(json.dumps(event, sort_keys=True), flush=True)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--rom", type=Path, default=DEFAULT_ROM)
    parser.add_argument("--capture-rom", type=Path, default=DEFAULT_CAPTURE_ROM)
    parser.add_argument("--state", type=Path, default=DEFAULT_STATE)
    parser.add_argument("--nexen", type=Path, default=base.DEFAULT_NEXEN)
    parser.add_argument("--nat", type=Path, default=base.DEFAULT_NAT)
    parser.add_argument("--port", type=int, default=7620)
    parser.add_argument("--cases", type=int, default=6)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    for path in (args.rom, args.capture_rom, args.state, args.nexen, args.nat):
        if not path.is_file():
            parser.error(f"missing required input: {path}")
    if not 1 <= args.cases <= 1 + len(SYNTHETIC_MUTATIONS):
        parser.error(
            f"--cases must be between 1 and {1 + len(SYNTHETIC_MUTATIONS)}"
        )
    if args.output.exists():
        parser.error(f"output already exists: {args.output}")

    args.output.parent.mkdir(parents=True, exist_ok=True)
    fixture_dir = args.output.parent / f"{args.output.stem}-fixtures"
    if fixture_dir.exists():
        parser.error(f"fixture directory already exists: {fixture_dir}")
    fixture_dir.mkdir()

    events: list[dict] = []
    emit(
        events,
        {
            "event": "provenance",
            "scope": (
                "live-fixture checkpointed $DA72-to-$DA70 MAME/Nexen "
                "differential; all D/A registers, CCR/mask, mapped 16 KiB "
                "work RAM; not fps"
            ),
            "mame": "/snap/bin/mame 0.287",
            "nexen": str(args.nexen.resolve()),
            "nexen_sha256": sha256(args.nexen),
            "rom": str(args.rom.resolve()),
            "rom_sha256": sha256(args.rom),
            "capture_rom": str(args.capture_rom.resolve()),
            "capture_rom_sha256": sha256(args.capture_rom),
            "state": str(args.state.resolve()),
            "state_sha256": sha256(args.state),
            "nat": str(args.nat.resolve()),
            "nat_sha256": sha256(args.nat),
            "entry_pc": f"{ENTRY_PC:06X}",
            "entry_native": f"{ENTRY_NATIVE:06X}",
            "terminal_pc": f"{EXIT_PC:06X}",
            "required_real_return": f"{RETURN_PC:06X}",
            "capture_method": "reference PC_RING pre-fetch freeze at $00DA72",
            "input_buttons": INPUT_BUTTONS,
            "mame_irq_isolation": (
                "entry mask forced to 7; organic mask restored in reported result"
            ),
            "mame_terminal_capture": (
                "$DA70 read-tap NOP, then post-span $DA72 prefetch; ROM file unchanged"
            ),
            "fixtures": args.cases,
            "organic_fixtures": 1,
            "synthetic_fixtures": args.cases - 1,
            "synthetic_mutations": [
                {
                    "name": label,
                    "work_words": {
                        f"F0{offset:04X}": f"{value:04X}"
                        for offset, value in mutations.items()
                    },
                    "incoming_ccr": incoming_ccr,
                }
                for label, mutations, incoming_ccr in SYNTHETIC_MUTATIONS[
                    : args.cases - 1
                ]
            ],
            "variants_per_fixture": 2,
            "time": time.time(),
        },
    )

    organic_cases = capture_live_cases(
        args.capture_rom,
        args.state,
        args.nexen,
        args.port,
        1,
        fixture_dir / "capture.nexen.stderr.log",
    )
    cases = expand_cases(organic_cases[0], args.cases)
    for index, case in enumerate(cases):
        (fixture_dir / f"case-{index:02d}.work.bin").write_bytes(case.work)
        fixture = {
            "event": "fixture",
            "name": case.name,
            "tick": case.tick,
            "terminal_pc": f"{case.exit_pc:06X}",
            "sr": case.sr,
            "regs": case.regs,
            "work_sha256": hashlib.sha256(case.work).hexdigest(),
        }
        (fixture_dir / f"case-{index:02d}.json").write_text(
            json.dumps(fixture, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        emit(events, fixture)

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
            emit(
                events,
                {
                    "event": "mame_case",
                    "case": case.name,
                    "oracle_terminal_pc": f"{EXIT_PC:06X}",
                },
            )
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
                console = shared.nexen_result(
                    nexen,
                    args.nat,
                    case,
                    xlat_gate=xlat_gate,
                    choke_gate=0,
                )
                emit(
                    events,
                    shared.compare(
                        case,
                        arcade[case.name],
                        console,
                        xlat_gate,
                        0,
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
    emit(events, summary)
    args.output.write_text(
        "".join(json.dumps(event, sort_keys=True) + "\n" for event in events),
        encoding="utf-8",
    )
    return 0 if summary["result"] == "green" else 1


if __name__ == "__main__":
    raise SystemExit(main())
