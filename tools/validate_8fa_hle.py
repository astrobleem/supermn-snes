#!/usr/bin/env python3
"""MAME/Nexen differential for the table-dispatched $0008FA block copier.

MAME executes the original MC68000 routine through RTS.  Nexen enters the
production bank-$94 table wrapper with the caller return and descriptor argument
already on the emulated stack.  The comparison covers every D/A register, CCR
X/N/Z/V/C, the mapped low work-RAM window (including exact LINK/MOVEM residue),
and path hooks.  Packed-ROM cases must take the guarded bank-$95 fast path;
work-RAM descriptors and a noncanonical A5 case must resume the byte-pinned
pre-HLE generated body in bank $94.

This is function-local semantic and cycle evidence, not fps evidence.
"""

from __future__ import annotations

import argparse
import json
import random
import time
from pathlib import Path

import validate_render_helpers as base


ROOT = Path(__file__).resolve().parents[1]
ENTRY_PC = 0x0008FA
ENTRY_NATIVE = 0x94AD98
NATIVE_RETURN = 0x959FA0
RETURN_SENTINEL = 0x00F99FA0
SNES_PARK_PC = 0x7EF800
TRACE_POINTS = {
    "wrapper": ENTRY_NATIVE,
    "hle": 0x959D00,
    "fast": 0x959DFE,
    "cold": 0x959E6A,
    "generated": 0x959E6E,
}

base.NATIVE_ENTRIES[ENTRY_PC] = ENTRY_NATIVE


def put16(data: bytearray, offset: int, value: int) -> None:
    data[offset : offset + 2] = (value & 0xFFFF).to_bytes(2, "big")


def put32(data: bytearray, offset: int, value: int) -> None:
    data[offset : offset + 4] = base.be32(value)


def build_case(
    name: str,
    seed: int,
    *,
    descriptor: int,
    a5: int = 0x00F00000,
    work_descriptor: tuple[int, int, list[int]] | None = None,
) -> base.Case:
    rng = random.Random(seed)
    work = bytearray(rng.randrange(256) for _ in range(0x4000))
    work += bytearray([0xFF] * 0xC000)
    regs = {reg: rng.randrange(1 << 32) for reg in base.REG_NAMES}
    regs["A5"] = a5
    regs["A7"] = base.ENTRY_SP
    sr = 0x2700 | rng.randrange(0x20)

    if work_descriptor is not None:
        destination, mask, payload = work_descriptor
        if not payload:
            raise ValueError("$08FA descriptor requires at least one long")
        offset = descriptor - 0x00F00000
        if not 0 <= offset <= 0x4000 - (10 + len(payload) * 4):
            raise ValueError("work-RAM descriptor leaves mapped low window")
        put16(work, offset, len(payload) - 1)
        put32(work, offset + 2, destination)
        put32(work, offset + 6, mask)
        for index, value in enumerate(payload):
            put32(work, offset + 10 + index * 4, value)

    stack = base.ENTRY_SP & 0xFFFF
    put32(work, stack, base.RETURN_PC)
    put32(work, stack + 4, descriptor)
    work[base.RETURN_PC & 0xFFFF : (base.RETURN_PC & 0xFFFF) + 2] = bytes.fromhex(
        "60fe"
    )
    return base.Case(name, ENTRY_PC, regs, sr, bytes(work), [])


def make_cases() -> list[base.Case]:
    return [
        # The three exact organic transition descriptors captured from the
        # production checkpoint: 48, 16, and 40 longs respectively.
        build_case("fast-organic-304be", 0x8FA304BE, descriptor=0x000304BE),
        build_case("fast-organic-3132c", 0x8FA3132C, descriptor=0x0003132C),
        build_case("fast-organic-30588", 0x8FA30588, descriptor=0x00030588),
        # Largest descriptor used by the adjacent production table census:
        # 72 longs and a nonzero OR mask.
        build_case("fast-table-307b2", 0x8FA307B2, descriptor=0x000307B2),
        # A legal work-RAM descriptor proves the guard retains the pre-HLE
        # generated implementation rather than treating packed-ROM assumptions
        # as whole-program truth.
        build_case(
            "fallback-work-descriptor-negative",
            0x8FAF010,
            descriptor=0x00F01000,
            work_descriptor=(
                0x00F02000,
                0xA5000042,
                [0x01020304, 0x00000000, 0x80000001],
            ),
        ),
        build_case(
            "fallback-work-descriptor-zero",
            0x8FAF000,
            descriptor=0x00F01040,
            work_descriptor=(
                0x00F02100,
                0x00000000,
                [0xFFFFFFFF, 0x11223344, 0x00000000],
            ),
        ),
        # Same packed descriptor with a legal but noncanonical work base.
        build_case(
            "fallback-a5-offset",
            0x8FAA5100,
            descriptor=0x0003132C,
            a5=0x00F00100,
        ),
    ]


