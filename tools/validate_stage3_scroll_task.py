#!/usr/bin/env python3
"""Exact MAME/native-off/native-on differential for Stage-3 scroll task.

The six organic inputs are exact pre-fetch architectural states retained from
Mesen 2.1.1 with both production native gates disabled.  They exercise the
live ``$00BD1C -> $00BD1A`` yield path.  One explicitly described derivative
forces the otherwise terminal ``$00BE58`` edge.

Each input is injected unchanged into MAME 0.287's original MC68000 program
and Nexen's production ROM with both native gates truly off or truly on.
Comparison stops before the terminal TRAP #5 executes and includes every D/A
register, CCR/X, exact task-stack bytes, all mapped 16 KiB work RAM, upper
backing conservation, AC charge equality, and halt state.  This is bounded
semantic evidence, not a frame-rate or fresh-boot result.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import time
from pathlib import Path

import validate_1f2e4_native as live
import validate_render_helpers as base
import validate_stage3_hot_handlers as stage3
from mame_0287 import MAME, environment as mame_environment
from mame_0287 import identity as mame_identity


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_FIXTURES = (
    ROOT
    / "build/playtest-investigation-20260725/"
    "stage3-selector-scroll-snes-fixtures-v1"
)
DEFAULT_ROM = ROOT / "build/interp.sfc"
ENTRY_PC = 0x00BD1C
ENTRY_NATIVE = 0x9FB000
YIELD_PC = 0x00BD1A
TERMINAL_PC = 0x00BE58
TERMINAL_MUTATIONS = {
    # After SUB.B #4, this first record is no longer BGT $FFC0.
    0x29B2: bytes.fromhex("ffc0"),
    # Point the list root at a known zero long within mapped work RAM.
    0x2A38: bytes.fromhex("00f03ff0"),
    0x3FF0: bytes.fromhex("00000000"),
}


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def load_cases(
    directory: Path, include_terminal_case: bool
) -> list[stage3.Fixture]:
    cases: list[stage3.Fixture] = []
    for metadata_path in sorted(directory.glob("00bd1c-*/entry.json")):
        metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
        target = int(str(metadata["target"]), 16)
        if target != ENTRY_PC:
            continue
        work_path = metadata_path.with_name("entry.work.bin")
        work = work_path.read_bytes()
        if len(work) != stage3.FULL_WORK_SIZE:
            raise RuntimeError(
                f"{work_path} is {len(work)} bytes; "
                f"expected {stage3.FULL_WORK_SIZE}"
            )
        if hashlib.sha256(work).hexdigest() != metadata["work_sha256"]:
            raise RuntimeError(f"fixture hash mismatch: {work_path}")
        regs = {
            name: int(metadata["regs"][name]) & 0xFFFFFFFF
            for name in base.REG_NAMES
        }
        pre_entry = Path(metadata["pre_entry_state"])
        if not pre_entry.is_file():
            raise RuntimeError(f"missing pre-entry state: {pre_entry}")
        cases.append(
            stage3.Fixture(
                name=metadata_path.parent.name,
                target=ENTRY_PC,
                return_pc=YIELD_PC,
                regs=regs,
                sr=int(metadata["sr"]) & 0xFFFF,
                work=work,
                tick=int(metadata["tick"]),
                frame=int(metadata["frame"]),
                state=int(metadata["state"]),
                substate=int(metadata["substate"]),
                metadata_path=metadata_path,
                pre_entry_state=pre_entry,
                prestate_kind="pre_entry_state",
            )
        )
    if not cases:
        raise RuntimeError(f"no $00BD1C fixtures found in {directory}")
    if include_terminal_case:
        source = cases[0]
        work = bytearray(source.work)
        for offset, replacement in TERMINAL_MUTATIONS.items():
            work[offset : offset + len(replacement)] = replacement
        cases.append(
            stage3.Fixture(
                name=source.name + "-synthetic-terminal",
                target=ENTRY_PC,
                return_pc=TERMINAL_PC,
                regs=dict(source.regs),
                sr=source.sr,
                work=bytes(work),
                tick=source.tick,
                frame=source.frame,
                state=source.state,
                substate=source.substate,
                metadata_path=source.metadata_path,
                pre_entry_state=source.pre_entry_state,
                prestate_kind=source.prestate_kind,
            )
        )
    return cases


def mame_result(
    session: base.MameSession, case: stage3.Fixture
) -> stage3.Result:
    session.pause()
    exit_pc = case.return_pc
    tap_name = f"mcp_bd1c_exit_{exit_pc:06x}"
    session.exec_lua(
        "if MCP_BD1C_EXIT then MCP_BD1C_EXIT:remove() end "
        "MCP_BD1C_EXIT = "
        "machine.devices[':maincpu'].spaces['program']"
        f":install_read_tap(0x{exit_pc:06X}, 0x{exit_pc + 1:06X}, "
        f"'{tap_name}', function(offset, data, mask) return 0x60FE end); "
        "return true"
    )
    session.write_block(
        0xF00000, case.work[: stage3.MAPPED_WORK_SIZE]
    )
    for name in base.REG_NAMES[:-1]:
        session.set_reg(name, case.regs[name])
    entry_sp = case.regs["A7"] & 0xFFFFFF
    session.set_reg("SP", entry_sp)
    session.set_reg("USP", entry_sp)
    session.set_reg("SR", case.sr | 0x0700)
    session.set_reg("PC", ENTRY_PC)
    captured = session.cmd(
        "capture_at_pc",
        pc=exit_pc,
        addr=0xF00000,
        len=stage3.MAPPED_WORK_SIZE,
        nth=2,
        exp_sp=entry_sp,
        maxFrames=180,
        timeout=180,
    )
    session.exec_lua(
        "if MCP_BD1C_EXIT then MCP_BD1C_EXIT:remove(); "
        "MCP_BD1C_EXIT=nil end; return true"
    )
    if not captured.get("registers"):
        raise RuntimeError(
            f"MAME did not reach ${exit_pc:06X} for {case.name}: "
            f"{captured!r}"
        )
    registers = captured["registers"]
    regs = {
        name: int(registers[name]) & 0xFFFFFFFF
        for name in base.REG_NAMES[:-1]
    }
    regs["A7"] = int(registers["SP"]) & 0xFFFFFFFF
    physical_sr = int(registers["SR"]) & 0xFFFF
    isolated_sr = (
        (case.sr & ~(stage3.CCR_MASK | 0x0700))
        | 0x0700
        | (physical_sr & stage3.CCR_MASK)
    )
    return stage3.Result(
        regs=regs,
        sr=isolated_sr,
        work=bytes.fromhex(captured["hex"]),
        usp=int(registers.get("USP", entry_sp)) & 0xFFFFFFFF,
        ac=None,
        cycles=None,
        halt=0,
        observed_pc=exit_pc,
    )


def console_result(
    session: base.McpSession,
    nat: Path,
    case: stage3.Fixture,
    native_gate: int,
    *,
    start_pc: int = stage3.OJMP_HOOK,
) -> stage3.Result:
    stage3.prepare_console(session, nat, case, native_gate)
    exit_pc = case.return_pc
    exit_file_offset = 0x10000 + exit_pc
    illegal_file_offset = stage3.OP_ILLEGAL - 0x8000
    original_exit = bytes(
        session.read_memory("snesPrgRom", exit_file_offset, 2)
    )
    original_illegal = bytes(
        session.read_memory("snesPrgRom", illegal_file_offset, 2)
    )
    if original_exit != bytes.fromhex("4e45"):
        raise RuntimeError(
            f"${exit_pc:06X} is {original_exit.hex()}, expected TRAP #5"
        )
    session.write_memory("snesPrgRom", exit_file_offset, "4afc")
    session.write_memory("snesPrgRom", illegal_file_offset, "80fe")
    hook = session.add_exec_hook(stage3.OP_ILLEGAL, cpu_type="Sa1")
    session.drain_notifications(timeout=0.05)
    live.set_sa1_pc(session, start_pc)
    start_cycles = int(session.get_cpu_state("Sa1")["cycleCount"])
    try:
        hit, _frames = live.run_to_hook(session, hook, attempts=24)
        session.pause()
        end_cycles = int(session.get_cpu_state("Sa1")["cycleCount"])
        observed_pc = live.read_u16(session, 0x40) | (
            (live.read_u16(session, 0x42) & 0xFF) << 16
        )
        if (hit or {}).get("reason") != "hookFired":
            sa1 = session.get_cpu_state("Sa1")
            raise RuntimeError(
                f"Nexen gate={native_gate} did not reach "
                f"${exit_pc:06X} for {case.name}: {hit!r}; "
                f"virtual_pc=${observed_pc:06X}, "
                f"sa1=${int(sa1.get('k', 0)) & 0xFF:02X}:"
                f"{int(sa1.get('pc', 0)) & 0xFFFF:04X}"
            )
        if observed_pc != exit_pc:
            raise RuntimeError(
                f"Nexen gate={native_gate} froze at "
                f"${observed_pc:06X}, expected ${exit_pc:06X}"
            )
        regs = live.captured_regs(session)
        work = bytes(
            session.read_memory(
                base.SNES_SPACE, 0x400000, stage3.FULL_WORK_SIZE
            )
        )
        usp = live.read_u16(session, 0xA4) | (
            live.read_u16(session, 0xA6) << 16
        )
        result = stage3.Result(
            regs=regs,
            sr=(
                (case.sr & ~(stage3.CCR_MASK | 0x0700))
                | ((live.read_u16(session, 0x7C) & 7) << 8)
                | live.captured_ccr(session)
            ),
            work=work,
            usp=usp,
            ac=live.read_u16(session, 0xAC),
            cycles=end_cycles - start_cycles,
            halt=live.read_u16(session, 0x4E),
            observed_pc=observed_pc,
        )
    finally:
        session.remove_hook(hook)
        session.write_memory(
            "snesPrgRom", exit_file_offset, original_exit.hex()
        )
        session.write_memory(
            "snesPrgRom", illegal_file_offset, original_illegal.hex()
        )
    return result


def emit(events: list[dict], event: dict) -> None:
    events.append(event)
    print(json.dumps(event, sort_keys=True), flush=True)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--fixtures", type=Path, default=DEFAULT_FIXTURES)
    parser.add_argument("--rom", type=Path, default=DEFAULT_ROM)
    parser.add_argument("--nexen", type=Path, default=base.DEFAULT_NEXEN)
    parser.add_argument("--nat", type=Path, default=base.DEFAULT_NAT)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--port", type=int, default=9312)
    parser.add_argument(
        "--no-terminal-case",
        action="store_true",
        help="omit the described derivative that reaches $00BE58",
    )
    args = parser.parse_args()
    mame_oracle = mame_identity()
    os.environ.update(mame_environment(os.environ))
    for label, path in (
        ("fixture directory", args.fixtures),
        ("ROM", args.rom),
        ("Nexen", args.nexen),
        ("native base state", args.nat),
    ):
        if not path.exists():
            parser.error(f"missing {label}: {path}")
    if args.output.exists():
        parser.error(f"output already exists: {args.output}")

    cases = load_cases(
        args.fixtures.resolve(), not args.no_terminal_case
    )
    stage3.NATIVE_ENTRIES[ENTRY_PC] = ENTRY_NATIVE
    args.output.parent.mkdir(parents=True, exist_ok=True)
    mame_workdir = (
        args.output.parent / f"{args.output.stem}.mame-session"
    ).resolve()
    if mame_workdir.exists():
        raise RuntimeError(
            f"refusing to reuse MAME IPC directory: {mame_workdir}"
        )
    mame_workdir.mkdir(parents=True)
    mame_states = mame_workdir / "states"
    mame_states.mkdir()

    events: list[dict] = []
    emit(
        events,
        {
            "event": "provenance",
            "scope": (
                "same-state MAME original / Nexen true native-off / "
                "Nexen production native-on $00BD1C scroll-coroutine "
                "differential; all D/A, CCR/X, exact stack, mapped 16 KiB "
                "work RAM, upper-backing conservation, AC equality, halt "
                "state and production route; bounded checkpoint evidence, "
                "not fps or fresh-boot evidence"
            ),
            "mame": str(MAME.resolve()),
            "mame_version": mame_oracle["version"],
            "mame_sha256": mame_oracle["sha256"],
            "mame_snap_revision": mame_oracle["snap_revision"],
            "mame_gnome_content_revision": (
                mame_oracle["gnome_content_revision"]
            ),
            "mame_ipc_workdir": str(mame_workdir),
            "nexen": str(args.nexen.resolve()),
            "nexen_sha256": sha256(args.nexen),
            "rom": str(args.rom.resolve()),
            "rom_sha256": sha256(args.rom),
            "nat": str(args.nat.resolve()),
            "nat_sha256": sha256(args.nat),
            "fixture_directory": str(args.fixtures.resolve()),
            "organic_fixture_count": sum(
                "synthetic" not in case.name for case in cases
            ),
            "derived_terminal_fixture_count": sum(
                "synthetic" in case.name for case in cases
            ),
            "derived_terminal_mutations": {
                f"F0{offset:04X}": replacement.hex()
                for offset, replacement in TERMINAL_MUTATIONS.items()
            },
            "entry_pc": f"{ENTRY_PC:06X}",
            "native_entry": f"{ENTRY_NATIVE:06X}",
            "terminal_pcs": [f"{YIELD_PC:06X}", f"{TERMINAL_PC:06X}"],
            "configurations": {
                "native_off": {"071A": 0, "073A": 0},
                "native_on": {"071A": 1, "073A": 1},
            },
            "boundary_method": (
                "MAME terminal TRAP read is validation-only BRA-to-self and "
                "the second fetch is captured; Nexen terminal TRAP is "
                "validation-only ILLEGAL and state is captured at the stable "
                "pre-op_illegal hook; all patches restored per case"
            ),
            "time": time.time(),
        },
    )

    arcade: dict[str, stage3.Result] = {}
    mame = base.MameSession(
        mame=str(MAME),
        system="superman",
        rompath=str(base.MAME_TRACE / "roms"),
        workdir=str(mame_workdir),
        state_directory=str(mame_states),
        extra_args=["-video", "none", "-sound", "none", "-nothrottle"],
    )
    try:
        mame.launch(boot_wait=25)
        for case in cases:
            arcade[case.name] = mame_result(mame, case)
            emit(
                events,
                {
                    "event": "mame_case",
                    "case": case.name,
                    "terminal_pc": f"{case.return_pc:06X}",
                },
            )
    finally:
        mame.stop()

    stderr_log = (
        args.output.parent / f"{args.output.stem}.nexen.stderr.log"
    )
    with base.McpSession(
        rom=str(args.rom.resolve()),
        mesen=str(args.nexen.resolve()),
        cwd=ROOT,
        port=args.port,
        boot_wait=8.0,
        socket_timeout=240.0,
        stderr_log=stderr_log,
    ) as nexen:
        for case in cases:
            off = console_result(nexen, args.nat.resolve(), case, 0)
            on = console_result(nexen, args.nat.resolve(), case, 1)
            event = stage3.compare_case(
                case, arcade[case.name], off, on
            )
            event["terminal_pc"] = event.pop("return_pc")
            event["fixture_kind"] = (
                "derived_terminal"
                if "synthetic" in case.name
                else "organic_exact_mesen"
            )
            emit(events, event)

        for native_gate in (0, 1):
            event = stage3.route_probe(
                nexen, args.nat.resolve(), cases[0], native_gate
            )
            emit(events, event)

    checks = [
        event
        for event in events
        if event.get("event") in ("case", "route_probe")
    ]
    green = sum(event["result"] == "green" for event in checks)
    summary = {
        "event": "summary",
        "semantic_cases": sum(
            event.get("event") == "case" for event in checks
        ),
        "route_probes": sum(
            event.get("event") == "route_probe" for event in checks
        ),
        "green": green,
        "red": len(checks) - green,
        "total": len(checks),
        "result": "green" if green == len(checks) else "red",
        "time": time.time(),
    }
    emit(events, summary)
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
