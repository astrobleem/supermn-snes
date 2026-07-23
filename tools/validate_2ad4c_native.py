#!/usr/bin/env python3
"""MAME/Nexen differential for the table-dispatched $02AD4C box publisher.

MAME executes the original 68000 routine through RTS.  Nexen enters the
production bank-$9D table-convention body with the caller return already on the
emulated stack.  The comparison covers every D/A register, CCR X/N/Z/V/C, the
arcade board's mapped low 16 KiB work-RAM window, and D0 video writes used by a
guard-rejection case.  Separate path probes prove which cases used the direct
body and which resumed the legal interpreter.

This is function-local semantic and local-cycle evidence, not fps evidence.
"""

from __future__ import annotations

import argparse
import json
import random
import time
from pathlib import Path

import validate_render_helpers as base


ROOT = Path(__file__).resolve().parents[1]
ENTRY_PC = 0x02AD4C
ENTRY_NATIVE = 0x9D8A00
HOT_PC = 0x9D8A39
COLD_PC = 0x9D8A3C
RETURN_SENTINEL = 0x00FF0000 | base.NATIVE_RETURN
SNES_PARK_PC = 0x7EF800

base.NATIVE_ENTRIES[ENTRY_PC] = ENTRY_NATIVE


def put16(data: bytearray, offset: int, value: int) -> None:
    data[offset : offset + 2] = (value & 0xFFFF).to_bytes(2, "big")


def put32(data: bytearray, offset: int, value: int) -> None:
    data[offset : offset + 4] = base.be32(value)


def build_case(
    name: str,
    seed: int,
    *,
    x: int,
    y: int,
    kind: int,
    first: int,
    second: int,
) -> base.Case:
    rng = random.Random(seed)
    work = bytearray(rng.randrange(256) for _ in range(0x4000))
    work.extend([0xFF] * 0xC000)
    regs = {reg: rng.randrange(1 << 32) for reg in base.REG_NAMES}
    regs["A4"] = 0x00F02000
    regs["A7"] = base.ENTRY_SP
    sr = 0x2700 | rng.randrange(0x20)

    a4 = regs["A4"] & 0xFFFF
    put16(work, a4 + 4, x)
    put16(work, a4 + 6, y)
    put16(work, a4 + 0x0A, kind)
    put32(work, a4 + 0x30, first)
    put32(work, a4 + 0x34, second)
    put32(work, base.ENTRY_SP & 0xFFFF, base.RETURN_PC)
    work[base.RETURN_PC & 0xFFFF : (base.RETURN_PC & 0xFFFF) + 2] = bytes.fromhex(
        "60fe"
    )

    video_regions: list[tuple[int, int, bytes]] = []
    if (first & 0xFFFFC0) == 0xD00400 or (second & 0xFFFFC0) == 0xD00400:
        video_regions.append(
            (
                0xD00400,
                0x413400,
                bytes(rng.randrange(256) for _ in range(0x40)),
            )
        )
    return base.Case(name, ENTRY_PC, regs, sr, bytes(work), video_regions)


def make_cases() -> list[base.Case]:
    return [
        build_case(
            "hot-kind-two",
            0x2AD4C0,
            x=0x1234,
            y=0x5678,
            kind=2,
            first=0x00F03000,
            second=0x00F03100,
        ),
        build_case(
            "hot-kind-six",
            0x2AD4C1,
            x=0x8000,
            y=0x7FFF,
            kind=6,
            first=0x00F03200,
            second=0x00F03300,
        ),
        build_case(
            "hot-final-add-carry",
            0x2AD4C2,
            x=0xFFFF,
            y=0x0000,
            kind=0xFFFF,
            first=0x00F03400,
            second=0x00F03500,
        ),
        build_case(
            "hot-low-window-boundaries",
            0x2AD4C3,
            x=0x7FE0,
            y=0x8020,
            kind=2,
            first=0x00F03FF4,
            second=0x00F03FFA,
        ),
        build_case(
            "cold-video-pointers",
            0x2AD4CF,
            x=0x0A00,
            y=0x0B00,
            kind=4,
            first=0x00D00400,
            second=0x00D00420,
        ),
    ]


def write_u16(session: base.McpSession, address: int, value: int) -> None:
    session.write_u16(address, value & 0xFFFF, base.DP_SPACE)