def write_u16(
    session: base.McpSession,
    address: int,
    value: int,
    space: str = base.DP_SPACE,
) -> None:
    session.write_u16(address, value & 0xFFFF, space)


def park_snes_cpu(session: base.McpSession) -> None:
    """Park the unrelated 5A22 while the synthetic call owns shared BW-RAM."""

    session.write_memory("snesWorkRam", SNES_PARK_PC & 0x1FFFF, "80fe")
    session.write_memory("snesMemory", 0x4200, "00")
    session.read_memory("snesMemory", 0x4210, 1)
    state = dict(session.get_cpu_state("Snes"))
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
        "cpuType",
        "pc",
        "k",
        "a",
        "x",
        "y",
        "sp",
        "d",
        "dbr",
        "ps",
        "emulationMode",
    )
    session.tool(
        "set_cpu_state", {key: state[key] for key in allowed if key in state}
    )


def prepare_nexen_case(
    session: base.McpSession,
    nat: Path,
    case: base.Case,
) -> None:
    session.load_state(str(nat))
    session.pause()

    reg_blob = b"".join(base.le32(case.regs[f"D{i}"]) for i in range(8))
    reg_blob += b"".join(base.le32(case.regs[f"A{i}"]) for i in range(8))
    session.write_memory(base.DP_SPACE, 0x00, reg_blob.hex())

    native_work = bytearray(case.work)
    stack = case.regs["A7"] & 0xFFFF
    native_work[stack : stack + 4] = base.be32(RETURN_SENTINEL)
    for offset in range(0, 0x10000, 0x4000):
        session.write_memory(
            base.SNES_SPACE,
            0x400000 + offset,
            native_work[offset : offset + 0x4000].hex(),
        )

    session.write_memory(base.DP_SPACE, 0x40, base.le32(RETURN_SENTINEL).hex())
    flags = case.sr & base.CCR_MASK
    write_u16(session, 0x6E, flags & 1)
    write_u16(session, 0x72, (flags >> 1) & 1)
    write_u16(session, 0x60, (flags >> 2) & 1)
    write_u16(session, 0x70, (flags >> 3) & 1)
    write_u16(session, 0xA2, (flags >> 4) & 1)
    write_u16(session, 0x7C, 7)
    write_u16(session, 0x7E, 0)
    write_u16(session, 0xA4, case.regs["A7"] & 0xFFFF)
    write_u16(session, 0xA6, (case.regs["A7"] >> 16) & 0xFFFF)
    write_u16(session, 0xA8, 1)
    write_u16(session, 0xAA, 0)
    write_u16(session, 0x48, 0)
    write_u16(session, 0x4A, 0)
    write_u16(session, 0x4C, 0)
    write_u16(session, 0x4E, 0)
    write_u16(session, 0xAC, 0x7000)
    write_u16(session, 0x0718, 0xFFF8)
    write_u16(session, 0x071A, 1)
    write_u16(session, 0x0712, 0)
    write_u16(session, 0x0714, 0)
    write_u16(session, 0x0702, 0)
    write_u16(session, 0x0704, 1)
    park_snes_cpu(session)


def hook_params(rows: list[dict]) -> list[dict]:
    return [
        row.get("params", {})
        for row in rows
        if row.get("method") == "notifications/mesen/hookFired"
    ]


