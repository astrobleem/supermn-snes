#!/usr/bin/env python3
"""MAME/Nexen differential for the $00C892 post-yield coroutine continuation.

The four cases force every bounded exit: yield again at $C890, loop expiry at
$C746, D7 failure at $C8BA, and BTST cancellation at $C8DA. Nexen enters the
deployed body through the real RTE/xlat route. Comparison covers all D/A regs,
CCR X/N/Z/V/C, and the complete mapped 16 KiB arcade work-RAM window.
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


ENTRY_PC = 0x00C892
ENTRY_NATIVE = 0x98FD70
ENTRY_4A9E = 0x99A4E1
ENTRY_SP = 0xF03D00
SCRATCH_PC = 0xF03F00
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
    exit_pc: int


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


def put_word(work: bytearray, offset: int, value: int) -> None:
    work[offset:offset + 2] = be16(value)


def build_case(name: str, seed: int, d2: int, exit_pc: int, *, bit_set: bool = False,
               force_d7_failure: bool = False) -> Case:
    rng = random.Random(seed)
    work = bytearray(rng.randrange(256) for _ in range(0x4000))
    regs = {reg: rng.randrange(1 << 32) for reg in REG_NAMES}
    regs.update(
        {
            "D1": (regs["D1"] & 0xFFFF0000) | 0x0003,
            "D2": (regs["D2"] & 0xFFFF0000) | (d2 & 0xFFFF),
            "A5": 0xF00000,
            "A6": 0xF02F00,
            "A7": ENTRY_SP,
        }
    )
    sr = 0x2415

    # Default $4A9E path: $3EE2 == 0 and $1C62 == 0 -> D7.w = 0.
    put_word(work, 0x3EE2, 0)
    put_word(work, 0x1C62, 0)
    put_word(work, 0x1C76, 0)
    put_word(work, 0x2936, 0)
    put_word(work, 0x2A4A, 0x0008 if bit_set else 0)

    if force_d7_failure:
        # Active-input path for argument D1=3: mask bit present, clear input
        # high bit, then $4B7A returns D7.w = -1.
        put_word(work, 0x3EE2, 1)
        put_word(work, 0x1C76, 1)
        put_word(work, 0x2936, 0x0008)
        put_word(work, 0x2A4A, 0)
        work[0x1C53] = 0xFF
        work[0x1C4F] = 0x00

    rte = be16(sr) + be32(ENTRY_PC)
    rte_offset = ENTRY_SP - 6 - 0xF00000
    work[rte_offset:rte_offset + 6] = rte
    work[SCRATCH_PC - 0xF00000:SCRATCH_PC - 0xF00000 + 2] = bytes.fromhex("4e73")
    return Case(name, regs, sr, bytes(work), exit_pc)


def make_cases() -> list[Case]:
    return [
        build_case("loop-yield-c890", 0xC89201, 1, 0x00C890),
        build_case("loop-expiry-c746", 0xC89202, 0, 0x00C746),
        build_case("bit-cancel-c8da", 0xC89203, 7, 0x00C8DA, bit_set=True),
        build_case("d7-failure-c8ba", 0xC89204, 7, 0x00C8BA, force_d7_failure=True),
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
    # MAME 0.287's arbitrary-PC hook fires on opcode prefetch, before a preceding
    # DBRA/branch has retired. Substitute only the first word at the selected exit
    # with a validation-only NOP and capture the following word. NOP has no state
    # effects, so that second prefetch is the committed post-$C892 boundary.
    session.exec_lua(
        "_G.c892_exit_nop = machine.devices[':maincpu'].spaces['program']"
        f":install_read_tap(0x{case.exit_pc:06X}, 0x{case.exit_pc + 1:06X}, "
        "'c892_exit_nop', function(offset, data, mask) return 0x4E71 end); return true"
    )
    capture_pc = case.exit_pc + 2
    capture = session.cmd(
        "capture_at_pc", pc=capture_pc, addr=0xF00000, len=0x4000,
        nth=1, exp_sp=case.regs["A7"] & 0xFFFFFF, maxFrames=30, timeout=30,
    )
    if not capture.get("registers"):
        raise RuntimeError(
            f"MAME did not reach validation boundary ${capture_pc:06X} from $C892 "
            f"for {case.name}: {capture!r}"
        )
    raw = capture["registers"]
    regs = {name: raw[name] & 0xFFFFFFFF for name in REG_NAMES[:-1]}
    regs["A7"] = raw["SP"] & 0xFFFFFFFF
    return Result(regs, raw["SR"] & 0xFFFF, bytes.fromhex(capture["hex"]))


def write_u16(m: McpSession, address: int, value: int) -> None:
    m.write_u16(address, value & 0xFFFF, DP_SPACE)


def nexen_result(
    m: McpSession, nat: Path, case: Case, entry_hook: int, callee_hook: int, spin_hook: int
) -> Result:
    m.load_state(str(nat))
    m.pause()
    reg_blob = b"".join(le32(case.regs[f"D{i}"]) for i in range(8))
    reg_blob += b"".join(le32(case.regs[f"A{i}"]) for i in range(7))
    m.write_memory(DP_SPACE, 0x00, reg_blob.hex())
    m.write_memory(DP_SPACE, 0x3C, le32(case.regs["A7"] - 6).hex())
    m.write_memory(SNES_SPACE, 0x400000, case.work.hex())

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
    write_u16(m, 0x0710, case.exit_pc & 0xFFFF)
    write_u16(m, 0x0716, (case.exit_pc >> 16) & 0xFF)
    write_u16(m, 0x0702, 0)
    write_u16(m, 0x0704, 1)

    hit = m.run_until(max_frames=120, hook_handle=entry_hook)
    if (hit or {}).get("reason") != "hookFired":
        raise RuntimeError(f"Nexen did not enter native $C892 for {case.name}: {hit!r}")
    start_cycles = int(m.get_cpu_state("Sa1")["cycleCount"])
    hit = m.run_until(max_frames=120, hook_handle=callee_hook)
    if (hit or {}).get("reason") != "hookFired":
        raise RuntimeError(f"Nexen $C892 did not call native $4A9E for {case.name}: {hit!r}")
    hit = m.run_until(max_frames=120, hook_handle=spin_hook)
    if (hit or {}).get("reason") != "hookFired" or not m.read_u16(0x0712, DP_SPACE):
        raise RuntimeError(f"Nexen did not freeze at ${case.exit_pc:06X} for {case.name}: {hit!r}")
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
    work = bytes(m.read_memory(SNES_SPACE, 0x400000, 0x4000))
    return Result(regs, (case.sr & ~CCR_MASK) | ccr, work, end_cycles - start_cycles)


def compare(case: Case, arcade: Result, console: Result) -> dict:
    reg_mismatches = {
        name: {"mame": arcade.regs[name], "nexen": console.regs[name]}
        for name in REG_NAMES if arcade.regs[name] != console.regs[name]
    }
    work_mismatches = [
        index for index, (left, right) in enumerate(zip(arcade.work, console.work))
        if left != right
    ]
    ccr_mismatch = (arcade.sr & CCR_MASK) != (console.sr & CCR_MASK)
    return {
        "case": case.name,
        "exit_pc": f"{case.exit_pc:06X}",
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
    parser.add_argument("--port", type=int, default=7519)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    for path in (args.rom, args.nexen, args.nat):
        if not path.exists():
            parser.error(f"missing required input: {path}")

    cases = make_cases()
    events: list[dict] = []
    provenance = {
        "event": "provenance",
        "scope": "function-local $C892 MAME/Nexen coroutine differential; mapped 16 KiB work RAM; not fps",
        "mame": "/snap/bin/mame 0.287",
        "nexen": str(args.nexen.resolve()),
        "nexen_sha256": sha256(args.nexen),
        "rom": str(args.rom.resolve()),
        "rom_sha256": sha256(args.rom),
        "nat": str(args.nat.resolve()),
        "nat_sha256": sha256(args.nat),
        "entry_native": f"{ENTRY_NATIVE:06X}",
        "callee_native": f"{ENTRY_4A9E:06X}",
        "mame_boundary_method": "validation-only NOP at exit, capture exit+2 prefetch",
        "cases": len(cases),
        "time": time.time(),
    }
    events.append(provenance)
    print(json.dumps(provenance, sort_keys=True), flush=True)

    arcade: dict[str, Result] = {}
    for case in cases:
        mame = MameSession(
            mame="/snap/bin/mame", system="superman",
            rompath=str(MAME_TRACE / "roms"), workdir=str(MAME_TRACE),
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
        rom=str(args.rom), mesen=str(args.nexen), port=args.port,
        boot_wait=6.0, socket_timeout=120.0,
    ) as nexen:
        entry_hook = nexen.add_exec_hook(ENTRY_NATIVE, cpu_type="Sa1")
        callee_hook = nexen.add_exec_hook(ENTRY_4A9E, cpu_type="Sa1")
        spin_hook = nexen.add_exec_hook(DF_SPIN, cpu_type="Sa1")
        for case in cases:
            console = nexen_result(
                nexen, args.nat, case, entry_hook, callee_hook, spin_hook
            )
            event = {"event": "case", **compare(case, arcade[case.name], console)}
            events.append(event)
            print(json.dumps(event, sort_keys=True), flush=True)

    green = sum(event.get("result") == "green" for event in events)
    summary = {
        "event": "summary", "green": green, "red": len(cases) - green,
        "total": len(cases), "result": "green" if green == len(cases) else "red",
        "time": time.time(),
    }
    events.append(summary)
    print(json.dumps(summary, sort_keys=True), flush=True)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text("".join(json.dumps(event, sort_keys=True) + "\n" for event in events))
    return 0 if green == len(cases) else 1


if __name__ == "__main__":
    raise SystemExit(main())
