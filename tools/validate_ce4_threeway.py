#!/usr/bin/env python3
"""Production-route three-way regression for CE4's guarded fast paths.

The broader ``validate_ce4_hle.py`` suite enters the native renderer body
directly.  This companion drives the deterministic clipped 2x2 states and
authenticated Stage-3 3x7 panels through the production virtual-PC dispatcher
so each state is compared in all three required configurations:

* MAME 0.287 executing the original MC68000 routine;
* Nexen with both native gates disabled;
* Nexen with both native gates enabled.

Every D/A register, CCR/X, the exact mapped 16-KiB work image (including the
real stacked return), upper-backing conservation, AC charge, USP, halt state,
and the gate-off/gate-on route are checked.  The inputs are synthetic focused
regressions, not organic fresh-boot or end-to-end performance evidence.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import time
from pathlib import Path

import validate_ce4_hle as ce4
import validate_stage3_hot_handlers as hot


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT = (
    ROOT
    / "build/playtest-investigation-20260725/"
    "ce4-fast-production-threeway.jsonl"
)
RETURN_PC = 0x000600
OP_LINK = 0x009718
FOCUSED_CASES = (
    ce4.FAST_2X2_CASES
    | ce4.FAST_STAGE3_PANEL_CASES
    | ce4.FAST_STAGE3_PANEL_GUARD_MISS_CASES
)


def make_fixture(case: ce4.base.Case, rom: Path) -> hot.Fixture:
    work = bytearray(case.work)
    stack = case.regs["A7"] & 0xFFFF
    work[stack : stack + 4] = ce4.base.be32(RETURN_PC)
    return hot.Fixture(
        name=case.name,
        target=ce4.ENTRY_PC,
        return_pc=RETURN_PC,
        regs=dict(case.regs),
        sr=case.sr,
        work=bytes(work),
        tick=-1,
        frame=-1,
        state=-1,
        substate=-1,
        metadata_path=Path(__file__).resolve(),
        pre_entry_state=rom.resolve(),
    )


def compare_case(
    fixture: hot.Fixture,
    arcade: hot.Result,
    native_off: hot.Result,
    native_on: hot.Result,
) -> dict:
    off_regs, off_work, off_ccr = hot.mismatch_map(arcade, native_off)
    on_regs, on_work, on_ccr = hot.mismatch_map(arcade, native_on)
    off_high = [
        offset
        for offset, (before, after) in enumerate(
            zip(
                fixture.work[hot.MAPPED_WORK_SIZE :],
                native_off.work[hot.MAPPED_WORK_SIZE :],
            ),
            start=hot.MAPPED_WORK_SIZE,
        )
        if before != after
    ]
    on_high = [
        offset
        for offset, (before, after) in enumerate(
            zip(
                fixture.work[hot.MAPPED_WORK_SIZE :],
                native_on.work[hot.MAPPED_WORK_SIZE :],
            ),
            start=hot.MAPPED_WORK_SIZE,
        )
        if before != after
    ]
    ac_match = native_off.ac == native_on.ac
    masks_green = (
        ((native_off.sr >> 8) & 7) == 7
        and ((native_on.sr >> 8) & 7) == 7
    )
    usp_match = native_off.usp == native_on.usp
    halt_clear = native_off.halt == 0 and native_on.halt == 0
    green = not any(
        (
            off_regs,
            off_work,
            off_ccr,
            on_regs,
            on_work,
            on_ccr,
            off_high,
            on_high,
            not ac_match,
            not masks_green,
            not usp_match,
            not halt_clear,
        )
    )
    stack = fixture.regs["A7"] & 0xFFFF
    return {
        "event": "case",
        "case": fixture.name,
        "target": f"{fixture.target:06X}",
        "native_entry": f"{ce4.ENTRY_NATIVE:06X}",
        "return_pc": f"{fixture.return_pc:06X}",
        "input_regs": {
            name: fixture.regs[name] for name in ce4.base.REG_NAMES
        },
        "input_sr": fixture.sr,
        "input_work_sha256": hashlib.sha256(fixture.work).hexdigest(),
        "input_stack_hex": fixture.work[stack : stack + 20].hex(),
        "native_off": {
            "cycles_local": native_off.cycles,
            "ac_after": native_off.ac,
            "register_mismatches": off_regs,
            "ccr_mismatch": off_ccr,
            "mapped_work_mismatch_count": len(off_work),
            "mapped_work_mismatch_first": [
                {
                    "address": f"F0{offset:04X}",
                    "mame": arcade.work[offset],
                    "nexen": native_off.work[offset],
                }
                for offset in off_work[:24]
            ],
            "upper_backing_mutation_count": len(off_high),
            "upper_backing_mutation_first": [
                f"F0{offset:04X}" for offset in off_high[:24]
            ],
        },
        "native_on": {
            "cycles_local": native_on.cycles,
            "ac_after": native_on.ac,
            "register_mismatches": on_regs,
            "ccr_mismatch": on_ccr,
            "mapped_work_mismatch_count": len(on_work),
            "mapped_work_mismatch_first": [
                {
                    "address": f"F0{offset:04X}",
                    "mame": arcade.work[offset],
                    "nexen": native_on.work[offset],
                }
                for offset in on_work[:24]
            ],
            "upper_backing_mutation_count": len(on_high),
            "upper_backing_mutation_first": [
                f"F0{offset:04X}" for offset in on_high[:24]
            ],
        },
        "mame_ccr": arcade.sr & hot.CCR_MASK,
        "native_off_ccr": native_off.sr & hot.CCR_MASK,
        "native_on_ccr": native_on.sr & hot.CCR_MASK,
        "ac_match_off_on": ac_match,
        "interrupt_mask_isolated": {
            "mame_physical": 7,
            "native_off": (native_off.sr >> 8) & 7,
            "native_on": (native_on.sr >> 8) & 7,
        },
        "usp_match_off_on": usp_match,
        "halt_clear": halt_clear,
        "result": "green" if green else "red",
    }


def fetch_route_probe(
    session: ce4.base.McpSession,
    nat: Path,
    fixture: hot.Fixture,
    native_gate: int,
) -> dict:
    """Prove CE4's real fetch-chokepoint route, not a synthetic OJMP reach."""

    hot.prepare_console(session, nat, fixture, native_gate)
    expected = ce4.ENTRY_NATIVE if native_gate else OP_LINK
    if expected >> 16 == 0:
        expected_file_offset = (expected & 0xFFFF) - 0x8000
    else:
        expected_file_offset = 0x2A0000 + (
            ((expected >> 16) - 0x94) * 0x8000
        ) + (expected & 0x7FFF)
    original_word = bytes(
        session.read_memory("snesPrgRom", expected_file_offset, 2)
    )
    session.write_memory("snesPrgRom", expected_file_offset, "80fe")
    hook = session.add_exec_hook(expected, cpu_type="Sa1")
    session.drain_notifications(timeout=0.05)
    hot.live.set_sa1_pc(session, hot.INEXT)
    start_cycles = int(session.get_cpu_state("Sa1")["cycleCount"])
    try:
        hit = session.run_until(max_frames=8, hook_handle=hook)
        session.pause()
    finally:
        session.remove_hook(hook)
        session.write_memory(
            "snesPrgRom", expected_file_offset, original_word.hex()
        )
    actual_state = session.get_cpu_state("Sa1")
    actual_pc = (
        (int(actual_state.get("k", 0)) & 0xFF) << 16
    ) | (int(actual_state["pc"]) & 0xFFFF)
    fired = (hit or {}).get("reason") == "hookFired" and actual_pc == expected
    return {
        "event": "fetch_route_probe",
        "target": f"{fixture.target:06X}",
        "native_gate": native_gate,
        "start_sa1_pc": f"{hot.INEXT:06X}",
        "expected_sa1_pc": f"{expected:06X}",
        "actual_sa1_pc": f"{actual_pc:06X}",
        "hook_fired": fired,
        "cycles": int(session.get_cpu_state("Sa1")["cycleCount"])
        - start_cycles,
        "result": "green" if fired else "red",
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--rom", type=Path, default=ce4.DEFAULT_ROM)
    parser.add_argument("--nexen", type=Path, default=ce4.base.DEFAULT_NEXEN)
    parser.add_argument("--nat", type=Path, default=ce4.base.DEFAULT_NAT)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--port", type=int, default=9064)
    args = parser.parse_args()
    for label, path in (
        ("ROM", args.rom),
        ("Nexen", args.nexen),
        ("native base state", args.nat),
    ):
        if not path.is_file():
            parser.error(f"missing {label}: {path}")
    if args.output.exists():
        parser.error(f"output already exists: {args.output}")

    cases = [
        case
        for case in ce4.make_cases()
        if case.name in FOCUSED_CASES
    ]
    if len(cases) != len(FOCUSED_CASES):
        missing = FOCUSED_CASES - {case.name for case in cases}
        raise RuntimeError(f"missing CE4 fast cases: {sorted(missing)}")
    fixtures = [make_fixture(case, args.rom) for case in cases]

    # Extend the shared route oracle locally; no production source is changed.
    hot.NATIVE_ENTRIES[ce4.ENTRY_PC] = ce4.ENTRY_NATIVE
    events: list[dict] = []
    provenance = {
        "event": "provenance",
        "scope": (
            "synthetic same-state MAME original / Nexen native-off / Nexen "
            "native-on real fetch-chokepoint CE4 clipped-2x2/Stage-3-panel "
            "hit and guard-fallback differential; every "
            "D/A, CCR/X, exact mapped work/stack, upper-backing conservation, "
            "AC equality, USP/halt, and fetch routes; not organic replay "
            "or fps evidence"
        ),
        "console_start": (
            "both Nexen configurations start at inext with virtual PC $000CE4; "
            "native-off reaches op_link while native-on reaches entry_ce4t "
            "through the production post-fetch choke"
        ),
        "configurations": {
            "native_off": {
                "xlat_gate_071a": 0,
                "fetch_chokepoint_gate_073a": 0,
            },
            "native_on": {
                "xlat_gate_071a": 1,
                "fetch_chokepoint_gate_073a": 1,
            },
        },
        "mame": "/snap/bin/mame 0.287",
        "nexen": str(args.nexen.resolve()),
        "nexen_sha256": hot.sha256(args.nexen),
        "rom": str(args.rom.resolve()),
        "rom_sha256": hot.sha256(args.rom),
        "nat": str(args.nat.resolve()),
        "nat_sha256": hot.sha256(args.nat),
        "target": f"{ce4.ENTRY_PC:06X}",
        "native_entry": f"{ce4.ENTRY_NATIVE:06X}",
        "return_pc": f"{RETURN_PC:06X}",
        "case_count": len(fixtures),
        "time": time.time(),
    }
    events.append(provenance)
    print(json.dumps(provenance, sort_keys=True), flush=True)

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
    arcade: dict[str, hot.Result] = {}
    mame = ce4.base.MameSession(
        mame="/snap/bin/mame",
        system="superman",
        rompath=str(ce4.base.MAME_TRACE / "roms"),
        workdir=str(mame_workdir),
        state_directory=str(mame_states),
        extra_args=["-video", "none", "-sound", "none", "-nothrottle"],
    )
    try:
        mame.launch(boot_wait=25)
        for fixture in fixtures:
            arcade[fixture.name] = hot.mame_result(mame, fixture)
            event = {"event": "mame_case", "case": fixture.name}
            events.append(event)
            print(json.dumps(event, sort_keys=True), flush=True)
    finally:
        mame.stop()

    args.output.parent.mkdir(parents=True, exist_ok=True)
    stderr_log = (
        args.output.parent / f"{args.output.stem}.nexen.stderr.log"
    )
    with ce4.base.McpSession(
        rom=str(args.rom.resolve()),
        mesen=str(args.nexen.resolve()),
        cwd=ROOT,
        port=args.port,
        boot_wait=8.0,
        socket_timeout=240.0,
        stderr_log=stderr_log,
    ) as nexen:
        off: dict[str, hot.Result] = {}
        on: dict[str, hot.Result] = {}
        for fixture in fixtures:
            off[fixture.name] = hot.console_result(
                nexen,
                args.nat.resolve(),
                fixture,
                0,
                start_pc=hot.INEXT,
            )
            on[fixture.name] = hot.console_result(
                nexen,
                args.nat.resolve(),
                fixture,
                1,
                start_pc=hot.INEXT,
            )
            event = compare_case(
                fixture,
                arcade[fixture.name],
                off[fixture.name],
                on[fixture.name],
            )
            events.append(event)
            print(json.dumps(event, sort_keys=True), flush=True)

        for native_gate in (0, 1):
            event = fetch_route_probe(
                nexen,
                args.nat.resolve(),
                fixtures[0],
                native_gate,
            )
            events.append(event)
            print(json.dumps(event, sort_keys=True), flush=True)

    checks = [
        event
        for event in events
        if event.get("event") in ("case", "fetch_route_probe")
    ]
    green = sum(event["result"] == "green" for event in checks)
    summary = {
        "event": "summary",
        "semantic_cases": len(fixtures),
        "route_probes": 2,
        "green": green,
        "red": len(checks) - green,
        "total": len(checks),
        "result": "green" if green == len(checks) else "red",
        "time": time.time(),
    }
    events.append(summary)
    print(json.dumps(summary, sort_keys=True), flush=True)
    args.output.write_text(
        "".join(
            json.dumps(event, sort_keys=True) + "\n" for event in events
        ),
        encoding="utf-8",
    )
    return 0 if summary["result"] == "green" else 1


if __name__ == "__main__":
    raise SystemExit(main())
