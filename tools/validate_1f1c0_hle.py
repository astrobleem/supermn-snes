#!/usr/bin/env python3
"""MAME/Nexen differential for the table-dispatched $01F1C0 object leaf.

MAME executes the original 68000 routine through its real RTS. Nexen enters the
deployed table-convention body through a synthetic RTE and the real xlat path;
the caller return is already on the 68K stack in both runs. The comparison is
all D/A registers, CCR X/N/Z/V/C, and the arcade's mapped 16 KiB work-RAM window.
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
MAME_EXE = Path(
    os.environ.get("SUPERMN_MAME_EXE", "/snap/mame/4339/mame")
)

sys.path.insert(0, str(MAME_MCP))
sys.path.insert(0, str(MESEN_PY))
os.environ["DOTNET_ROOT"] = "/home/chad/.dotnet10"
os.environ["PATH"] = "/home/chad/.dotnet10:" + os.environ.get("PATH", "")

from mame_mcp.session import MameSession  # noqa: E402
import mesen_mcp.session as _mesen_session  # noqa: E402

_mesen_session.validate_mesen_build = lambda *args, **kwargs: None
from mesen_mcp import McpSession  # noqa: E402


ENTRY_PC = 0x01F1C0
ENTRY_NATIVE = 0x97FC60
EXIT_PC = 0x000400
ENTRY_SP = 0xF03D00
SCRATCH_PC = 0xF0FF00
DF_SPIN = 0x00E2CF
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
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def be16(value: int) -> bytes:
    return (value & 0xFFFF).to_bytes(2, "big")


def be32(value: int) -> bytes:
    return (value & 0xFFFFFFFF).to_bytes(4, "big")


def le32(value: int) -> bytes:
    return (value & 0xFFFFFFFF).to_bytes(4, "little")


def build_case(
    name: str,
    seed: int,
    initial_d7: int,
    source_words: list[int],
    sr: int,
    *,
    source_addr: int = 0xF01000,
) -> Case:
    rng = random.Random(seed)
    work = bytearray(rng.randrange(256) for _ in range(0x10000))
    regs = {reg: rng.randrange(1 << 32) for reg in REG_NAMES}
    regs.update(
        {
            "D1": (regs["D1"] & 0xFFFF0000) | 0x0095,
            "D2": (regs["D2"] & 0xFFFF0000) | 0x009E,
            "D7": (regs["D7"] & 0xFFFF0000) | (initial_d7 & 0xFFFF),
            "A3": 0xF02000,
            "A4": source_addr,
            "A5": 0xF00000,
            "A6": 0xF03000,
            "A7": ENTRY_SP,
        }
    )
    if 0xF00000 <= source_addr <= 0xF0FFF6:
        for index, value in enumerate(source_words):
            offset = (source_addr & 0xFFFF) + index * 2
            work[offset:offset + 2] = be16(value)

    # The real caller return is present at function entry. The six bytes below
    # it are also preinitialized to the validation-only RTE frame so the MAME
    # and Nexen full-RAM comparison includes identical synthetic residue.
    work[ENTRY_SP - 0xF00000:ENTRY_SP - 0xF00000 + 4] = be32(EXIT_PC)
    rte = be16(sr) + be32(ENTRY_PC)
    rte_offset = ENTRY_SP - 6 - 0xF00000
    work[rte_offset:rte_offset + 6] = rte
    work[SCRATCH_PC - 0xF00000:SCRATCH_PC - 0xF00000 + 2] = bytes.fromhex("4e73")
    return Case(name, regs, sr, bytes(work))


def make_cases() -> list[Case]:
    return [
        build_case("positive-final-n", 0x1F1C001, 0x0000,
                   [0x0001, 0x0002, 0x0010, 0x0020, 0xFF90], 0x2410),
        build_case("positive-final-z", 0x1F1C002, 0x0001,
                   [0x0003, 0x0004, 0x0100, 0x0200, 0x0000], 0x2400),
        build_case("positive-final-byte-80", 0x1F1C003, 0x0002,
                   [0x0005, 0x0006, 0x0300, 0x0400, 0xAB80], 0x241F),
        build_case("negative-path", 0x1F1C004, 0xFFFF,
                   [0x7F00, 0x8000, 0x0101, 0xFE02, 0x0081], 0x240F),
        # Organic animation-table sources in immutable arcade ROM.
        build_case("rom-negative-1c602", 0x1F1C005, 0xFFFF,
                   [], 0x2410, source_addr=0x01C602),
        build_case("rom-negative-1c60c", 0x1F1C006, 0xFFFF,
                   [], 0x2400, source_addr=0x01C60C),
        # Organic Stage-1 object-list source observed immediately before the
        # first deterministic movement mismatch.  This address exercises the
        # same ROM-bank mapping as the live $F03A74 producer, rather than the
        # earlier generic animation-table fixtures.
        build_case("rom-organic-1daca", 0x1F1C008, 0x0000,
                   [], 0x2410, source_addr=0x01DACA),
        # Valid ROM read spanning a 64 KiB bank: deliberately outside the
        # direct helper's non-wrapping proof, so it exercises the generated
        # fallback without using an invalid address-space shape.
        build_case("rom-bank-crossing-fallback", 0x1F1C007, 0x0000,
                   [], 0x241F, source_addr=0x01FFF8),
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
    capture = session.cmd(
        "capture_at_pc",
        pc=EXIT_PC,
        addr=0xF00000,
        len=0x10000,
        nth=1,
        exp_sp=(case.regs["A7"] + 4) & 0xFFFFFF,
        maxFrames=30,
        timeout=30,
    )
    if not capture.get("registers"):
        raise RuntimeError(f"MAME did not return from $01F1C0 for {case.name}: {capture!r}")
    raw = capture["registers"]
    regs = {name: raw[name] & 0xFFFFFFFF for name in REG_NAMES[:-1]}
    regs["A7"] = raw["SP"] & 0xFFFFFFFF
    return Result(regs, raw["SR"] & 0xFFFF, bytes.fromhex(capture["hex"]))


def write_u16(m: McpSession, address: int, value: int) -> None:
    m.write_u16(address, value & 0xFFFF, DP_SPACE)


def nexen_result(m: McpSession, nat: Path, case: Case, entry_hook: int, spin_hook: int) -> Result:
    m.load_state(str(nat))
    m.pause()
    reg_blob = b"".join(le32(case.regs[f"D{i}"]) for i in range(8))
    reg_blob += b"".join(le32(case.regs[f"A{i}"]) for i in range(7))
    m.write_memory(DP_SPACE, 0x00, reg_blob.hex())
    m.write_memory(DP_SPACE, 0x3C, le32(case.regs["A7"] - 6).hex())
    for offset in range(0, 0x10000, 0x4000):
        m.write_memory(SNES_SPACE, 0x400000 + offset, case.work[offset:offset + 0x4000].hex())

    m.write_memory(DP_SPACE, 0x40, le32(SCRATCH_PC).hex())
    write_u16(m, 0x7C, 7)
    write_u16(m, 0xA8, 1)
    write_u16(m, 0xAA, 0)
    write_u16(m, 0x4A, 0)
    write_u16(m, 0x4C, 0)
    write_u16(m, 0xAC, 0x7000)
    write_u16(m, 0x0718, 0xFFF8)
    write_u16(m, 0x071A, 1)
    write_u16(m, 0x0712, 0)
    write_u16(m, 0x0714, 0)
    write_u16(m, 0x0710, EXIT_PC & 0xFFFF)
    write_u16(m, 0x0716, (EXIT_PC >> 16) & 0xFF)
    write_u16(m, 0x0702, 0)
    write_u16(m, 0x0704, 1)

    hit = m.run_until(max_frames=120, hook_handle=entry_hook)
    if (hit or {}).get("reason") != "hookFired":
        raise RuntimeError(f"Nexen did not enter native $01F1C0 for {case.name}: {hit!r}")
    start_cycles = int(m.get_cpu_state("Sa1")["cycleCount"])
    hit = m.run_until(max_frames=120, hook_handle=spin_hook)
    if (hit or {}).get("reason") != "hookFired" or not m.read_u16(0x0712, DP_SPACE):
        raise RuntimeError(f"Nexen did not freeze at ${EXIT_PC:06X} for {case.name}: {hit!r}")
    end_cycles = int(m.get_cpu_state("Sa1")["cycleCount"])

    raw_regs = bytes(m.read_memory(DP_SPACE, 0x00, 0x40))
    regs = {
        name: int.from_bytes(raw_regs[index * 4:index * 4 + 4], "little")
        for index, name in enumerate(REG_NAMES)
    }
    ccr = (
        (1 if m.read_u16(0x6E, DP_SPACE) else 0)
        | ((1 if m.read_u16(0x72, DP_SPACE) else 0) << 1)
        | ((1 if m.read_u16(0x60, DP_SPACE) else 0) << 2)
        | ((1 if m.read_u16(0x70, DP_SPACE) else 0) << 3)
        | ((1 if m.read_u16(0xA2, DP_SPACE) else 0) << 4)
    )
    work = bytes(m.read_memory(SNES_SPACE, 0x400000, 0x10000))
    return Result(regs, (case.sr & ~CCR_MASK) | ccr, work, end_cycles - start_cycles)


def compare(case: Case, arcade: Result, console: Result) -> dict:
    reg_mismatches = {
        name: {"mame": arcade.regs[name], "nexen": console.regs[name]}
        for name in REG_NAMES
        if arcade.regs[name] != console.regs[name]
    }
    work_mismatches = [
        index for index, (left, right) in enumerate(zip(arcade.work[:0x4000], console.work[:0x4000]))
        if left != right
    ]
    ccr_mismatch = (arcade.sr & CCR_MASK) != (console.sr & CCR_MASK)
    return {
        "case": case.name,
        "result": "green" if not reg_mismatches and not ccr_mismatch and not work_mismatches else "red",
        "reg_mismatches": reg_mismatches,
        "mame_ccr": arcade.sr & CCR_MASK,
        "nexen_ccr": console.sr & CCR_MASK,
        "work_mismatch_count": len(work_mismatches),
        "work_mismatch_first": [f"F0{offset:04X}" for offset in work_mismatches[:24]],
        "sa1_cycles_native_entry_to_exit_freeze": console.cycles,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--rom", type=Path, default=DEFAULT_ROM)
    parser.add_argument("--nexen", type=Path, default=DEFAULT_NEXEN)
    parser.add_argument("--nat", type=Path, default=DEFAULT_NAT)
    parser.add_argument("--port", type=int, default=7518)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    for path in (args.rom, args.nexen, args.nat):
        if not path.exists():
            parser.error(f"missing required input: {path}")
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)

    cases = make_cases()
    events: list[dict] = []
    provenance = {
        "event": "provenance",
        "scope": "function-local $01F1C0 MAME/Nexen xlat differential; mapped 16 KiB work RAM; not fps",
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

    arcade: dict[str, Result] = {}
    # capture_at_pc taps are deliberately retained by the MAME MCP Lua side. A
    # fresh process per case prevents a prior return tap from contaminating the
    # next synthetic entry/exit pair.
    for case in cases:
        mame = MameSession(
            mame=str(MAME_EXE),
            system="superman",
            rompath=str(MAME_TRACE / "roms"),
            workdir=str(MAME_TRACE),
            state_directory=str(MAME_TRACE / "sta"),
            extra_args=["-video", "none", "-sound", "none", "-nothrottle"],
        )
        try:
            mame.launch(boot_wait=25)
            arcade[case.name] = mame_result(mame, case)
            print(json.dumps({"event": "mame_case", "case": case.name}), flush=True)
        finally:
            mame.stop()

    with McpSession(
        rom=str(args.rom), mesen=str(args.nexen), cwd=ROOT, port=args.port,
        boot_wait=6.0, socket_timeout=120.0,
        stderr_log=(args.output.parent / "nexen.stderr.log") if args.output else None,
    ) as nexen:
        entry_hook = nexen.add_exec_hook(ENTRY_NATIVE, cpu_type="Sa1")
        spin_hook = nexen.add_exec_hook(DF_SPIN, cpu_type="Sa1")
        for case in cases:
            console = nexen_result(nexen, args.nat, case, entry_hook, spin_hook)
            event = {"event": "case", **compare(case, arcade[case.name], console)}
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
        args.output.write_text("".join(json.dumps(event, sort_keys=True) + "\n" for event in events))
    return 0 if green == len(cases) else 1


if __name__ == "__main__":
    raise SystemExit(main())
