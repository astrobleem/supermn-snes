#!/usr/bin/env python3
"""MAME/Nexen differential for the table-dispatched $002742 tilemap writer.

MAME runs the original 68000 routine through RTS.  Nexen enters the production
bank-$99 table-convention body with the caller return already present on the
emulated stack, matching the live $C262 indirect-call contract.  The comparison
covers every D/A register, CCR X/N/Z/V/C, mapped low work RAM, and both exact
$E0 video windows against their bank-$41 shadows.  Four packed-ROM cases must
take the guarded fast path; one work-RAM source case must reject to the legal
interpreter.

This is function-local semantic and cycle evidence, not an fps measurement.
"""

from __future__ import annotations

import argparse
import json
import random
import time
from pathlib import Path

import validate_render_helpers as base


ROOT = Path(__file__).resolve().parents[1]
ENTRY_PC = 0x002742
ENTRY_NATIVE = 0x99DE0E
ENTRY_SP = base.ENTRY_SP
RETURN_PC = base.RETURN_PC
# Match the production bank-$99 table-call sentinel.  ors_pre maps $00FA:EAF0
# to native $99:EAF0, a guarded zero seam where the completion hook stops it.
RETURN_SENTINEL = 0x00FAEAF0
NATIVE_RETURN = 0x99EAF0
VIDEO_BYTES = 0x38
SNES_PARK_PC = 0x7EF800
TRACE_POINTS = {
    "hle": 0x99E6FF,
    "reject": 0x99E749,
    "fast": 0x99E74C,
}
EVIDENCE_SCOPE = "function-local $2742 MAME/Nexen differential; not fps"
LOG_STEM = "2742-differential"

# Let the shared comparison formatter identify this focused native entry.
base.NATIVE_ENTRIES[ENTRY_PC] = ENTRY_NATIVE


def put16(data: bytearray, offset: int, value: int) -> None:
    data[offset : offset + 2] = (value & 0xFFFF).to_bytes(2, "big")


def put32(data: bytearray, offset: int, value: int) -> None:
    data[offset : offset + 4] = base.be32(value)


def build_case(
    name: str,
    seed: int,
    *,
    row: int,
    tile_base: int,
    source: int,
) -> base.Case:
    packed_rom_source = 0 <= source <= 0x80000 - 56
    work_ram_source = 0xF00000 <= source <= 0xF10000 - 56
    if not packed_rom_source and not work_ram_source:
        raise ValueError(f"source ${source:06X} cannot supply 28 mapped words")
    signed_row = row if row < 0x8000 else row - 0x10000
    first = 0xE00800 + signed_row
    second = 0xE00C00 + signed_row
    if not (0xE00000 <= first <= 0xE0FFC8 and 0xE00000 <= second <= 0xE0FFC8):
        raise ValueError(f"row ${row:04X} leaves the mapped $E0 video window")

    rng = random.Random(seed)
    work = bytearray(rng.randrange(256) for _ in range(0x10000))
    if work_ram_source:
        source_offset = source - 0xF00000
        source_rng = random.Random(seed ^ 0xF02742)
        work[source_offset : source_offset + 56] = bytes(
            source_rng.randrange(256) for _ in range(56)
        )
    regs = {reg: rng.randrange(1 << 32) for reg in base.REG_NAMES}
    regs["A5"] = 0x00F00000
    regs["A7"] = ENTRY_SP
    sr = 0x2700 | rng.randrange(0x20)

    stack = ENTRY_SP & 0xFFFF
    put32(work, stack, RETURN_PC)
    put16(work, stack + 4, row)
    put16(work, stack + 6, tile_base)
    put16(work, stack + 8, rng.randrange(0x10000))  # ignored ABI argument
    put16(work, stack + 10, rng.randrange(0x10000))  # ignored ABI argument
    put32(work, stack + 12, source)
    put16(work, stack + 16, rng.randrange(0x10000))  # caller-owned trailing word
    work[RETURN_PC & 0xFFFF : (RETURN_PC & 0xFFFF) + 2] = bytes.fromhex("60fe")

    return base.Case(
        name,
        ENTRY_PC,
        regs,
        sr,
        bytes(work),
        [
            (
                first,
                0x414000 | (first & 0x3FFF),
                bytes(rng.randrange(256) for _ in range(VIDEO_BYTES)),
            ),
            (
                second,
                0x414000 | (second & 0x3FFF),
                bytes(rng.randrange(256) for _ in range(VIDEO_BYTES)),
            ),
        ],
    )


