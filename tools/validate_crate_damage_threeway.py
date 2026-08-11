#!/usr/bin/env python3
"""Exact held/thrown crate damage chain across arcade and both SNES paths.

This regression deliberately splits the chain at its two independently
callable roots:

* $025110 emits collision response $2000 for a carried crate and $2001 for a
  thrown crate.  It must not write enemy health.
* $01E7C0 consumes that response.  $2000 records contact without damage;
  $2001 subtracts one health point.

Each held/thrown fixture runs in original MAME 0.287, in Nexen through the
fully interpreted root with all escape gates disabled, and in Nexen through
the production native root.  The existing root validators compare all D/A
registers, CCR/X/mask, stack residue, and mapped work RAM.  This wrapper adds
explicit collision-field and health-write assertions and retains portable
entry fixtures plus configured Nexen pre-entry states.

The two roots use different organic register/stack contexts, so this is
bounded function-semantic evidence, not an organic carried-flight replay or
IRQ-cadence proof.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import time
from pathlib import Path
from typing import Any, Callable

import validate_1e7c0_native as consumer
import validate_25110_native as emitter
from mame_0287 import MAME, environment as mame_environment
from mame_0287 import identity as mame_identity


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_ROM = ROOT / "build/interp.sfc"
DEFAULT_NEXEN = Path(
    "/mnt/sdc1/Nexen-r5-20260712/bin/linux-x64/Release/"
    "mcp-exact-count-publish/Nexen"
)
DEFAULT_NAT = Path("/tmp/b0_native.mss")
DEFAULT_EMITTER_FIXTURES = (
    ROOT
    / "build/playability-20260720/"
    "25110-final832-current-mame-v1/results-fixtures"
)
DEFAULT_CONSUMER_FIXTURES = (
    ROOT
    / "build/playtest-investigation-20260725/"
    "1e7c0-organic-tick2927-8047348-production-v6-fixtures"
)

WORK_BASE = 0xF00000
SNES_WORK_BASE = 0x400000
HEALTH_OFFSET = 0x02DD
LAST_CONTACT_OFFSET = 0x02E0
TASK_MASK_OFFSET = 0x0002
TICK_OFFSET = 0x1C56
CRATE_RECORD_OFFSET = 0x3744
TARGET_RECORD_OFFSET = 0x3A74
COLLISION_CLEAR_START = 0x3734
COLLISION_CLEAR_END = 0x3CC4
RESPONSE_OFFSET = 0x0C
PEER_OFFSET = 0x0E
TYPE_OFFSET = 0x0A
HELD_RESPONSE = 0x2000
THROWN_RESPONSE = 0x2001
CRATE_TYPE = 0x8039
TARGET_TYPE = 0x0060
MAME_DAMAGE_PC = 0x01EA4E


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def be16(data: bytes, offset: int) -> int:
    return (data[offset] << 8) | data[offset + 1]


def put_be16(data: bytearray, offset: int, value: int) -> None:
    data[offset : offset + 2] = int(value & 0xFFFF).to_bytes(2, "big")


def record(
    *,
    active: int,
    x1: int,
    x2: int,
    y1: int,
    y2: int,
    object_type: int,
    response: int = 0,
    peer: int = 0,
) -> bytes:
    return b"".join(
        int(value & 0xFFFF).to_bytes(2, "big")
        for value in (
            active,
            x1,
            x2,
            y1,
            y2,
            object_type,
            response,
            peer,
        )
    )


def derive_emitter_cases(
    seed: emitter.shared.LiveCase,
    object_seed: consumer.LiveCase,
) -> list[emitter.shared.LiveCase]:
    cases: list[emitter.shared.LiveCase] = []
    for name, response in (
        ("held-response-2000", HELD_RESPONSE),
        ("thrown-response-2001", THROWN_RESPONSE),
    ):
        # Use the organic object/list context that the consumer will run
        # against, while retaining the independently authenticated $025110
        # register/SR/stack entry.  Isolate one owner in the eight-slot list
        # and one crate/target overlap so no unrelated collision can satisfy
        # the fixture.
        work = bytearray(object_seed.work)
        list_offset = ((object_seed.regs["A6"] & 0xFFFF) - 0x20) & 0xFFFF
        work[list_offset : list_offset + 0x20] = bytes(0x20)
        work[list_offset : list_offset + 4] = (0x00F002DA).to_bytes(
            4, "big"
        )
        work[COLLISION_CLEAR_START:COLLISION_CLEAR_END] = bytes(
            COLLISION_CLEAR_END - COLLISION_CLEAR_START
        )
        work[
            CRATE_RECORD_OFFSET : CRATE_RECORD_OFFSET
            + emitter.COLLISION_RECORD_SIZE
        ] = record(
            active=1,
            x1=0x00EA,
            x2=0x0116,
            y1=0x0044,
            y2=0x006A,
            object_type=CRATE_TYPE,
            response=response,
        )
        work[
            TARGET_RECORD_OFFSET : TARGET_RECORD_OFFSET
            + emitter.COLLISION_RECORD_SIZE
        ] = record(
            active=1,
            x1=0x010E,
            x2=0x0117,
            y1=0x0025,
            y2=0x0056,
            object_type=TARGET_TYPE,
        )
        work[HEALTH_OFFSET] = 1
        work[LAST_CONTACT_OFFSET] = 0
        cases.append(
            emitter.shared.LiveCase(
                name=f"crate-emitter-{name}",
                regs=dict(seed.regs),
                sr=seed.sr,
                work=bytes(work),
                tick=seed.tick,
                exit_pc=seed.exit_pc,
            )
        )
    differences = [
        offset
        for offset, (held, thrown) in enumerate(
            zip(cases[0].work, cases[1].work)
        )
        if held != thrown
    ]
    if differences != [CRATE_RECORD_OFFSET + RESPONSE_OFFSET + 1]:
        raise RuntimeError(
            "emitter pair must differ only in the crate response low byte: "
            f"{[f'F0{offset:04X}' for offset in differences]}"
        )
    return cases


def derive_consumer_cases(
    seed: consumer.LiveCase,
    emitter_cases: list[emitter.shared.LiveCase],
    mame_results: dict[str, Any],
) -> list[consumer.LiveCase]:
    cases: list[consumer.LiveCase] = []
    for emitter_case in emitter_cases:
        # Stage-one exact equality is a hard gate.  Feed its canonical MAME
        # mapped-work output to all three consumer arms, overlaid onto the
        # common 64 KiB input so upper private work remains byte-identical.
        work = bytearray(emitter_case.work)
        work[: consumer.MAPPED_WORK_SIZE] = mame_results[
            emitter_case.name
        ].work
        reasons = consumer.hot_guard_reasons(seed.regs, bytes(work))
        if reasons:
            raise RuntimeError(
                f"derived consumer case fails native guard: {reasons}"
            )
        cases.append(
            consumer.LiveCase(
                name=emitter_case.name.replace(
                    "crate-emitter-", "crate-consumer-"
                ),
                regs=dict(seed.regs),
                sr=seed.sr,
                work=bytes(work),
                tick=seed.tick,
            )
        )
    for case, response in zip(
        cases, (HELD_RESPONSE, THROWN_RESPONSE)
    ):
        if (
            be16(case.work, TARGET_RECORD_OFFSET + RESPONSE_OFFSET)
            != response
            or be16(case.work, TARGET_RECORD_OFFSET + PEER_OFFSET)
            != CRATE_TYPE
            or case.work[HEALTH_OFFSET] != 1
        ):
            raise RuntimeError(
                f"{case.name}: canonical post-$025110 consumer input is "
                "missing response/peer/health contract"
            )
    return cases


def retain_case(output: Path, index: int, case: Any) -> dict[str, Any]:
    output.mkdir(parents=True, exist_ok=True)
    work_path = output / f"case-{index:02d}.work.bin"
    metadata_path = output / f"case-{index:02d}.json"
    work_path.write_bytes(case.work)
    metadata = {
        "name": case.name,
        "regs": case.regs,
        "sr": case.sr,
        "tick": case.tick,
        "work_sha256": hashlib.sha256(case.work).hexdigest(),
        "work_path": str(work_path.resolve()),
    }
    metadata_path.write_text(
        json.dumps(metadata, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return {
        **metadata,
        "metadata_path": str(metadata_path.resolve()),
        "metadata_sha256": sha256(metadata_path),
    }


def new_mame_session() -> Any:
    base = emitter.base
    return base.MameSession(
        mame=str(MAME),
        system="superman",
        rompath=str(base.MAME_TRACE / "roms"),
        workdir=str(base.MAME_TRACE),
        state_directory=str(base.MAME_TRACE / "sta"),
        extra_args=["-video", "none", "-sound", "none", "-nothrottle"],
    )


def mame_health_capture(
    session: Any,
    runner: Callable[[], Any],
) -> tuple[Any, list[dict[str, Any]]]:
    installed = session.exec_lua(
        "if MCP_CRATE_HEALTH_TAP then MCP_CRATE_HEALTH_TAP:remove() end; "
        "MCP_CRATE_HEALTH_EVENTS={}; "
        "local cpu=M.devices[':maincpu']; "
        "local prog=cpu.spaces['program']; "
        "MCP_CRATE_HEALTH_TAP=prog:install_write_tap("
        f"0x{WORK_BASE + HEALTH_OFFSET - 1:06X},"
        f"0x{WORK_BASE + HEALTH_OFFSET:06X},"
        "'mcp_crate_health',function(offset,data,mask) "
        "MCP_CRATE_HEALTH_EVENTS[#MCP_CRATE_HEALTH_EVENTS+1]={"
        "offset=offset,data=data,mask=mask,"
        "pc=cpu.state['PC'].value & 0xFFFFFF,"
        "sr=cpu.state['SR'].value & 0xFFFF}; "
        "return data end); return true"
    )
    if installed is not True:
        raise RuntimeError("MAME health write tap did not install")
    try:
        result = runner()
        writes = session.exec_lua(
            "local answer=MCP_CRATE_HEALTH_EVENTS or {}; "
            "if MCP_CRATE_HEALTH_TAP then "
            "MCP_CRATE_HEALTH_TAP:remove(); "
            "MCP_CRATE_HEALTH_TAP=nil end; "
            "MCP_CRATE_HEALTH_EVENTS=nil; return answer"
        )
    except Exception:
        session.exec_lua(
            "if MCP_CRATE_HEALTH_TAP then "
            "MCP_CRATE_HEALTH_TAP:remove(); "
            "MCP_CRATE_HEALTH_TAP=nil end; "
            "MCP_CRATE_HEALTH_EVENTS=nil; return true"
        )
        raise
    if not isinstance(writes, list):
        raise RuntimeError(f"unexpected MAME write events: {writes!r}")
    # The fixture loader writes the complete work image while the injected
    # CPU is parked in MAME's $003FF0 safe loop.  Those setup writes are not
    # execution of either audited root.  Retain every write outside that
    # isolated loader PC range, including any unexpected health writer.
    execution_writes = [
        dict(row)
        for row in writes
        if not 0x003F00 <= int(row.get("pc", -1)) <= 0x003FFF
    ]
    return result, execution_writes


def compact_hook_events(
    rows: list[dict[str, Any]], handle: int
) -> list[dict[str, Any]]:
    answer: list[dict[str, Any]] = []
    for row in rows:
        if row.get("method") != "notifications/mesen/hookFired":
            continue
        params = row.get("params", {})
        if int(params.get("handle", -1)) != handle:
            continue
        answer.append(
            {
                key: params[key]
                for key in (
                    "address",
                    "value",
                    "pc",
                    "cycleCount",
                    "cpuType",
                    "operation",
                )
                if key in params
            }
        )
    return answer


def nexen_watched_run(
    session: Any,
    root_address: int,
    runner: Callable[[], Any],
) -> tuple[Any, list[dict[str, Any]], list[dict[str, Any]]]:
    root_hook = session.add_exec_hook(root_address, cpu_type="Sa1")
    health_hook = session.add_write_hook(
        SNES_WORK_BASE + HEALTH_OFFSET,
        cpu_type="Sa1",
    )
    session.drain_notifications(timeout=0.05)
    try:
        result = runner()
        rows = session.drain_notifications(timeout=0.1)
    finally:
        session.remove_hook(root_hook)
        session.remove_hook(health_hook)
        rows = locals().get("rows", []) + session.drain_notifications(
            timeout=0.05
        )
    return (
        result,
        compact_hook_events(rows, root_hook),
        compact_hook_events(rows, health_hook),
    )


def emitter_semantics(
    result: Any,
    expected_response: int,
    health_writes: list[dict[str, Any]],
) -> tuple[dict[str, Any], bool]:
    work = result.work
    checks = {
        "target_response": (
            be16(work, TARGET_RECORD_OFFSET + RESPONSE_OFFSET)
            == expected_response
        ),
        "target_damage_byte": (
            work[TARGET_RECORD_OFFSET + RESPONSE_OFFSET + 1]
            == (expected_response & 0xFF)
        ),
        "target_peer_is_crate": (
            be16(work, TARGET_RECORD_OFFSET + PEER_OFFSET) == CRATE_TYPE
        ),
        "crate_peer_is_target": (
            be16(work, CRATE_RECORD_OFFSET + PEER_OFFSET) == TARGET_TYPE
        ),
        "enemy_health_unchanged": work[HEALTH_OFFSET] == 1,
        "zero_health_writes": len(health_writes) == 0,
    }
    return (
        {
            "checks": checks,
            "response": be16(
                work, TARGET_RECORD_OFFSET + RESPONSE_OFFSET
            ),
            "damage": work[
                TARGET_RECORD_OFFSET + RESPONSE_OFFSET + 1
            ],
            "target_peer": be16(
                work, TARGET_RECORD_OFFSET + PEER_OFFSET
            ),
            "crate_peer": be16(
                work, CRATE_RECORD_OFFSET + PEER_OFFSET
            ),
            "health": work[HEALTH_OFFSET],
            "health_writes": health_writes,
            "task_mask": be16(work, TASK_MASK_OFFSET),
            "tick": be16(work, TICK_OFFSET),
            "collision_sha256": hashlib.sha256(
                work[COLLISION_CLEAR_START:COLLISION_CLEAR_END]
            ).hexdigest(),
        },
        all(checks.values()),
    )


def consumer_semantics(
    result: Any,
    *,
    thrown: bool,
    health_writes: list[dict[str, Any]],
    mame: bool,
) -> tuple[dict[str, Any], bool]:
    work = result.work
    expected_health = 0 if thrown else 1
    expected_writes = 1 if thrown else 0
    write_values = [
        int(row.get("data" if mame else "value", -1)) & 0xFF
        for row in health_writes
    ]
    checks = {
        "peer_consumed": (
            be16(work, TARGET_RECORD_OFFSET + PEER_OFFSET) == 0
        ),
        "last_contact_recorded": (
            work[LAST_CONTACT_OFFSET] == (CRATE_TYPE & 0xFF)
        ),
        "health": work[HEALTH_OFFSET] == expected_health,
        "health_write_count": len(health_writes) == expected_writes,
        "health_write_value": (
            write_values == ([0] if thrown else [])
        ),
    }
    if mame:
        checks["mame_damage_pc"] = [
            int(row.get("pc", -1)) for row in health_writes
        ] == ([MAME_DAMAGE_PC] if thrown else [])
    return (
        {
            "checks": checks,
            "response": be16(
                work, TARGET_RECORD_OFFSET + RESPONSE_OFFSET
            ),
            "peer": be16(work, TARGET_RECORD_OFFSET + PEER_OFFSET),
            "last_contact": work[LAST_CONTACT_OFFSET],
            "health": work[HEALTH_OFFSET],
            "health_writes": health_writes,
            "task_mask": be16(work, TASK_MASK_OFFSET),
            "tick": be16(work, TICK_OFFSET),
            "owner_record_sha256": hashlib.sha256(
                work[0x02DA:0x0344]
            ).hexdigest(),
            "collision_sha256": hashlib.sha256(
                work[COLLISION_CLEAR_START:COLLISION_CLEAR_END]
            ).hexdigest(),
        },
        all(checks.values()),
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--rom", type=Path, default=DEFAULT_ROM)
    parser.add_argument("--nexen", type=Path, default=DEFAULT_NEXEN)
    parser.add_argument("--nat", type=Path, default=DEFAULT_NAT)
    parser.add_argument(
        "--emitter-fixtures",
        type=Path,
        default=DEFAULT_EMITTER_FIXTURES,
    )
    parser.add_argument(
        "--consumer-fixtures",
        type=Path,
        default=DEFAULT_CONSUMER_FIXTURES,
    )
    parser.add_argument("--port", type=int, default=9510)
    parser.add_argument("--max-handoffs", type=int, default=20000)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    mame_oracle = mame_identity()
    os.environ.update(mame_environment(os.environ))
    for path in (
        args.rom,
        args.nexen,
        args.nat,
        args.emitter_fixtures,
        args.consumer_fixtures,
        consumer.DEFAULT_INTERP_SYM,
    ):
        if not path.exists():
            parser.error(f"missing required input: {path}")
    if args.output.exists():
        parser.error(f"output already exists: {args.output}")
    if args.max_handoffs < 1024:
        parser.error("--max-handoffs must be at least 1024")

    args.output.mkdir(parents=True)
    fixture_root = args.output / "portable-fixtures"
    prestate_root = args.output / "prestates"
    events: list[dict[str, Any]] = []
    provenance = {
        "event": "provenance",
        "scope": (
            "bounded held/thrown crate collision-emitter and damage-consumer "
            "three-way differential; not organic flight, IRQ cadence, or fps"
        ),
        "rom": str(args.rom.resolve()),
        "rom_sha256": sha256(args.rom),
        "nexen": str(args.nexen.resolve()),
        "nexen_sha256": sha256(args.nexen),
        "nexen_control_extension": (
            "MCP-private counted synchronous pre-opcode stop; emulator "
            "execution semantics and production ROM are unchanged"
        ),
        "nat": str(args.nat.resolve()),
        "nat_sha256": sha256(args.nat),
        "mame": mame_oracle,
        "mame_rom_set": str(
            (ROOT / "tools/mame-trace/roms/superman.zip").resolve()
        ),
        "mame_rom_set_sha256": sha256(
            ROOT / "tools/mame-trace/roms/superman.zip"
        ),
        "configurations": [
            "mame-original",
            "nexen-root-interpreted-gates-0-0",
            "nexen-production-native-gates-1-1",
        ],
        "irq_scope": (
            "both root validators isolate unrelated IRQ delivery; task mask "
            "and tick remain inside exact mapped-work comparison"
        ),
        "emitter_seed": str(args.emitter_fixtures.resolve()),
        "consumer_seed": str(args.consumer_fixtures.resolve()),
        "time": time.time(),
    }
    events.append(provenance)
    print(json.dumps(provenance, sort_keys=True), flush=True)

    emitter_seed = emitter.load_cases(args.emitter_fixtures, 1)[0]
    consumer_seed = consumer.load_fixture_cases(
        args.consumer_fixtures, 1
    )[0]
    emitter_cases = derive_emitter_cases(emitter_seed, consumer_seed)
    for index, case in enumerate(emitter_cases):
        event = {
            "event": "fixture",
            "stage": "emitter",
            **retain_case(fixture_root / "emitter", index, case),
        }
        events.append(event)
        print(json.dumps(event, sort_keys=True), flush=True)

    mame_emitter: dict[str, Any] = {}
    mame_emitter_writes: dict[str, list[dict[str, Any]]] = {}
    for case in emitter_cases:
        mame_session = new_mame_session()
        try:
            mame_session.launch(boot_wait=25)
            result, writes = mame_health_capture(
                mame_session,
                lambda case=case: emitter.mame_result(mame_session, case),
            )
            mame_emitter[case.name] = result
            mame_emitter_writes[case.name] = writes
        finally:
            mame_session.stop()
        expected_response = (
            THROWN_RESPONSE if "thrown" in case.name else HELD_RESPONSE
        )
        semantic, green = emitter_semantics(
            result, expected_response, writes
        )
        event = {
            "event": "oracle_case",
            "stage": "emitter",
            "case": case.name,
            "configuration": "mame-original",
            "semantics": semantic,
            "result": "green" if green else "red",
        }
        events.append(event)
        print(json.dumps(event, sort_keys=True), flush=True)

    if any(
        event["result"] != "green"
        for event in events
        if event.get("event") == "oracle_case"
        and event.get("stage") == "emitter"
    ):
        raise RuntimeError(
            "MAME $025110 oracle failed the held/thrown emitter contract"
        )

    consumer_cases = derive_consumer_cases(
        consumer_seed, emitter_cases, mame_emitter
    )
    for index, case in enumerate(consumer_cases):
        event = {
            "event": "fixture",
            "stage": "consumer",
            "canonical_source": (
                "mapped 16 KiB output of the matching MAME $025110 case"
            ),
            **retain_case(fixture_root / "consumer", index, case),
        }
        events.append(event)
        print(json.dumps(event, sort_keys=True), flush=True)

    mame_consumer: dict[str, Any] = {}
    mame_consumer_writes: dict[str, list[dict[str, Any]]] = {}
    for case in consumer_cases:
        mame_session = new_mame_session()
        try:
            mame_session.launch(boot_wait=25)
            pair, writes = mame_health_capture(
                mame_session,
                lambda case=case: consumer.mame_result(mame_session, case),
            )
            result, sr_reads = pair
            mame_consumer[case.name] = result
            mame_consumer_writes[case.name] = writes
        finally:
            mame_session.stop()
        semantic, green = consumer_semantics(
            result,
            thrown="thrown" in case.name,
            health_writes=writes,
            mame=True,
        )
        event = {
            "event": "oracle_case",
            "stage": "consumer",
            "case": case.name,
            "configuration": "mame-original",
            "irq_isolation_sr_reads": sr_reads,
            "semantics": semantic,
            "result": "green" if green else "red",
        }
        events.append(event)
        print(json.dumps(event, sort_keys=True), flush=True)

    interp_sym = consumer.DEFAULT_INTERP_SYM
    test_idle = consumer.symbol_offset(interp_sym, "test_idle")
    inext = consumer.symbol_offset(interp_sym, "inext")
    debug_spin = consumer.symbol_offset(interp_sym, "df_spin")

    with emitter.base.McpSession(
        rom=str(args.rom.resolve()),
        mesen=str(args.nexen.resolve()),
        cwd=ROOT,
        port=args.port,
        boot_wait=8.0,
        socket_timeout=300.0,
        stderr_log=args.output / "emitter.nexen.stderr.log",
    ) as nexen:
        for case in emitter_cases:
            expected_response = (
                THROWN_RESPONSE if "thrown" in case.name else HELD_RESPONSE
            )
            for root_native in (False, True):
                configuration = (
                    "nexen-production-native-gates-1-1"
                    if root_native
                    else "nexen-root-interpreted-gates-0-0"
                )
                pre_state = (
                    prestate_root
                    / "emitter"
                    / configuration
                    / f"{case.name}.mss"
                )
                pair, root_hits, health_writes = nexen_watched_run(
                    nexen,
                    emitter.ENTRY_NATIVE,
                    lambda case=case, root_native=root_native,
                    pre_state=pre_state: emitter.nexen_result(
                        nexen,
                        args.nat,
                        case,
                        native=root_native,
                        pre_state=pre_state,
                        choke_gate=1 if root_native else 0,
                        boundary_tool="run_to_exact_exec_stop",
                    ),
                )
                result, pre_state_info = pair
                exact = emitter.shared.compare(
                    case,
                    mame_emitter[case.name],
                    result,
                    1 if root_native else 0,
                    1 if root_native else 0,
                )
                semantic, semantic_green = emitter_semantics(
                    result, expected_response, health_writes
                )
                root_green = (
                    len(root_hits) >= 1 if root_native else len(root_hits) == 0
                )
                green = (
                    exact["result"] == "green"
                    and semantic_green
                    and root_green
                )
                event = {
                    "event": "threeway_case",
                    "stage": "emitter",
                    "case": case.name,
                    "configuration": configuration,
                    "root_native": root_native,
                    "root_hits": root_hits,
                    "root_hook_check": root_green,
                    "health_writes": health_writes,
                    "pre_state": pre_state_info,
                    "exact": exact,
                    "semantics": semantic,
                    "result": "green" if green else "red",
                }
                events.append(event)
                print(json.dumps(event, sort_keys=True), flush=True)

    with emitter.base.McpSession(
        rom=str(args.rom.resolve()),
        mesen=str(args.nexen.resolve()),
        cwd=ROOT,
        port=args.port + 1,
        boot_wait=8.0,
        socket_timeout=300.0,
        stderr_log=args.output / "consumer.nexen.stderr.log",
    ) as nexen:
        for case in consumer_cases:
            for root_native in (False, True):
                configuration = (
                    "nexen-production-native-gates-1-1"
                    if root_native
                    else "nexen-root-interpreted-gates-0-0"
                )
                pre_state = (
                    prestate_root
                    / "consumer"
                    / configuration
                    / f"{case.name}.mss"
                )
                pair, root_hits, health_writes = nexen_watched_run(
                    nexen,
                    consumer.ENTRY_NATIVE,
                    lambda case=case, root_native=root_native,
                    pre_state=pre_state: consumer.nexen_result(
                        nexen,
                        args.nat,
                        case,
                        xlat_gate=1 if root_native else 0,
                        choke_gate=1 if root_native else 0,
                        test_idle=test_idle,
                        inext=inext,
                        debug_spin=debug_spin,
                        diagnostic_fetch_freeze=False,
                        root_native=root_native,
                        max_handoffs=args.max_handoffs,
                        pre_state=pre_state,
                        terminal_illegal=True,
                        boundary_tool="run_to_exact_exec_stop",
                    ),
                )
                result, boundary = pair
                exact = consumer.compare(
                    case,
                    mame_consumer[case.name],
                    result,
                    1 if root_native else 0,
                    1 if root_native else 0,
                    boundary,
                )
                semantic, semantic_green = consumer_semantics(
                    result,
                    thrown="thrown" in case.name,
                    health_writes=health_writes,
                    mame=False,
                )
                root_green = (
                    len(root_hits) >= 1 if root_native else len(root_hits) == 0
                )
                green = (
                    exact["result"] == "green"
                    and semantic_green
                    and root_green
                )
                event = {
                    "event": "threeway_case",
                    "stage": "consumer",
                    "case": case.name,
                    "configuration": configuration,
                    "root_native": root_native,
                    "root_hits": root_hits,
                    "root_hook_check": root_green,
                    "health_writes": health_writes,
                    "exact": exact,
                    "semantics": semantic,
                    "result": "green" if green else "red",
                }
                events.append(event)
                print(json.dumps(event, sort_keys=True), flush=True)

    result_events = [
        event
        for event in events
        if event.get("event") in {"oracle_case", "threeway_case"}
    ]
    green = sum(event["result"] == "green" for event in result_events)
    red_events = [
        {
            "stage": event["stage"],
            "case": event["case"],
            "configuration": event["configuration"],
        }
        for event in result_events
        if event["result"] != "green"
    ]
    summary = {
        "event": "summary",
        "green": green,
        "red": len(result_events) - green,
        "total": len(result_events),
        "red_cases": red_events,
        "classification": (
            "no discrepancy in bounded chain"
            if not red_events
            else "inspect per-case MAME/native-off/native-on split"
        ),
        "organic_irq_cadence_proven": False,
        "result": "green" if not red_events else "red",
        "time": time.time(),
    }
    events.append(summary)
    print(json.dumps(summary, sort_keys=True), flush=True)
    event_path = args.output / "events.jsonl"
    event_path.write_text(
        "".join(json.dumps(event, sort_keys=True) + "\n" for event in events),
        encoding="utf-8",
    )
    summary["events"] = str(event_path.resolve())
    summary["events_sha256"] = sha256(event_path)
    summary["mame"] = mame_oracle
    summary["mame_rom_set_sha256"] = provenance[
        "mame_rom_set_sha256"
    ]
    summary["validator"] = str(Path(__file__).resolve())
    summary["validator_sha256"] = sha256(Path(__file__).resolve())
    (args.output / "summary.json").write_text(
        json.dumps(summary, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return 0 if summary["result"] == "green" else 1


if __name__ == "__main__":
    raise SystemExit(main())