def park_snes_cpu(session: base.McpSession) -> None:
    """Keep the unrelated 5A22 from touching synthetic BW-RAM state."""

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

    reg_blob = b"".join(base.le32(case.regs[name]) for name in base.REG_NAMES)
    session.write_memory(base.DP_SPACE, 0x00, reg_blob.hex())
    native_work = bytearray(case.work)
    put32(native_work, case.regs["A7"] & 0xFFFF, RETURN_SENTINEL)
    for offset in range(0, 0x10000, 0x4000):
        session.write_memory(
            base.SNES_SPACE,
            0x400000 + offset,
            native_work[offset : offset + 0x4000].hex(),
        )
    for _video_address, shadow_address, video in case.video_regions:
        session.write_memory(base.SNES_SPACE, shadow_address, video.hex())

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
        if (hit or {}).get("reason") != "hookFired" or (
            require_exact_pc and actual_pc != address
        ):
            raise RuntimeError(
                f"Nexen did not stop exactly at {stage} ${address:06X}: "
                f"hit={hit!r}, actual_pc=${actual_pc:06X}"
            )
        return actual_pc
    finally:
        session.remove_hook(hook)
        session.drain_notifications(timeout=0.1)


def nexen_result(
    session: base.McpSession,
    nat: Path,
    case: base.Case,
) -> base.Result:
    prepare_nexen_case(session, nat, case)
    base._set_sa1_pc(session, ENTRY_NATIVE)
    start_cycles = int(session.get_cpu_state("Sa1")["cycleCount"])
    completion_pc = run_until_exact_hook(
        session, base.NATIVE_RETURN, f"completion for {case.name}"
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
    return result


def expected_path(case: base.Case) -> str:
    return "cold" if case.name.startswith("cold-") else "hot"


def path_probe(
    session: base.McpSession,
    nat: Path,
    case: base.Case,
) -> dict[str, int]:
    path = expected_path(case)
    address = COLD_PC if path == "cold" else HOT_PC
    prepare_nexen_case(session, nat, case)
    base._set_sa1_pc(session, ENTRY_NATIVE)
    run_until_exact_hook(
        session,
        address,
        f"{path} path for {case.name}",
        require_exact_pc=False,
    )
    return {"hot": int(path == "hot"), "cold": int(path == "cold")}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--rom", type=Path, default=base.DEFAULT_ROM)
    parser.add_argument("--nexen", type=Path, default=base.DEFAULT_NEXEN)
    parser.add_argument("--nat", type=Path, default=base.DEFAULT_NAT)
    parser.add_argument("--port", type=int, default=7594)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    for path in (args.rom, args.nexen, args.nat):
        if not path.is_file():
            parser.error(f"missing required input: {path}")

    cases = make_cases()
    events: list[dict] = []
    provenance = {
        "event": "provenance",
        "scope": "function-local $02AD4C MAME/Nexen differential; not fps",
        "mame": "/snap/bin/mame 0.287",
        "nexen": str(args.nexen.resolve()),
        "nexen_sha256": base.sha256(args.nexen),
        "rom": str(args.rom.resolve()),
        "rom_sha256": base.sha256(args.rom),
        "nat": str(args.nat.resolve()),
        "nat_sha256": base.sha256(args.nat),
        "native_entry": f"{ENTRY_NATIVE:06X}",
        "return_sentinel": f"{RETURN_SENTINEL:08X}",
        "native_completion": f"{base.NATIVE_RETURN:06X}",
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
        else ROOT / "build/2ad4c-differential-nexen.stderr.log"
    )
    stderr_log.parent.mkdir(parents=True, exist_ok=True)
    console: dict[str, base.Result] = {}
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

    path_log = (
        args.output.parent / f"{args.output.stem}.path.nexen.stderr.log"
        if args.output
        else ROOT / "build/2ad4c-differential-path-nexen.stderr.log"
    )
    paths: dict[str, dict[str, int]] = {}
    with base.McpSession(
        rom=str(args.rom),
        mesen=str(args.nexen),
        cwd=str(ROOT),
        port=args.port + 1,
        boot_wait=8.0,
        socket_timeout=120.0,
        stderr_log=path_log,
    ) as nexen:
        for case in cases:
            paths[case.name] = path_probe(nexen, args.nat, case)

    for case in cases:
        comparison = base.compare(case, arcade[case.name], console[case.name])
        expected = {
            "hot": int(expected_path(case) == "hot"),
            "cold": int(expected_path(case) == "cold"),
        }
        path_green = paths[case.name] == expected
        if not path_green:
            comparison["result"] = "red"
        event = {
            "event": "case",
            **comparison,
            "path_counts": paths[case.name],
            "path_expected": expected,
            "path_result": "green" if path_green else "red",
            "completion_pc": f"{console[case.name].completion_pc:06X}",
            "halt_marker": f"{console[case.name].halt_marker:04X}",
        }
        events.append(event)
        print(json.dumps(event, sort_keys=True), flush=True)

    green = sum(
        row.get("result") == "green" for row in events if row.get("event") == "case"
    )
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
            "".join(json.dumps(row, sort_keys=True) + "\n" for row in events),
            encoding="utf-8",
        )
    return 0 if green == len(cases) else 1


if __name__ == "__main__":
    raise SystemExit(main())
