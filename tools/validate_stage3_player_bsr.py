#!/usr/bin/env python3
"""Three-way differential through real Stage-3 native call instructions.

The six player leaves enter through BSR.  The active `$02E42C` selector instead
enters through `JSR d16(PC)` at `$0278E2`; treating it as a table-dispatch
entry falsely routes the probe through `$00:D1B3`.  Both forms push the same
four-byte return, so the derived pre-call fixture and the comparison contract
are shared, while the retained metadata records the distinct instruction form.
"""

from __future__ import annotations

import argparse
import json
import os
import time
from dataclasses import replace
from pathlib import Path

import validate_1f2e4_native as live
import validate_render_helpers as base
import validate_stage3_hot_handlers as hot
from mame_0287 import MAME, environment as mame_environment
from mame_0287 import identity as mame_identity


ROOT = Path(__file__).resolve().parents[1]
CALL_SITES = {
    # The retained $013282 entries have the genuine BSR return $0126EE on
    # their 68000 stack, so the instruction itself begins four bytes earlier.
    0x013282: 0x0126EA,
    0x013314: 0x0126FE,
    0x01337E: 0x013378,
    0x0133EA: 0x0126DC,
    0x013468: 0x0126D8,
    0x013538: 0x01272A,
}
# The selector has two real PC-relative-JSR callers.  The six retained
# fixtures alternate between them, so the stacked return determines the
# pre-call PC.  Collapsing this to the $0278E2 caller is not a valid replay of
# the $02F2DA state: its callback A0 and post-call continuation are different.
SELECTOR_CALL_SITES = {
    0x0278E6: 0x0278E2,
    0x02F2DE: 0x02F2DA,
}
CALL_KINDS = {
    0x013282: "bsr.w",
    0x013314: "bsr.w",
    0x01337E: "bsr.w",
    0x0133EA: "bsr.w",
    0x013468: "bsr.w",
    0x013538: "bsr.w",
    0x02E42C: "jsr d16(pc)",
}


def call_site_for(fixture: hot.Fixture) -> int:
    """Return the actual call instruction that produced ``fixture``."""

    if fixture.target == 0x02E42C:
        try:
            return SELECTOR_CALL_SITES[fixture.return_pc]
        except KeyError as exc:
            raise RuntimeError(
                f"unknown $02E42C caller return ${fixture.return_pc:06X}"
            ) from exc
    return CALL_SITES[fixture.target]


def pre_call_fixture(fixture: hot.Fixture) -> hot.Fixture:
    """Reconstruct the state immediately before the retained call instruction."""

    regs = dict(fixture.regs)
    regs["A7"] = (regs["A7"] + 4) & 0xFFFFFFFF
    return replace(
        fixture,
        name=fixture.name + "-via-call",
        target=call_site_for(fixture),
        regs=regs,
    )


