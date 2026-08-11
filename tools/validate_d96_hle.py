#!/usr/bin/env python3
"""Function-local MAME/Nexen differential for the $000D96 sprite renderer.

MAME executes the original 68000 subroutine through RTS.  Nexen enters the
same-bank bank-$98 table-convention escape directly with an already-pushed
sentinel return, matching the real $01F096 indirect-call contract.  The
comparison covers all D/A registers, CCR X/N/Z/V/C, and the complete mapped
low 16 KiB work-RAM window apart from the synthetic return PC.

This is bounded semantic and local-cycle evidence, not an FPS measurement.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import random
import sys
import time
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
MAME_TRACE = ROOT / "tools" / "mame-trace"
MAME_MCP = Path("/home/chad/mame-mcp")
MESEN_PY = Path("/home/chad/Mesen2/python")
DEFAULT_NEXEN = Path(
    "/mnt/sdc1/Nexen-r5-20260712/bin/linux-x64/Release/linux-x64/publish/Nexen"
)
DEFAULT_ROM = ROOT / "build" / "interp.sfc"
DEFAULT_NAT = Path("/tmp/b0_native.mss")

sys.path.insert(0, str(MAME_MCP))
sys.path.insert(0, str(MESEN_PY))
os.environ["DOTNET_ROOT"] = "/home/chad/.dotnet10"
os.environ["PATH"] = "/home/chad/.dotnet10:" + os.environ.get("PATH", "")

from mame_mcp.session import MameSession  # noqa: E402
import mesen_mcp.session as _mesen_session  # noqa: E402

_mesen_session.validate_mesen_build = lambda *args, **kwargs: None
from mesen_mcp import McpSession  # noqa: E402


ENTRY_PC = 0x000D96


def current_escbank4_address(symbol: str) -> int:
    path = ROOT / "src/escbank4.sym"
    if not path.is_file():
        raise SystemExit(f"current bank-$98 symbols are required: {path}")
    for raw in path.read_text(encoding="utf-8-sig").splitlines():
        fields = raw.split()
        if len(fields) == 2 and fields[1] == symbol:
            return 0x980000 | int(fields[0].split(":", 1)[1], 16)
    raise SystemExit(f"{path}: missing {symbol}")


ENTRY_NATIVE = current_escbank4_address("entry_d96t")
RETURN_PC = 0xF03E80
NATIVE_RETURN = 0x00D15A
WORK_FRAME = 0xF02B00
ENTRY_SP = 0xF03D00
DP_SPACE = "Sa1Memory"
SNES_SPACE = "snesMemory"
REG_NAMES = [f"D{i}" for i in range(8)] + [f"A{i}" for i in range(8)]
CCR_MASK = 0x1F


@dataclass
class Case:
    name: str
    regs: dict[str, int]
    sr: int
    work: bytes


@dataclass
class Result:
    regs: dict[str, int]
    sr: int
    work: bytes
    cycles: int | None = None
    ac: int | None = None


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def be16(value: int) -> bytes:
    return (value & 0xFFFF).to_bytes(2, "big")


def be32(value: int) -> bytes:
    return (value & 0xFFFFFFFF).to_bytes(4, "big")


def le32(value: int) -> bytes:
    return (value & 0xFFFFFFFF).to_bytes(4, "little")


def build_case(
    name: str,
    seed: int,
    *,
    outer_count: int,
    inner_count: int,
    tiles: list[int],
    capacity_minus_one: int,
    cursor: int = 0,
    attr: int = 0x2000,
    y: int = 0x0040,
    x: int = 0x0060,
    frame_pointer: int = WORK_FRAME,
    entry_sp: int = ENTRY_SP,
    a5: int = 0x00F00000,
    x_flag: int = 0,
) -> Case:
    expected_tiles = (outer_count + 1) * (inner_count + 1)
    if frame_pointer == WORK_FRAME and len(tiles) != expected_tiles:
        raise ValueError(f"{name}: expected {expected_tiles} tile words")
    rng = random.Random(seed)
    work = bytearray(rng.randrange(256) for _ in range(0x10000))
    regs = {reg: rng.randrange(1 << 32) for reg in REG_NAMES}
    regs["A5"] = a5
    regs["A7"] = entry_sp
    sr = 0x2700 | rng.randrange(0x10) | ((x_flag & 1) << 4)

    if frame_pointer == WORK_FRAME:
        frame = be16(outer_count) + be16(inner_count)
        frame += b"".join(be16(tile) for tile in tiles)
        frame_offset = frame_pointer & 0xFFFF
        work[frame_offset : frame_offset + len(frame)] = frame

    stack = entry_sp & 0xFFFF
    args = (
        be16(cursor)
        + be16(attr)
        + be16(y)
        + be16(x)
        + be32(frame_pointer)
        + be16(capacity_minus_one)
    )
    work[stack : stack + 4] = be32(RETURN_PC)
    work[stack + 4 : stack + 4 + len(args)] = args
    work[RETURN_PC & 0xFFFF : (RETURN_PC & 0xFFFF) + 2] = bytes.fromhex("60fe")
    return Case(name, regs, sr, bytes(work))


def make_cases() -> list[Case]:
    return [
        build_case(
            "single-row-zero-skip-and-fill-x0",
            0xD9600,
            outer_count=0,
            inner_count=2,
            tiles=[0x0001, 0x0000, 0x0345],
            capacity_minus_one=5,
            x_flag=0,
        ),
        build_case(
            "two-rows-offscreen-and-negative-offset-x1",
            0xD9601,
            outer_count=1,
            inner_count=2,
            tiles=[0x0010, 0x0011, 0x0012, 0x0020, 0x0000, 0x0022],
            capacity_minus_one=8,
            cursor=0xFFF0,
            attr=0x6400,
            y=0x0190,
            x=0xFFF8,
            x_flag=1,
        ),
        build_case(
            "capacity-exhausts-mid-row",
            0xD9602,
            outer_count=0,
            inner_count=4,
            tiles=[0x0100, 0x0101, 0x0102, 0x0103, 0x0104],
            capacity_minus_one=1,
            x_flag=0,
        ),
        build_case(
            "negative-capacity-before-first-write",
            0xD9603,
            outer_count=0,
            inner_count=1,
            tiles=[0x0007, 0x0008],
            capacity_minus_one=0xFFFE,
            x_flag=1,
        ),
        # The immutable arcade ROM bytes at $00084A decode as header 0,3 and
        # tile words 0,4,0,5.  This exercises the production ROM mapping path.
        build_case(
            "rom-backed-frame-stream",
            0xD9604,
            outer_count=0,
            inner_count=3,
            tiles=[],
            capacity_minus_one=4,
            frame_pointer=0x0000084A,
            cursor=0x0020,
            y=0x0004,
            x=0x00EF,
            x_flag=0,
        ),
        build_case(
            "rom-shape-337f0-hot",
            0xD9607,
            outer_count=4,
            inner_count=4,
            tiles=[],
            capacity_minus_one=0x0011,
            cursor=0x0228,
            attr=0x3000,
            y=0x002C,
            x=0x0086,
            frame_pointer=0x0337F0,
            x_flag=1,
        ),
        build_case(
            "rom-shape-33c0a-hot",
            0xD9608,
            outer_count=4,
            inner_count=4,
            tiles=[],
            capacity_minus_one=0x0011,
            cursor=0x0204,
            attr=0x3800,
            y=0x0010,
            x=0x0008,
            frame_pointer=0x033C0A,
            x_flag=0,
        ),
        build_case(
            "rom-shape-33c0a-hot-guard-edge",
            0xD9609,
            outer_count=4,
            inner_count=4,
            tiles=[],
            capacity_minus_one=0x0011,
            cursor=0x0180,
            attr=0x6800,
            y=0x00AA,
            x=0x013F,
            frame_pointer=0x033C0A,
            x_flag=1,
        ),
        build_case(
            "low-task-stack",
            0xD9605,
            outer_count=2,
            inner_count=1,
            tiles=[0x1000, 0x1001, 0x1010, 0x1011, 0x1020, 0x1021],
            capacity_minus_one=7,
            entry_sp=0xF00440,
            cursor=0x0006,
            x_flag=1,
        ),
        build_case(
            "noncanonical-a5-cold-fallback",
            0xD9606,
            outer_count=0,
            inner_count=1,
            tiles=[0x0042, 0x0043],
            capacity_minus_one=3,
            a5=0x00F00010,
            cursor=0x0010,
            x_flag=0,
        ),
    ]


def mame_result(session: MameSession, case: Case) -> Result:
    session.pause()
    session.write_block(0xF00000, case.work)
    for name in REG_NAMES[:-1]:
        session.set_reg(name, case.regs[name])
    session.set_reg("SP", case.regs["A7"])
    session.set_reg("USP", case.regs["A7"])
    session.set_reg("SR", case.sr)
    session.set_reg("PC", ENTRY_PC)
    captured = session.cmd(
        "capture_at_pc",
        pc=RETURN_PC,
        addr=0xF00000,
        len=0x4000,
        nth=1,
        exp_sp=(case.regs["A7"] + 4) & 0xFFFFFF,
        maxFrames=30,
        timeout=30,
    )
    if not captured.get("registers"):
        raise RuntimeError(f"MAME did not return for {case.name}: {captured!r}")
    regs = captured["registers"]
    result_regs = {name: regs[name] & 0xFFFFFFFF for name in REG_NAMES[:-1]}
    result_regs["A7"] = regs["SP"] & 0xFFFFFFFF
    return Result(result_regs, regs["SR"] & 0xFFFF, bytes.fromhex(captured["hex"]))


def write_u16(m: McpSession, address: int, value: int) -> None:
    m.write_u16(address, value & 0xFFFF, DP_SPACE)


def set_sa1_pc(m: McpSession, address: int) -> None:
    state = dict(m.get_cpu_state("Sa1"))
    state["pc"] = address & 0xFFFF
    state["k"] = (address >> 16) & 0xFF
    state["d"] = 0
    state["dbr"] = 0
    state["ps"] = int(state.get("ps", 0)) | 0x04
    state["emulationMode"] = False
    allowed = (
        "cpuType", "pc", "k", "a", "x", "y", "sp", "d", "dbr", "ps",
        "emulationMode",
    )
    m.tool("set_cpu_state", {key: state[key] for key in allowed if key in state})


def nexen_result(m: McpSession, nat: Path, case: Case) -> Result:
    m.load_state(str(nat))
    m.pause()

    reg_blob = b"".join(le32(case.regs[f"D{i}"]) for i in range(8))
    reg_blob += b"".join(le32(case.regs[f"A{i}"]) for i in range(8))
    m.write_memory(DP_SPACE, 0x00, reg_blob.hex())
    for offset in range(0, 0x10000, 0x4000):
        m.write_memory(
            SNES_SPACE,
            0x400000 + offset,
            case.work[offset : offset + 0x4000].hex(),
        )

    # Table-convention native entries consume an already-pushed return.  The
    # $00FF sentinel routes ors_pre back to the stable bank-$00 ispin loop.
    stack = case.regs["A7"] & 0xFFFF
    m.write_memory(SNES_SPACE, 0x400000 + stack, be32(0x00FF0000 | NATIVE_RETURN).hex())
    flags = case.sr & CCR_MASK
    write_u16(m, 0x6E, flags & 1)
    write_u16(m, 0x72, (flags >> 1) & 1)
    write_u16(m, 0x60, (flags >> 2) & 1)
    write_u16(m, 0x70, (flags >> 3) & 1)
    write_u16(m, 0xA2, (flags >> 4) & 1)
    write_u16(m, 0x40, NATIVE_RETURN & 0xFFFF)
    write_u16(m, 0x42, 0x00FF)
    write_u16(m, 0x7C, 7)
    write_u16(m, 0xA4, case.regs["A7"] & 0xFFFF)
    write_u16(m, 0xA6, (case.regs["A7"] >> 16) & 0xFFFF)
    write_u16(m, 0xA8, 1)
    write_u16(m, 0xAA, 0)
    write_u16(m, 0x4A, 0)
    write_u16(m, 0x4C, 0)
    write_u16(m, 0xAC, 0x7000)
    write_u16(m, 0x0718, 0xFFF8)
    write_u16(m, 0x071A, 1)
    write_u16(m, 0x0702, 0)
    write_u16(m, 0x0704, 1)

    return_hook = m.add_exec_hook(NATIVE_RETURN, cpu_type="Sa1")
    m.drain_notifications(timeout=0.05)
    set_sa1_pc(m, ENTRY_NATIVE)
    start_cycles = int(m.get_cpu_state("Sa1")["cycleCount"])
    hit = m.run_until(max_frames=120, hook_handle=return_hook)
    if (hit or {}).get("reason") != "hookFired":
        raise RuntimeError(f"Nexen did not return for {case.name}: {hit!r}")
    m.pause()
    m.remove_hook(return_hook)
    end_cycles = int(m.get_cpu_state("Sa1")["cycleCount"])

    raw_regs = bytes(m.read_memory(DP_SPACE, 0x00, 0x40))
    result_regs = {}
    for index, name in enumerate(REG_NAMES):
        offset = index * 4
        result_regs[name] = int.from_bytes(raw_regs[offset : offset + 4], "little")
    ccr = (
        (1 if m.read_u16(0x6E, DP_SPACE) else 0)
        | ((1 if m.read_u16(0x72, DP_SPACE) else 0) << 1)
        | ((1 if m.read_u16(0x60, DP_SPACE) else 0) << 2)
        | ((1 if m.read_u16(0x70, DP_SPACE) else 0) << 3)
        | ((1 if m.read_u16(0xA2, DP_SPACE) else 0) << 4)
    )
    return Result(
        result_regs,
        (case.sr & ~CCR_MASK) | ccr,
        bytes(m.read_memory(SNES_SPACE, 0x400000, 0x4000)),
        end_cycles - start_cycles,
        m.read_u16(0xAC, DP_SPACE),
    )


def compare(case: Case, arcade: Result, console: Result) -> dict:
    reg_mismatches = {
        name: {"mame": arcade.regs[name], "nexen": console.regs[name]}
        for name in REG_NAMES
        if arcade.regs[name] != console.regs[name]
    }
    stack = case.regs["A7"] & 0xFFFF
    excluded = set(range(stack, stack + 4))
    work_mismatches = [
        offset
        for offset, (left, right) in enumerate(zip(arcade.work, console.work))
        if offset not in excluded and left != right
    ]
    work_mismatch_values = [
        {
            "address": f"F0{offset:04X}",
            "mame": arcade.work[offset],
            "nexen": console.work[offset],
        }
        for offset in work_mismatches[:24]
    ]
    ccr_mismatch = (arcade.sr & CCR_MASK) != (console.sr & CCR_MASK)
    return {
        "case": case.name,
        "result": (
            "green"
            if not reg_mismatches and not ccr_mismatch and not work_mismatches
            else "red"
        ),
        "reg_mismatches": reg_mismatches,
        "mame_ccr": arcade.sr & CCR_MASK,
        "nexen_ccr": console.sr & CCR_MASK,
        "work_mismatch_count": len(work_mismatches),
        "work_mismatch_first": [f"F0{offset:04X}" for offset in work_mismatches[:24]],
        "work_mismatch_values": work_mismatch_values,
        "nexen_cycles": console.cycles,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--rom", type=Path, default=DEFAULT_ROM)
    parser.add_argument("--nexen", type=Path, default=DEFAULT_NEXEN)
    parser.add_argument("--nat", type=Path, default=DEFAULT_NAT)
    parser.add_argument("--port", type=int, default=7541)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    for path in (args.rom, args.nexen, args.nat):
        if not path.is_file():
            parser.error(f"missing required input: {path}")

    cases = make_cases()
    events: list[dict] = []
    provenance = {
        "event": "provenance",
        "scope": "function-local D96 MAME/Nexen differential; not fps",
        "mame": "/snap/bin/mame 0.287",
        "nexen": str(args.nexen.resolve()),
        "nexen_sha256": sha256(args.nexen),
        "rom": str(args.rom.resolve()),
        "rom_sha256": sha256(args.rom),
        "nat": str(args.nat.resolve()),
        "nat_sha256": sha256(args.nat),
        "entry_native": f"{ENTRY_NATIVE:06X}",
        "cases": len(cases),
        "time": time.time(),
    }
    events.append(provenance)
    print(json.dumps(provenance, sort_keys=True), flush=True)

    arcade_results: dict[str, Result] = {}
    mame = MameSession(
        mame="/snap/bin/mame",
        system="superman",
        rompath=str(MAME_TRACE / "roms"),
        workdir=str(MAME_TRACE),
        state_directory=str(MAME_TRACE / "sta"),
        extra_args=["-video", "none", "-sound", "none", "-nothrottle"],
    )
    try:
        mame.launch(boot_wait=25)
        for case in cases:
            arcade_results[case.name] = mame_result(mame, case)
            print(json.dumps({"event": "mame_case", "case": case.name}), flush=True)
    finally:
        mame.stop()

    with McpSession(
        rom=str(args.rom),
        mesen=str(args.nexen),
        cwd=ROOT,
        port=args.port,
        boot_wait=8.0,
        socket_timeout=120.0,
        stderr_log=ROOT / "build" / "playability-20260719" / "d96-nexen.stderr.log",
    ) as nexen:
        for case in cases:
            console = nexen_result(nexen, args.nat, case)
            event = {"event": "case", **compare(case, arcade_results[case.name], console)}
            events.append(event)
            print(json.dumps(event, sort_keys=True), flush=True)

    green = sum(event.get("result") == "green" for event in events)
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
            "".join(json.dumps(event, sort_keys=True) + "\n" for event in events)
        )
    return 0 if green == len(cases) else 1


if __name__ == "__main__":
    raise SystemExit(main())