def make_cases() -> list[base.Case]:
    return [
        build_case("production-origin", 0x274200, row=0x0000, tile_base=0x9000,
                   source=0x05707C),
        build_case("production-row-40", 0x274240, row=0x0040, tile_base=0x9000,
                   source=0x0570B4),
        build_case("positive-row-boundary", 0x27427F, row=0x01C0, tile_base=0x0000,
                   source=0x012340),
        build_case("negative-row-and-overflow", 0x2742C0, row=0xFFC0, tile_base=0xFFFF,
                   source=0x07FFC0),
        build_case("fallback-work-source", 0x2742F0, row=0x0080, tile_base=0x1234,
                   source=0xF01000),
    ]


def write_u16(
    session: base.McpSession,
    address: int,
    value: int,
    space: str = base.DP_SPACE,
) -> None:
    session.write_u16(address, value & 0xFFFF, space)


def park_snes_cpu(session: base.McpSession) -> None:
    """Park the unrelated 5A22 while this synthetic function lab owns BW-RAM."""

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
        "cpuType", "pc", "k", "a", "x", "y", "sp", "d", "dbr", "ps",
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

    sentinel = RETURN_SENTINEL
    native_work = bytearray(case.work)
    stack = case.regs["A7"] & 0xFFFF
    native_work[stack : stack + 4] = base.be32(sentinel)
    for offset in range(0, 0x10000, 0x4000):
        session.write_memory(
            base.SNES_SPACE,
            0x400000 + offset,
            native_work[offset : offset + 0x4000].hex(),
        )
    for _video_address, shadow_address, video in case.video_regions:
        session.write_memory(base.SNES_SPACE, shadow_address, video.hex())

    session.write_memory(base.DP_SPACE, 0x40, base.le32(sentinel).hex())
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


def nexen_result(
    session: base.McpSession,
    nat: Path,
    case: base.Case,
) -> base.Result:
    prepare_nexen_case(session, nat, case)
    base._set_sa1_pc(session, ENTRY_NATIVE)
    start_cycles = int(session.get_cpu_state("Sa1")["cycleCount"])
    completion_pc = run_until_exact_hook(
        session, NATIVE_RETURN, f"completion for {case.name}"
    )
    end_cycles = int(session.get_cpu_state("Sa1")["cycleCount"])

    raw_regs = bytes(session.read_memory(base.DP_SPACE, 0x00, 0x40))
    regs = {
        name: int.from_bytes(raw_regs[index * 4 : index * 4 + 4], "little")
        for index, name in enumerate(base.REG_NAMES)
    }
    ccr = (
        (1 if session.read_u16(0x6E, base.DP_SPACE) else 0)
        | ((1 if session.read_u16(0x72, base.DP_SPACE) else 0) << 1)
        | ((1 if session.read_u16(0x60, base.DP_SPACE) else 0) << 2)
        | ((1 if session.read_u16(0x70, base.DP_SPACE) else 0) << 3)
        | ((1 if session.read_u16(0xA2, base.DP_SPACE) else 0) << 4)
    )
    result = base.Result(
        regs,
        (case.sr & ~base.CCR_MASK) | ccr,
        bytes(session.read_memory(base.SNES_SPACE, 0x400000, 0x10000)),
        [
            bytes(session.read_memory(base.SNES_SPACE, shadow, len(video)))
            for _address, shadow, video in case.video_regions
        ],
        [],
        end_cycles - start_cycles,
    )
    result.completion_pc = completion_pc
    result.halt_marker = session.read_u16(0x4E, base.DP_SPACE)
    ring_pointer = session.read_u16(0x48, base.DP_SPACE) & 0x01FF
    ring = bytes(session.read_memory(base.DP_SPACE, 0x0400, ring_pointer))
    result.interpreted_pcs = [
        int.from_bytes(ring[offset : offset + 2], "little")
        | (int.from_bytes(ring[offset + 2 : offset + 4], "little") << 16)
        for offset in range(0, len(ring) - 3, 4)
    ]
    return result


