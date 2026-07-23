#!/usr/bin/env python3
"""Function-local MAME/Nexen differential for the $024D98 slot scanner.

MAME executes the original 68000 subroutine through its RTS.  Nexen enters the
real bank-$99 native escape directly with the same architectural state and a
bank-$00 sentinel return.  The comparison covers all D/A registers, CCR
X/N/Z/V/C, and the complete mapped low 16 KiB work-RAM window (apart from the
synthetic return slot, whose two harnesses necessarily contain different PCs).

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


ENTRY_PC = 0x024D98
ENTRY_NATIVE = 0x999D3B
RETURN_PC = 0xF03E00
ENTRY_SP = 0xF03D00
# Stable bank-$00 `bra ispin` loop.  Exec hooks are non-pausing notifications,
# so returning to the debug-freeze implementation at $E2CF would let it mutate
# the emulated register file before the client samples it.
NATIVE_RETURN = 0x00D15A
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
    flags: int,
    delta: int,
    slots: list[tuple[int, int, int, int]],
    d2_high: int = 0,
    a5: int = 0x00F00000,
    x: int = 0,
) -> Case:
    if len(slots) != 4:
        raise ValueError("exactly four slots are required")
    rng = random.Random(seed)
    work = bytearray(rng.randrange(256) for _ in range(0x4000))
    work.extend([0xFF] * 0xC000)
    regs = {reg: rng.randrange(1 << 32) for reg in REG_NAMES}
    regs["A5"] = a5
    regs["A7"] = ENTRY_SP
    regs["D2"] = ((d2_high & 0xFFFF) << 16) | (regs["D2"] & 0xFFFF)
    sr = 0x2700 | rng.randrange(0x10) | ((x & 1) << 4)

    base = a5 & 0xFFFF
    work[base + 2 : base + 4] = be16(flags)
    work[base + 0x2A32 : base + 0x2A34] = be16(delta)
    for index, (slot_id, timer, active, f8) in enumerate(slots):
        offset = base + 0x3702 + index * 12
        work[offset : offset + 2] = be16(slot_id)
        work[offset + 2 : offset + 4] = be16(timer)
        work[offset + 4 : offset + 8] = be32(active)
        work[offset + 8 : offset + 10] = be16(f8)
        work[offset + 10 : offset + 12] = be16(rng.randrange(0x10000))

    work[ENTRY_SP & 0xFFFF : (ENTRY_SP & 0xFFFF) + 4] = be32(RETURN_PC)
    work[RETURN_PC & 0xFFFF : (RETURN_PC & 0xFFFF) + 2] = bytes.fromhex("60fe")
    return Case(name, regs, sr, bytes(work))


def make_cases() -> list[Case]:
    inactive = [(0, 0, 0, 0)] * 4
    return [
        build_case(
            "all-inactive-preserve-x0", 0x24D980, flags=0xA55A, delta=7,
            slots=inactive, x=0,
        ),
        build_case(
            "current-shape-bit14-set-x1", 0x24D981, flags=0x4000, delta=0,
            slots=[(14, 0x0190, 0x0001D516, 0x00B4), *inactive[:3]], x=1,
        ),
        build_case(
            "mixed-set-decrement-clear-final-set", 0x24D982, flags=0x000A, delta=5,
            slots=[
                (1, 8, 1, 0x0012),
                (2, 9, 1, 0x0001),
                (3, 5, 1, 0x7777),
                (3, 7, 1, 0x2222),
            ],
        ),
        build_case(
            "final-negative-clear-borrow", 0x24D983, flags=0x0000, delta=2,
            slots=[*inactive[:3], (2, 1, 0x89ABCDEF, 0x3456)],
        ),
        build_case(
            "dynamic-high-d2-bit20", 0x24D984, flags=0x0000, delta=1,
            slots=[*inactive[:3], (20, 4, 1, 0x0000)], d2_high=0x0010,
        ),
        build_case(
            "noncanonical-a5-cold-fallback", 0x24D985, flags=0x0002, delta=3,
            slots=[(1, 9, 1, 0x0020), *inactive[:3]], a5=0x00F00010,
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
        exp_sp=(ENTRY_SP + 4) & 0xFFFFFF,
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
    # This is a function-isolation harness, not a scheduler test.  Prevent an
    # SA-1 IRQ from swapping the shared emulated register file mid-call.
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
    reg_blob += b"".join(le32(case.regs[f"A{i}"]) for i in range(7))
    reg_blob += le32((case.regs["A7"] + 4) & 0xFFFFFFFF)
    m.write_memory(DP_SPACE, 0x00, reg_blob.hex())
    for offset in range(0, 0x10000, 0x4000):
        m.write_memory(
            SNES_SPACE,
            0x400000 + offset,
            case.work[offset : offset + 0x4000].hex(),
        )

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

    # Use a fresh hook per case.  Reusing a non-pausing exec hook across state
    # loads can leave a prior return notification queued and sample the next
    # case before it has actually completed.
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
    )


def compare(case: Case, arcade: Result, console: Result) -> dict:
    reg_mismatches = {
        name: {"mame": arcade.regs[name], "nexen": console.regs[name]}
        for name in REG_NAMES
        if arcade.regs[name] != console.regs[name]
    }
    excluded = set(range(ENTRY_SP & 0xFFFF, (ENTRY_SP & 0xFFFF) + 4))
    work_mismatches = [
        offset
        for offset, (left, right) in enumerate(zip(arcade.work, console.work))
        if offset not in excluded and left != right
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
        "work_mismatch_first": [f"F0{offset:04X}" for offset in work_mismatches[:16]],
        "nexen_cycles": console.cycles,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--rom", type=Path, default=DEFAULT_ROM)
    parser.add_argument("--nexen", type=Path, default=DEFAULT_NEXEN)
    parser.add_argument("--nat", type=Path, default=DEFAULT_NAT)
    parser.add_argument("--port", type=int, default=7539)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    for path in (args.rom, args.nexen, args.nat):
        if not path.is_file():
            parser.error(f"missing required input: {path}")

    cases = make_cases()
    events: list[dict] = []
    provenance = {
        "event": "provenance",
        "scope": "function-local MAME/Nexen differential; not fps",
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
            print(
                json.dumps({"event": "mame_case", "case": case.name, "result": "captured"}),
                flush=True,
            )
    finally:
        mame.stop()

    with McpSession(
        rom=str(args.rom),
        mesen=str(args.nexen),
        cwd=ROOT,
        port=args.port,
        boot_wait=6.0,
        socket_timeout=120.0,
        stderr_log=ROOT / "build" / "playability-20260719" / "24d98-nexen.stderr.log",
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
