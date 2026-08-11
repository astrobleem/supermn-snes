#!/usr/bin/env python3
"""Exact three-way validation of Stage-3 BSR-to-native entry shims.

Unlike the target-entry fixtures in ``validate_stage3_hot_handlers.py``, these
cases begin before the real BSR instruction.  They therefore cover return
materialization, stack residue, the bank-$01/$02 BSR dispatch arms, the native
table/rts body, and the return to the original continuation as one unit.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import time
from pathlib import Path

import validate_render_helpers as base
import validate_stage3_hot_handlers as stage3


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_FIXTURES = (
    ROOT
    / "build/playtest-investigation-20260725/"
    "stage3-e49c-bsr-call-fixtures-v4"
)
DEFAULT_ROM = ROOT / "build/interp.sfc"
CALL_SPECS = {
    # call PC: (callee PC, native entry, return PC, exact BSR bytes)
    0x02E4B8: (0x02E49C, 0x94D340, 0x02E4BA, bytes.fromhex("61e2")),
    0x02E4F8: (0x02E49C, 0x94D340, 0x02E4FA, bytes.fromhex("61a2")),
    0x02E524: (
        0x02E49C,
        0x94D340,
        0x02E528,
        bytes.fromhex("6100ff76"),
    ),
    0x02E448: (0x02E40E, 0x94D540, 0x02E44A, bytes.fromhex("61c4")),
    0x0135A8: (
        0x0135E0,
        0x94DB20,
        0x0135AC,
        bytes.fromhex("61000036"),
    ),
    0x0135D0: (
        0x0135E0,
        0x94DB20,
        0x0135D4,
        bytes.fromhex("6100000e"),
    ),
    0x0278E2: (
        0x02E42C,
        0x9FA140,
        0x0278E6,
        bytes.fromhex("4eba6b48"),
    ),
    0x02F2DA: (
        0x02E42C,
        0x9FA140,
        0x02F2DE,
        bytes.fromhex("4ebaf150"),
    ),
    0x0278EE: (
        0x027912,
        0x9FA500,
        0x0278F2,
        bytes.fromhex("61000022"),
    ),
    0x0278F8: (
        0x027912,
        0x9FA500,
        0x0278FC,
        bytes.fromhex("61000018"),
    ),
    0x02F474: (
        0x02F542,
        0x9FFE00,
        0x02F478,
        bytes.fromhex("610000CC"),
    ),
    0x02F506: (
        0x02F542,
        0x9FFE00,
        0x02F50A,
        bytes.fromhex("6100003A"),
    ),
}
CALL_CALLEES = {pc: spec[0] for pc, spec in CALL_SPECS.items()}
CALL_ENTRIES = {pc: spec[1] for pc, spec in CALL_SPECS.items()}
CALL_RETURNS = {pc: spec[2] for pc, spec in CALL_SPECS.items()}
CALL_BYTES = {pc: spec[3] for pc, spec in CALL_SPECS.items()}


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def load_fixtures(directory: Path) -> list[stage3.Fixture]:
    fixtures: list[stage3.Fixture] = []
    for metadata_path in sorted(directory.glob("*/entry.json")):
        metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
        target = int(str(metadata["target"]), 16)
        if target not in CALL_RETURNS:
            continue
        work_path = metadata_path.with_name("entry.work.bin")
        work = work_path.read_bytes()
        if len(work) != stage3.FULL_WORK_SIZE:
            raise RuntimeError(f"short work image: {work_path}")
        if hashlib.sha256(work).hexdigest() != metadata["work_sha256"]:
            raise RuntimeError(f"fixture work hash mismatch: {work_path}")
        regs = {
            name: int(metadata["regs"][name]) & 0xFFFFFFFF
            for name in base.REG_NAMES
        }
        pre_entry = Path(metadata["pre_entry_state"])
        if not pre_entry.is_file():
            raise RuntimeError(f"missing pre-entry state: {pre_entry}")
        a4off = regs["A4"] & 0xFFFF
        fixtures.append(
            stage3.Fixture(
                name=metadata_path.parent.name,
                target=target,
                return_pc=CALL_RETURNS[target],
                regs=regs,
                sr=int(metadata["sr"]) & 0xFFFF,
                work=work,
                tick=int(metadata["tick"]),
                frame=int(metadata["frame"]),
                state=work[(a4off + 0x16) & 0xFFFF],
                substate=work[(a4off + 0x17) & 0xFFFF],
                metadata_path=metadata_path,
                pre_entry_state=pre_entry,
                prestate_kind="pre_entry_state",
            )
        )
    if not fixtures:
        raise RuntimeError(f"no BSR fixtures found in {directory}")
    return fixtures


def bsr_route_probe(
    session: base.McpSession,
    nat: Path,
    fixture: stage3.Fixture,
    native_gate: int,
) -> dict:
    """Prove the pre-BSR route without racing two execution hooks.

    Nexen pauses on any execution hook, even when ``run_until`` names another
    handle.  Use only the native-entry hook.  For gate-on, temporarily spin at
    that entry.  For gate-off, temporarily spin at ``op_illegal`` after the
    patched 68000 continuation reaches it.  The resulting stable PC proves
    either the native route or the complete interpreted return, respectively.
    """

    stage3.prepare_console(session, nat, fixture, native_gate)
    native_entry = CALL_ENTRIES[fixture.target]
    callee = CALL_CALLEES[fixture.target]
    return_file_offset = 0x10000 + fixture.return_pc
    illegal_file_offset = stage3.OP_ILLEGAL - 0x8000
    entry_file_offset = 0x2A0000 + (
        ((native_entry >> 16) - 0x94) * 0x8000
    ) + (native_entry & 0x7FFF)
    saved = {
        "return": bytes(
            session.read_memory("snesPrgRom", return_file_offset, 2)
        ),
        "illegal": bytes(
            session.read_memory("snesPrgRom", illegal_file_offset, 2)
        ),
        "entry": bytes(
            session.read_memory("snesPrgRom", entry_file_offset, 2)
        ),
    }
    session.write_memory("snesPrgRom", return_file_offset, "4afc")
    session.write_memory("snesPrgRom", illegal_file_offset, "80fe")
    session.write_memory("snesPrgRom", entry_file_offset, "80fe")
    expected_pc = native_entry if native_gate else stage3.OP_ILLEGAL
    hook = session.add_exec_hook(expected_pc, cpu_type="Sa1")
    session.drain_notifications(timeout=0.05)
    stage3.live.set_sa1_pc(session, stage3.INEXT)
    start_cycles = int(session.get_cpu_state("Sa1")["cycleCount"])
    try:
        hit, frames_advanced = stage3.live.run_to_hook(
            session, hook, attempts=16
        )
        session.pause()
        sa1 = session.get_cpu_state("Sa1")
        actual_pc = (
            ((int(sa1.get("k", 0)) & 0xFF) << 16)
            | (int(sa1["pc"]) & 0xFFFF)
        )
        virtual_pc = stage3.live.read_u16(session, 0x40) | (
            (stage3.live.read_u16(session, 0x42) & 0xFF) << 16
        )
        regs = stage3.live.captured_regs(session)
        stack_pointer = regs["A7"] & 0xFFFFFF
        residue_offset = (
            stack_pointer if native_gate else stack_pointer - 4
        ) & 0xFFFF
        stacked_return = int.from_bytes(
            bytes(
                session.read_memory(
                    base.SNES_SPACE,
                    0x400000 + residue_offset,
                    4,
                )
            ),
            "big",
        ) & 0xFFFFFF
    finally:
        session.remove_hook(hook)
        session.write_memory(
            "snesPrgRom", return_file_offset, saved["return"].hex()
        )
        session.write_memory(
            "snesPrgRom", illegal_file_offset, saved["illegal"].hex()
        )
        session.write_memory(
            "snesPrgRom", entry_file_offset, saved["entry"].hex()
        )

    expected_sp = (
        fixture.regs["A7"] - 4 if native_gate else fixture.regs["A7"]
    ) & 0xFFFFFF
    fired = (hit or {}).get("reason") == "hookFired"
    route_ok = (
        fired
        and actual_pc == expected_pc
        and virtual_pc
        == (callee if native_gate else fixture.return_pc)
        and stack_pointer == expected_sp
        and stacked_return == fixture.return_pc
    )
    return {
        "native_gate": native_gate,
        "run_reason": (hit or {}).get("reason"),
        "expected_endpoint_hook_fired": fired,
        "hook_kind": "native_entry" if native_gate else "returned_illegal",
        "actual_sa1_pc": f"{actual_pc:06X}",
        "expected_sa1_pc": f"{expected_pc:06X}",
        "virtual_68k_pc": f"{virtual_pc:06X}",
        "stack_pointer": f"{stack_pointer:06X}",
        "expected_stack_pointer": f"{expected_sp:06X}",
        "stacked_return_or_residue": f"{stacked_return:06X}",
        "cycles": int(session.get_cpu_state("Sa1")["cycleCount"])
        - start_cycles,
        "frames_advanced": frames_advanced,
        "result": "green" if route_ok else "red",
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--fixtures", type=Path, default=DEFAULT_FIXTURES)
    parser.add_argument("--rom", type=Path, default=DEFAULT_ROM)
    parser.add_argument("--nexen", type=Path, default=base.DEFAULT_NEXEN)
    parser.add_argument("--nat", type=Path, default=base.DEFAULT_NAT)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--port", type=int, default=9174)
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

    fixtures = load_fixtures(args.fixtures.resolve())
    required_e49c_callers = {0x02E4B8, 0x02E4F8, 0x02E524}
    observed_e49c_callers = {
        fixture.target
        for fixture in fixtures
        if CALL_CALLEES[fixture.target] == 0x02E49C
    }
    if (
        observed_e49c_callers
        and observed_e49c_callers != required_e49c_callers
    ):
        missing = required_e49c_callers - observed_e49c_callers
        raise RuntimeError(
            "$02E49C pre-BSR coverage is incomplete; missing callers "
            + ", ".join(f"${target:06X}" for target in sorted(missing))
        )
    rom = args.rom.read_bytes()
    for target in {fixture.target for fixture in fixtures}:
        offset = 0x10000 + target
        expected = CALL_BYTES[target]
        actual = rom[offset : offset + len(expected)]
        if actual != expected:
            raise RuntimeError(
                f"${target:06X} opcode mismatch: "
                f"{actual.hex()} != {expected.hex()}"
            )

    # Reuse the established complete comparator while identifying every
    # pre-BSR call PC with the one native body that it must reach.
    stage3.NATIVE_ENTRIES.update(CALL_ENTRIES)
    stage3.EXPECTED_RETURNS.update(
        {target: {return_pc} for target, return_pc in CALL_RETURNS.items()}
    )

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
    provenance = {
        "event": "provenance",
        "scope": (
            "pre-BSR same-state MAME original / Nexen true native-off / "
            "Nexen production native-on differential for Stage-3 BSR leaves; "
            "includes BSR decode, exact 24-bit return push/residue, body, "
            "all D/A, CCR/X, mapped work RAM, upper-backing conservation, "
            "AC equality, and native-entry hook; checkpointed, not fps or "
            "fresh-boot evidence"
        ),
        "fixtures": str(args.fixtures.resolve()),
        "fixture_count": len(fixtures),
        "e49c_required_callers": [
            f"{target:06X}" for target in sorted(required_e49c_callers)
        ],
        "e49c_observed_callers": [
            f"{target:06X}" for target in sorted(observed_e49c_callers)
        ],
        "call_returns": {
            f"{target:06X}": f"{return_pc:06X}"
            for target, return_pc in CALL_RETURNS.items()
            if any(fixture.target == target for fixture in fixtures)
        },
        "rom": str(args.rom.resolve()),
        "rom_sha256": sha256(args.rom),
        "nexen": str(args.nexen.resolve()),
        "nexen_sha256": sha256(args.nexen),
        "nat": str(args.nat.resolve()),
        "nat_sha256": sha256(args.nat),
        "mame": "/snap/bin/mame 0.287",
        "mame_ipc_workdir": str(mame_workdir),
        "native_entries": {
            f"{target:06X}": f"{CALL_ENTRIES[target]:06X}"
            for target in sorted({fixture.target for fixture in fixtures})
        },
        "callees": {
            f"{target:06X}": f"{CALL_CALLEES[target]:06X}"
            for target in sorted({fixture.target for fixture in fixtures})
        },
        "time": time.time(),
    }
    events.append(provenance)
    print(json.dumps(provenance, sort_keys=True), flush=True)

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
        for fixture in fixtures:
            arcade[fixture.name] = stage3.mame_result(
                mame, fixture, return_sp_delta=0
            )
            event = {
                "event": "mame_case",
                "case": fixture.name,
                "call_pc": f"{fixture.target:06X}",
                "stop_pc": f"{fixture.return_pc:06X}",
            }
            events.append(event)
            print(json.dumps(event, sort_keys=True), flush=True)
    finally:
        mame.stop()

    checks: list[dict] = []
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
        for fixture in fixtures:
            route_off = bsr_route_probe(
                nexen, args.nat.resolve(), fixture, 0
            )
            route_on = bsr_route_probe(
                nexen, args.nat.resolve(), fixture, 1
            )
            off = stage3.console_result(
                nexen,
                args.nat.resolve(),
                fixture,
                0,
                start_pc=stage3.INEXT,
            )
            on = stage3.console_result(
                nexen,
                args.nat.resolve(),
                fixture,
                1,
                start_pc=stage3.INEXT,
            )
            event = stage3.compare_case(
                fixture, arcade[fixture.name], off, on
            )
            event["event"] = "bsr_case"
            event["call_pc"] = event.pop("target")
            event["stop_pc"] = event.pop("return_pc")
            event["bsr_route"] = {
                "native_off": route_off,
                "native_on": route_on,
            }
            route_green = (
                route_off["result"] == "green"
                and route_on["result"] == "green"
            )
            if not route_green:
                event["result"] = "red"
            event["bsr_route_result"] = (
                "green" if route_green else "red"
            )
            checks.append(event)
            events.append(event)
            print(json.dumps(event, sort_keys=True), flush=True)

    green = sum(event["result"] == "green" for event in checks)
    summary = {
        "event": "summary",
        "cases": len(checks),
        "green": green,
        "red": len(checks) - green,
        "result": "green" if green == len(checks) else "red",
        "time": time.time(),
    }
    events.append(summary)
    print(json.dumps(summary, sort_keys=True), flush=True)
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