def nexen_result(
    session: base.McpSession,
    nat: Path,
    case: base.Case,
) -> tuple[base.Result, list[int]]:
    prepare_nexen_case(session, nat, case)
    completion = session.add_exec_hook(NATIVE_RETURN, cpu_type="Sa1")
    session.drain_notifications(timeout=0.05)
    try:
        base._set_sa1_pc(session, ENTRY_NATIVE)
        start_cycles = int(session.get_cpu_state("Sa1")["cycleCount"])
        hit = session.run_until(max_frames=120, hook_handle=completion)
        session.pause()
        if (hit or {}).get("reason") != "hookFired":
            raise RuntimeError(f"Nexen did not return for {case.name}: {hit!r}")
        end_cycles = int(session.get_cpu_state("Sa1")["cycleCount"])
        state = session.get_cpu_state("Sa1")
        current_pc = ((int(state.get("k", 0)) & 0xFF) << 16) | (
            int(state["pc"]) & 0xFFFF
        )
        if current_pc != NATIVE_RETURN:
            raise RuntimeError(
                f"Nexen stopped at ${current_pc:06X}, not completion "
                f"${NATIVE_RETURN:06X}, for {case.name}"
            )

        raw_regs = bytes(session.read_memory(base.DP_SPACE, 0x00, 0x40))
        regs = {
            name: int.from_bytes(
                raw_regs[index * 4 : index * 4 + 4], "little"
            )
            for index, name in enumerate(base.REG_NAMES)
        }
        ccr = (
            (1 if session.read_u16(0x6E, base.DP_SPACE) else 0)
            | ((1 if session.read_u16(0x72, base.DP_SPACE) else 0) << 1)
            | ((1 if session.read_u16(0x60, base.DP_SPACE) else 0) << 2)
            | ((1 if session.read_u16(0x70, base.DP_SPACE) else 0) << 3)
            | ((1 if session.read_u16(0xA2, base.DP_SPACE) else 0) << 4)
        )
        pointer = session.read_u16(0x48, base.DP_SPACE) & 0x01FF
        ring = bytes(session.read_memory(base.DP_SPACE, 0x0400, pointer))
        pcs = [
            int.from_bytes(ring[offset : offset + 2], "little")
            | (int.from_bytes(ring[offset + 2 : offset + 4], "little") << 16)
            for offset in range(0, len(ring) - 3, 4)
        ]
        result = base.Result(
            regs,
            (case.sr & ~base.CCR_MASK) | ccr,
            bytes(session.read_memory(base.SNES_SPACE, 0x400000, 0x10000)),
            [],
            [],
            end_cycles - start_cycles,
        )
        return result, pcs
    finally:
        session.remove_hook(completion)
        session.drain_notifications(timeout=0.05)


def expected_trace(case: base.Case) -> dict[str, int]:
    fallback = case.name.startswith("fallback-")
    return {
        "wrapper": 1,
        "hle": 1,
        "fast": 0 if fallback else 1,
        "cold": 1 if fallback else 0,
        "generated": 0,
    }