def native_route_probe(
    session: base.McpSession,
    nat: Path,
    original: hot.Fixture,
    pre_call: hot.Fixture,
) -> dict:
    hot.prepare_console(session, nat, pre_call, 1)
    expected = hot.NATIVE_ENTRIES[original.target]
    # Native player entries live across the complete $92-$9F SA-1 packed
    # region.  Do not apply the old bank-$94-only arithmetic here: it patched
    # a different ROM byte for the bank-$9F entries and could yield a false
    # route result.
    expected_file_offset = hot.sa1_rom_file_offset(expected)
    original_word = bytes(
        session.read_memory("snesPrgRom", expected_file_offset, 2)
    )
    session.write_memory("snesPrgRom", expected_file_offset, "80fe")
    hook = session.add_exec_hook(expected, cpu_type="Sa1")
    session.drain_notifications(timeout=0.05)
    live.set_sa1_pc(session, hot.INEXT)
    start_cycles = int(session.get_cpu_state("Sa1")["cycleCount"])
    try:
        hit = session.run_until(max_frames=8, hook_handle=hook)
        session.pause()
    finally:
        session.remove_hook(hook)
        session.write_memory(
            "snesPrgRom", expected_file_offset, original_word.hex()
        )
    state = session.get_cpu_state("Sa1")
    actual = ((int(state.get("k", 0)) & 0xFF) << 16) | (
        int(state["pc"]) & 0xFFFF
    )
    fired = (hit or {}).get("reason") == "hookFired" and actual == expected
    return {
        "event": "call_route_probe",
        "target": f"{original.target:06X}",
        "call_site": f"{pre_call.target:06X}",
        "native_gate": 1,
        "expected_sa1_pc": f"{expected:06X}",
        "actual_sa1_pc": f"{actual:06X}",
        "hook_fired": fired,
        "cycles": int(session.get_cpu_state("Sa1")["cycleCount"])
        - start_cycles,
        "result": "green" if fired else "red",
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--fixtures", type=Path, required=True)
    parser.add_argument("--rom", type=Path, default=hot.DEFAULT_ROM)
    parser.add_argument("--nexen", type=Path, default=hot.DEFAULT_NEXEN)
    parser.add_argument("--nat", type=Path, default=hot.DEFAULT_NAT)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--port", type=int, default=9054)
    parser.add_argument(
        "--max-cases",
        type=int,
        help="debug-only cap after sorting fixtures",
    )
    args = parser.parse_args()
    # The snap launcher is mutable.  Use the retained MAME 0.287 payload and
    # record its verified identity, matching the other three-way validators.
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

    fixtures = hot.load_fixtures(
        args.fixtures.resolve(),
        set(CALL_SITES) | {0x02E42C},
        args.max_cases,
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
            "same-state MAME original / Nexen native-off / Nexen native-on "
            "differential beginning at the real Stage-3 BSR or JSR d16(PC) "
            "instruction; "
            "all D/A, CCR/X, exact stack and mapped work RAM, upper backing "
            "conservation, AC equality, plus native-on natural-route probes"
        ),
        "call_sites": {
            **{
                f"{target:06X}": {
                    "pc": f"{caller:06X}",
                    "mnemonic": CALL_KINDS[target],
                }
                for target, caller in CALL_SITES.items()
            },
            "02E42C": {
                "pc_by_return": {
                    f"{return_pc:06X}": f"{caller:06X}"
                    for return_pc, caller in SELECTOR_CALL_SITES.items()
                },
                "mnemonic": CALL_KINDS[0x02E42C],
            },
        },
        "fixture_directory": str(args.fixtures.resolve()),
        "fixture_count": len(fixtures),
        "mame": str(MAME.resolve()),
        "mame_version": mame_oracle["version"],
        "mame_sha256": mame_oracle["sha256"],
        "mame_snap_revision": mame_oracle["snap_revision"],
        "mame_gnome_content_revision": (
            mame_oracle["gnome_content_revision"]
        ),
        "nexen": str(args.nexen.resolve()),
        "nexen_sha256": hot.sha256(args.nexen),
        "rom": str(args.rom.resolve()),
        "rom_sha256": hot.sha256(args.rom),
        "nat": str(args.nat.resolve()),
        "nat_sha256": hot.sha256(args.nat),
        "irq_isolation": (
            "bounded spans physically mask level 7; architectural CCR/X "
            "remains part of the comparison"
        ),
        "time": time.time(),
    }
    events.append(provenance)
    print(json.dumps(provenance, sort_keys=True), flush=True)

    arcade: dict[str, hot.Result] = {}
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
        for fixture in fixtures:
            pre_call = pre_call_fixture(fixture)
            arcade[fixture.name] = hot.mame_result(
                mame, pre_call, return_sp_delta=0
            )
            event = {
                "event": "mame_call_case",
                "case": pre_call.name,
                "target": f"{fixture.target:06X}",
                "call_site": f"{pre_call.target:06X}",
                "call_mnemonic": CALL_KINDS[fixture.target],
                "return_pc": f"{fixture.return_pc:06X}",
            }
            events.append(event)
            print(json.dumps(event, sort_keys=True), flush=True)
    finally:
        mame.stop()

    stderr_log = args.output.parent / f"{args.output.stem}.nexen.stderr.log"
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
            pre_call = pre_call_fixture(fixture)
            native_off = hot.console_result(
                nexen,
                args.nat.resolve(),
                pre_call,
                0,
                start_pc=hot.INEXT,
            )
            native_on = hot.console_result(
                nexen,
                args.nat.resolve(),
                pre_call,
                1,
                start_pc=hot.INEXT,
            )
            event = hot.compare_case(
                fixture,
                arcade[fixture.name],
                native_off,
                native_on,
            )
            event["case"] = pre_call.name
            event["entry_mode"] = "real_call_instruction"
            event["call_site"] = f"{pre_call.target:06X}"
            event["call_mnemonic"] = CALL_KINDS[fixture.target]
            events.append(event)
            print(json.dumps(event, sort_keys=True), flush=True)

        seen: set[int] = set()
        for fixture in fixtures:
            if fixture.target in seen:
                continue
            seen.add(fixture.target)
            event = native_route_probe(
                nexen,
                args.nat.resolve(),
                fixture,
                pre_call_fixture(fixture),
            )
            events.append(event)
            print(json.dumps(event, sort_keys=True), flush=True)

    checks = [
        event
        for event in events
        if event.get("event") in ("case", "call_route_probe")
    ]
    green = sum(event["result"] == "green" for event in checks)
    summary = {
        "event": "summary",
        "semantic_cases": sum(
            event.get("event") == "case" for event in checks
        ),
        "route_probes": sum(
            event.get("event") == "call_route_probe" for event in checks
        ),
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