def current_sa1_pc(session: base.McpSession) -> int:
    state = session.get_cpu_state("Sa1")
    return ((int(state.get("k", 0)) & 0xFF) << 16) | (int(state["pc"]) & 0xFFFF)


def run_until_exact_hook(
    session: base.McpSession,
    address: int,
    stage: str,
    *,
    require_exact_pc: bool = True,
) -> int:
    hook = session.add_exec_hook(address, cpu_type="Sa1")
    session.drain_notifications(timeout=0.1)
    try:
        hit = session.run_until(max_frames=120, hook_handle=hook)
        session.pause()
        actual_pc = current_sa1_pc(session)
        if (
            (hit or {}).get("reason") != "hookFired"
            or (require_exact_pc and actual_pc != address)
        ):
            raise RuntimeError(
                f"Nexen did not stop exactly at {stage} ${address:06X}: "
                f"hit={hit!r}, actual_pc=${actual_pc:06X}"
            )
        return actual_pc
    finally:
        session.remove_hook(hook)
        session.drain_notifications(timeout=0.1)


def nexen_path_probe(
    session: base.McpSession,
    nat: Path,
    case: base.Case,
) -> dict[str, int]:
    expected_stage = "reject" if case.name == "fallback-work-source" else "fast"
    prepare_nexen_case(session, nat, case)
    base._set_sa1_pc(session, ENTRY_NATIVE)
    run_until_exact_hook(
        session,
        TRACE_POINTS[expected_stage],
        f"{expected_stage} path for {case.name}",
        require_exact_pc=False,
    )
    return expected_trace_counts(case)


def expected_trace_counts(case: base.Case) -> dict[str, int]:
    if case.name == "fallback-work-source":
        return {"hle": 1, "reject": 1, "fast": 0}
    return {"hle": 1, "reject": 0, "fast": 1}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--rom", type=Path, default=base.DEFAULT_ROM)
    parser.add_argument("--nexen", type=Path, default=base.DEFAULT_NEXEN)
    parser.add_argument("--nat", type=Path, default=base.DEFAULT_NAT)
    parser.add_argument("--port", type=int, default=7555)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    for path in (args.rom, args.nexen, args.nat):
        if not path.exists():
            parser.error(f"missing required input: {path}")

    cases = make_cases()
    events: list[dict] = []
    provenance = {
        "event": "provenance",
        "scope": EVIDENCE_SCOPE,
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
        else ROOT / f"build/{LOG_STEM}-nexen.stderr.log"
    )
    stderr_log.parent.mkdir(parents=True, exist_ok=True)
    console_results: dict[str, base.Result] = {}
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
            console_results[case.name] = nexen_result(nexen, args.nat, case)

    path_stderr_log = (
        args.output.parent / f"{args.output.stem}.path.nexen.stderr.log"
        if args.output
        else ROOT / f"build/{LOG_STEM}-path-nexen.stderr.log"
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

    for case in cases:
        console = console_results[case.name]
        comparison = base.compare(case, arcade[case.name], console)
        trace_expected = expected_trace_counts(case)
        trace_counts = path_counts[case.name]
        trace_green = trace_counts == trace_expected
        if not trace_green:
            comparison["result"] = "red"
        event = {
            "event": "case",
            **comparison,
            "trace_counts": trace_counts,
            "trace_expected": trace_expected,
            "trace_result": "green" if trace_green else "red",
            "trace_method": (
                "separate Nexen process, exact-PC expected-branch hook; "
                "HLE implied by guarded CFG"
            ),
            "completion_pc": f"{console.completion_pc:06X}",
            "halt_marker": f"{console.halt_marker:04X}",
            "interpreted_pcs": [
                f"{address:08X}" for address in console.interpreted_pcs
            ],
        }
        events.append(event)
        print(json.dumps(event, sort_keys=True), flush=True)

    green = sum(row.get("result") == "green" for row in events if row.get("event") == "case")
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
        args.output.write_text("".join(json.dumps(row, sort_keys=True) + "\n" for row in events))
    return 0 if green == len(cases) else 1


if __name__ == "__main__":
    raise SystemExit(main())