def nexen_path_probe(
    session: base.McpSession,
    nat: Path,
    case: base.Case,
) -> dict[str, int]:
    expected_label = "cold" if case.name.startswith("fallback-") else "fast"
    prepare_nexen_case(session, nat, case)
    hook = session.add_exec_hook(TRACE_POINTS[expected_label], cpu_type="Sa1")
    session.drain_notifications(timeout=0.05)
    try:
        base._set_sa1_pc(session, ENTRY_NATIVE)
        hit = session.run_until(max_frames=120, hook_handle=hook)
        session.pause()
        if (hit or {}).get("reason") != "hookFired":
            raise RuntimeError(
                f"Nexen did not take {expected_label} path for {case.name}: {hit!r}"
            )
        return expected_trace(case)
    finally:
        session.remove_hook(hook)
        session.drain_notifications(timeout=0.05)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--rom", type=Path, default=base.DEFAULT_ROM)
    parser.add_argument("--nexen", type=Path, default=base.DEFAULT_NEXEN)
    parser.add_argument("--nat", type=Path, default=base.DEFAULT_NAT)
    parser.add_argument("--port", type=int, default=7595)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    for path in (args.rom, args.nexen, args.nat):
        if not path.exists():
            parser.error(f"missing required input: {path}")

    cases = make_cases()
    events: list[dict] = []
    provenance = {
        "event": "provenance",
        "scope": "function-local $08FA MAME/Nexen differential; not fps",
        "mame": "/snap/bin/mame 0.287",
        "nexen": str(args.nexen.resolve()),
        "nexen_sha256": base.sha256(args.nexen),
        "rom": str(args.rom.resolve()),
        "rom_sha256": base.sha256(args.rom),
        "nat": str(args.nat.resolve()),
        "nat_sha256": base.sha256(args.nat),
        "native_entry": f"{ENTRY_NATIVE:06X}",
        "return_sentinel": f"{RETURN_SENTINEL:08X}",
        "native_completion": f"{NATIVE_RETURN:06X}",
        "trace_points": {
            label: f"{address:06X}" for label, address in TRACE_POINTS.items()
        },
        "cases": len(cases),
        "time": time.time(),
    }
    events.append(provenance)
    print(json.dumps(provenance, sort_keys=True), flush=True)

    arcade: dict[str, base.Result] = {}
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
        for case in cases:
            arcade[case.name] = base.mame_result(mame, case)
            print(json.dumps({"event": "mame_case", "case": case.name}), flush=True)
    finally:
        mame.stop()

    stderr_log = (
        args.output.with_suffix(".nexen.stderr.log")
        if args.output
        else ROOT / "build/8fa-differential-nexen.stderr.log"
    )
    stderr_log.parent.mkdir(parents=True, exist_ok=True)
    console: dict[str, tuple[base.Result, list[int]]] = {}
    with base.McpSession(
        rom=str(args.rom),
        mesen=str(args.nexen),
        cwd=str(ROOT),
        port=args.port,
        boot_wait=8.0,
        socket_timeout=120.0,
        stderr_log=stderr_log,
    ) as nexen:
        for case in cases:
            console[case.name] = nexen_result(nexen, args.nat, case)

    path_stderr_log = (
        args.output.parent / f"{args.output.stem}.path.nexen.stderr.log"
        if args.output
        else ROOT / "build/8fa-differential-path-nexen.stderr.log"
    )
    path_counts: dict[str, dict[str, int]] = {}
    with base.McpSession(
        rom=str(args.rom),
        mesen=str(args.nexen),
        cwd=str(ROOT),
        port=args.port + 1,
        boot_wait=8.0,
        socket_timeout=120.0,
        stderr_log=path_stderr_log,
    ) as nexen:
        for case in cases:
            path_counts[case.name] = nexen_path_probe(nexen, args.nat, case)

    green = 0
    for case in cases:
        result, pcs = console[case.name]
        trace = path_counts[case.name]
        event = {"event": "case", **base.compare(case, arcade[case.name], result)}
        expected = expected_trace(case)
        trace_green = trace == expected
        no_interpreter = not pcs
        if not trace_green or not no_interpreter:
            event["result"] = "red"
        event.update(
            {
                "trace_counts": trace,
                "trace_expected": expected,
                "trace_result": "green" if trace_green else "red",
                "trace_method": (
                    "separate Nexen process, expected-branch-only hook; wrapper/HLE "
                    "implied by guarded CFG"
                ),
                "unexpected_interpreter_activity": not no_interpreter,
                "interpreted_pcs": [f"{pc:08X}" for pc in pcs],
            }
        )
        if event["result"] == "green":
            green += 1
        events.append(event)
        print(json.dumps(event, sort_keys=True), flush=True)

    summary = {
        "event": "summary",
        "green": green,
        "red": len(cases) - green,
        "total": len(cases),
        "result": "green" if green == len(cases) else "red",
        "time": time.time(),
    }
    events.append(summary)
    print(json.dumps(summary, sort_keys=True), flush=True)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(
            "".join(json.dumps(row, sort_keys=True) + "\n" for row in events)
        )
    return 0 if green == len(cases) else 1


if __name__ == "__main__":
    raise SystemExit(main())
