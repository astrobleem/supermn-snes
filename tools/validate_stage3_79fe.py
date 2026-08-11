#!/usr/bin/env python3
"""Exact MAME/native-off/native-on validation of the Stage-3 $79FE loop."""

from __future__ import annotations

import argparse
import hashlib
import json
import time
from pathlib import Path

import validate_1f2e4_native as live
import validate_render_helpers as base
import validate_stage3_hot_handlers as stage3


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_FIXTURES = (
    ROOT
    / "build/playtest-investigation-20260725/"
    "stage3-79fe-mame-fixtures-v5"
)
DEFAULT_ROM = ROOT / "build/interp.sfc"
ENTRY_79FE = 0x0079FE
ENTRY_7AC6 = 0x007AC6
TERMINAL_PC = 0x007AC4
NATIVE_ENTRIES = {
    ENTRY_79FE: 0x9FBE00,
    ENTRY_7AC6: 0x9FBE10,
}


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def be16(data: bytes, offset: int) -> int:
    return int.from_bytes(data[offset : offset + 2], "big")


def replace_word(work: bytes, offset: int, value: int) -> bytes:
    result = bytearray(work)
    result[offset : offset + 2] = value.to_bytes(2, "big")
    return bytes(result)


def derivative(
    source: stage3.Fixture,
    *,
    name: str,
    target: int,
    work: bytes | None = None,
    regs: dict[str, int] | None = None,
) -> stage3.Fixture:
    return stage3.Fixture(
        name=name,
        target=target,
        return_pc=TERMINAL_PC,
        regs=dict(source.regs if regs is None else regs),
        sr=source.sr,
        work=source.work if work is None else work,
        tick=source.tick,
        frame=source.frame,
        state=source.state,
        substate=source.substate,
        metadata_path=source.metadata_path,
        pre_entry_state=source.pre_entry_state,
        prestate_kind=source.prestate_kind,
    )


def load_cases(directory: Path) -> list[stage3.Fixture]:
    organic: list[stage3.Fixture] = []
    for metadata_path in sorted(directory.glob("case-0079fe-*.json")):
        metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
        work_path = directory / metadata["work_file"]
        mapped = work_path.read_bytes()
        if len(mapped) != stage3.MAPPED_WORK_SIZE:
            raise RuntimeError(
                f"{work_path} is {len(mapped)} bytes; expected mapped 16 KiB"
            )
        if hashlib.sha256(mapped).hexdigest() != metadata["work_sha256"]:
            raise RuntimeError(f"fixture hash mismatch: {work_path}")
        regs = {
            name: int(metadata["regs"][name]) & 0xFFFFFFFF
            for name in base.REG_NAMES
        }
        state_path = (
            directory
            / "mame-states/superman"
            / f"{metadata['mame_state_name']}.sta"
        )
        if not state_path.is_file():
            raise RuntimeError(f"missing retained MAME prestate: {state_path}")
        padded = mapped + bytes(
            stage3.FULL_WORK_SIZE - stage3.MAPPED_WORK_SIZE
        )
        organic.append(
            stage3.Fixture(
                name=metadata["name"],
                target=ENTRY_79FE,
                return_pc=TERMINAL_PC,
                regs=regs,
                sr=int(metadata["sr"]) & 0xFFFF,
                work=padded,
                tick=int(metadata["frame"]),
                frame=int(metadata["frame"]),
                state=be16(mapped, 0x2930),
                substate=be16(mapped, 0x292C),
                metadata_path=metadata_path,
                pre_entry_state=state_path,
                prestate_kind="mame_save_state_fixture",
            )
        )
    if not organic:
        raise RuntimeError(f"no organic $0079FE fixtures found in {directory}")

    source = organic[0]
    cases = organic
    cases.append(
        derivative(
            source,
            name=source.name + "-resume-7ac6",
            target=ENTRY_7AC6,
        )
    )

    high_regs = dict(source.regs)
    high_regs["D0"] = 0xA5A50000 | (high_regs["D0"] & 0xFFFF)
    high_regs["D2"] = 0xBEEF0000 | (high_regs["D2"] & 0xFFFF)
    cases.extend(
        derivative(
            source,
            name=source.name + f"-high-words-{target:06x}",
            target=target,
            regs=high_regs,
        )
        for target in (ENTRY_79FE, ENTRY_7AC6)
    )

    mode_one = replace_word(source.work, 0x2930, 1)
    a6 = source.regs["A6"] & 0xFFFF
    mode_one = replace_word(mode_one, a6 - 2, 0x0100)
    cases.extend(
        derivative(
            source,
            name=source.name + f"-mode1-fallback-{target:06x}",
            target=target,
            work=mode_one,
        )
        for target in (ENTRY_79FE, ENTRY_7AC6)
    )

    index_d = replace_word(source.work, 0x292C, 0x000D)
    cases.extend(
        derivative(
            source,
            name=source.name + f"-indexd-fallback-{target:06x}",
            target=target,
            work=index_d,
        )
        for target in (ENTRY_79FE, ENTRY_7AC6)
    )
    return cases


def mame_result(
    session: base.MameSession, case: stage3.Fixture
) -> stage3.Result:
    session.pause()
    tap_name = f"mcp_stage3_79_exit_{case.target:06x}"
    session.exec_lua(
        "if MCP_STAGE3_79_EXIT then MCP_STAGE3_79_EXIT:remove() end "
        "MCP_STAGE3_79_EXIT = "
        "machine.devices[':maincpu'].spaces['program']"
        f":install_read_tap(0x{TERMINAL_PC:06X}, "
        f"0x{TERMINAL_PC + 1:06X}, '{tap_name}', "
        "function(offset, data, mask) return 0x60FE end); return true"
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
    session.set_reg("PC", case.target)
    captured = session.cmd(
        "capture_at_pc",
        pc=TERMINAL_PC,
        addr=0xF00000,
        len=stage3.MAPPED_WORK_SIZE,
        nth=2,
        exp_sp=entry_sp,
        maxFrames=180,
        timeout=180,
    )
    session.exec_lua(
        "if MCP_STAGE3_79_EXIT then MCP_STAGE3_79_EXIT:remove(); "
        "MCP_STAGE3_79_EXIT=nil end; return true"
    )
    if not captured.get("registers"):
        raise RuntimeError(
            f"MAME did not reach ${TERMINAL_PC:06X} for {case.name}: "
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
    mapped = bytes.fromhex(captured["hex"])
    return stage3.Result(
        regs=regs,
        sr=isolated_sr,
        work=mapped + case.work[stage3.MAPPED_WORK_SIZE :],
        usp=int(registers.get("USP", entry_sp)) & 0xFFFFFFFF,
        ac=None,
        cycles=None,
        halt=0,
        observed_pc=TERMINAL_PC,
    )


def console_result(
    session: base.McpSession,
    nat: Path,
    case: stage3.Fixture,
    native_gate: int,
) -> stage3.Result:
    stage3.prepare_console(session, nat, case, native_gate)
    exit_file_offset = 0x10000 + TERMINAL_PC
    illegal_file_offset = stage3.OP_ILLEGAL - 0x8000
    original_exit = bytes(
        session.read_memory("snesPrgRom", exit_file_offset, 2)
    )
    original_illegal = bytes(
        session.read_memory("snesPrgRom", illegal_file_offset, 2)
    )
    if original_exit != bytes.fromhex("4e45"):
        raise RuntimeError(
            f"${TERMINAL_PC:06X} is {original_exit.hex()}, expected TRAP #5"
        )
    session.write_memory("snesPrgRom", exit_file_offset, "4afc")
    session.write_memory("snesPrgRom", illegal_file_offset, "80fe")
    hook = session.add_exec_hook(stage3.OP_ILLEGAL, cpu_type="Sa1")
    session.drain_notifications(timeout=0.05)
    live.set_sa1_pc(session, stage3.OJMP_HOOK)
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
                f"${TERMINAL_PC:06X} for {case.name}: {hit!r}; "
                f"virtual_pc=${observed_pc:06X}, "
                f"sa1=${int(sa1.get('k', 0)) & 0xFF:02X}:"
                f"{int(sa1.get('pc', 0)) & 0xFFFF:04X}"
            )
        if observed_pc != TERMINAL_PC:
            raise RuntimeError(
                f"Nexen gate={native_gate} froze at "
                f"${observed_pc:06X}, expected ${TERMINAL_PC:06X}"
            )
        result = stage3.Result(
            regs=live.captured_regs(session),
            sr=(
                (case.sr & ~(stage3.CCR_MASK | 0x0700))
                | ((live.read_u16(session, 0x7C) & 7) << 8)
                | live.captured_ccr(session)
            ),
            work=bytes(
                session.read_memory(
                    base.SNES_SPACE, 0x400000, stage3.FULL_WORK_SIZE
                )
            ),
            usp=live.read_u16(session, 0xA4)
            | (live.read_u16(session, 0xA6) << 16),
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
    parser.add_argument("--port", type=int, default=9362)
    args = parser.parse_args()
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

    cases = load_cases(args.fixtures.resolve())
    stage3.NATIVE_ENTRIES.update(NATIVE_ENTRIES)
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
                "same-state MAME 0.287 original / Nexen true native-off / "
                "Nexen production native-on $0079FE/$007AC6 coroutine "
                "differential; all D/A, CCR/X, exact task stack, mapped "
                "16 KiB work RAM, upper-backing conservation, AC equality, "
                "halt state and production route; bounded evidence, not fps "
                "or fresh-boot evidence"
            ),
            "mame": "/snap/bin/mame 0.287",
            "nexen": str(args.nexen.resolve()),
            "nexen_sha256": sha256(args.nexen),
            "rom": str(args.rom.resolve()),
            "rom_sha256": sha256(args.rom),
            "fixture_directory": str(args.fixtures.resolve()),
            "organic_cases": sum(
                "case-0079fe" in case.name
                and "fallback" not in case.name
                and "high-words" not in case.name
                and "resume" not in case.name
                for case in cases
            ),
            "derived_cases": sum(
                "fallback" in case.name
                or "high-words" in case.name
                or "resume" in case.name
                for case in cases
            ),
            "native_entries": {
                f"{pc:06X}": f"{native:06X}"
                for pc, native in NATIVE_ENTRIES.items()
            },
            "terminal_pc": f"{TERMINAL_PC:06X}",
            "configurations": {
                "native_off": {"071A": 0, "073A": 0},
                "native_on": {"071A": 1, "073A": 1},
            },
            "time": time.time(),
        },
    )

    arcade: dict[str, stage3.Result] = {}
    mame = base.MameSession(
        mame="/snap/bin/mame",
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
                    "target": f"{case.target:06X}",
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
                "organic_mame_entry"
                if case.name.startswith("case-0079fe-")
                and all(
                    marker not in case.name
                    for marker in ("fallback", "high-words", "resume")
                )
                else "explicit_derivative"
            )
            emit(events, event)

        route_fixtures = {
            case.target: case
            for case in cases
            if case.target in NATIVE_ENTRIES
        }
        for target in sorted(route_fixtures):
            for native_gate in (0, 1):
                emit(
                    events,
                    stage3.route_probe(
                        nexen,
                        args.nat.resolve(),
                        route_fixtures[target],
                        native_gate,
                    ),
                )

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
