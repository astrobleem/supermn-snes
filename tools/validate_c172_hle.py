#!/usr/bin/env python3
"""Function-local MAME/Nexen differential for the $00C172 hot coroutine path.

This is semantic evidence for one bounded native path, not an end-to-end FPS
measurement.  MAME executes the original 68000 routine from $C172 to the
fetch of its yield instruction at $C170.  Nexen reaches the native coroutine
entry through the real RTE/xlat dispatch and freezes on the same $C170 fetch.

The comparison covers all D/A registers, CCR X/N/Z/V/C, and every byte of the
arcade board's mapped low 16 KiB work-RAM window, including the exact final
$295A call residue below A7.
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


ENTRY_PC = 0x00C172
EXIT_PC = 0x00C170
ENTRY_NATIVE = 0x949D7E
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
    video_regions: list[tuple[int, int, bytes]]
    exit_pc: int = EXIT_PC
    expected_route: str = "inline"


@dataclass
class Result:
    regs: dict[str, int]
    sr: int
    work: bytes
    video_regions: list[bytes]
    video_writes: list[tuple[int, int, int]]
    cycles: int | None = None
    route: str = "unknown"


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
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
    speed: int,
    seed: int,
    negative_pattern: bool,
    final_y: int,
    entry_sp: int = ENTRY_SP,
    crossing_indices: tuple[int, ...] = (),
    table_base: int = 0x00055FF0,
    table_offset: int = 0x00A8,
    tile_base_pointer: int = 0x00057092,
    zero_table_abort: bool = False,
    expected_route: str | None = None,
) -> Case:
    rng = random.Random(seed)
    work = bytearray(rng.randrange(256) for _ in range(0x4000))
    work.extend([0xFF] * 0xC000)
    regs = {reg: rng.randrange(1 << 32) for reg in REG_NAMES}
    regs["A5"] = 0x00F00000
    regs["A7"] = entry_sp
    sr = 0x2700 | rng.randrange(0x20)

    work[0x1CBE:0x1CC2] = be32(0x0000295A)
    work[0x1CC2:0x1CC6] = be32(0x000029B6)
    work[0x2A32:0x2A34] = be16(rng.randrange(0x10000))
    work[0x2A34:0x2A36] = be16(rng.randrange(0x10000))
    work[0x2A36] = speed & 0xFF
    work[0x2A38:0x2A3C] = be32(table_base)
    work[0x2A3C:0x2A3E] = be16(table_offset)
    work[0x2A44:0x2A48] = be32(tile_base_pointer)

    crossings = set(crossing_indices)
    video_regions: list[tuple[int, int, bytes]] = []
    for index in range(14):
        base = 0x29B2 + index * 8
        if index in crossings:
            # Updated X == -64 takes the optional $29B6 branch exactly at the
            # signed BGT boundary.  The callback then adds $01C0 in place.
            x = (speed - 0x40) & 0xFFFF
        elif negative_pattern:
            # Results span 0 through -13: all are strictly greater than -64.
            x = (speed - index) & 0xFFFF
        else:
            x = (0x0100 + speed + index * 0x31) & 0xFFFF
        y = final_y if index == 13 else rng.randrange(0x10000)
        # Four-byte-separated destinations below $29B2 avoid aliasing the
        # source records while still exercising the complete scatter loop.
        destination_token = index * 0x40
        work[base:base + 2] = be16(x)
        work[base + 2:base + 4] = be16(y)
        work[base + 4:base + 6] = be16(destination_token)
        work[base + 6:base + 8] = be16(rng.randrange(0x10000))

        if index in crossings and not zero_table_abort:
            signed_row = destination_token if destination_token < 0x8000 else destination_token - 0x10000
            for video_address in (0xE00800 + signed_row, 0xE00C00 + signed_row):
                if not 0xE00000 <= video_address <= 0xE0FFC8:
                    raise ValueError(f"optional row ${destination_token:04X} leaves video RAM")
                video_regions.append(
                    (
                        video_address,
                        0x414000 | (video_address & 0x3FFF),
                        bytes(rng.randrange(256) for _ in range(0x38)),
                    )
                )

    if expected_route is None:
        expected_route = (
            "helper-zero-abort"
            if zero_table_abort
            else "helper-fast-callback"
            if crossings
            else "inline"
        )
    return Case(
        name,
        regs,
        sr,
        bytes(work),
        video_regions,
        0x00C236 if zero_table_abort else EXIT_PC,
        expected_route,
    )


def make_cases() -> list[Case]:
    return [
        build_case("speed-00-positive-x0", 0x00, 0xC17200, False, 0x00F8),
        build_case(
            "speed-05-negative-x1-low-task-stack",
            0x05,
            0xC17205,
            True,
            0x00FA,
            0xF00440,
        ),
        build_case("speed-7f-positive-x1", 0x7F, 0xC1727F, False, 0x8000),
        build_case("speed-ff-negative-x0", 0xFF, 0xC172FF, True, 0x0001),
        # Organic tick-542 shape: record 1 crosses to exactly -64 while the
        # table offset reaches $E0, advancing both persistent ROM pointers.
        build_case(
            "organic-record-1-crossing-and-pointer-rollover",
            0x03,
            0xC172A8,
            False,
            0x02C0,
            entry_sp=0xF01406,
            crossing_indices=(1,),
            table_offset=0x00A8,
        ),
        build_case(
            "two-crossings-second-rolls-pointer",
            0x05,
            0xC17270,
            False,
            0x0340,
            crossing_indices=(0, 1),
            table_offset=0x0070,
        ),
        # $000060 is an aligned all-zero long in the immutable arcade image.
        # This reaches the original $C22A early-abort state before any draw.
        build_case(
            "zero-table-early-abort",
            0x03,
            0xC17260,
            False,
            0x0100,
            crossing_indices=(0,),
            table_base=0x00000060,
            table_offset=0,
            zero_table_abort=True,
        ),
        # The high disjoint stack starts exactly where the complete 56-byte
        # callback residue remains above the persistent state block.
        build_case(
            "optional-high-stack-fast-callback",
            0x03,
            0xC172FB,
            False,
            0x0180,
            entry_sp=0xF02A80,
            crossing_indices=(0,),
            table_offset=0,
            expected_route="helper-fast-callback",
        ),
    ]


def mame_result(session: MameSession, case: Case) -> Result:
    session.pause()
    session.write_block(0xF00000, case.work)
    normalized_regions = []
    for video_address, shadow_address, video in case.video_regions:
        session.write_block(video_address, video)
        normalized_regions.append(
            (
                video_address,
                shadow_address,
                session.read_block(video_address, len(video)),
            )
        )
    case.video_regions = normalized_regions

    tap_lines = [
        "if C172_TAPS then for _,tap in ipairs(C172_TAPS) do tap:remove() end end",
        "C172_TAPS = {}",
        "C172_WRITES = {}",
        'local prog = M.devices[":maincpu"].spaces["program"]',
    ]
    for index, (video_address, _shadow_address, video) in enumerate(
        case.video_regions, 1
    ):
        tap_lines.extend(
            [
                f"C172_TAPS[{index}] = prog:install_write_tap(0x{video_address:X},",
                f'    0x{video_address + len(video) - 1:X}, "c172_write_{index}",',
                "    function(off, data, mask)",
                '      C172_WRITES[#C172_WRITES+1] = string.format("%06X,%08X,%08X", off, data, mask)',
                "      return data",
                "    end)",
            ]
        )
    tap_lines.append('return "armed"')
    session.exec_lua("\n".join(tap_lines))

    for name in REG_NAMES[:-1]:
        session.set_reg(name, case.regs[name])
    session.set_reg("SP", case.regs["A7"])
    session.set_reg("USP", case.regs["A7"])
    session.set_reg("SR", case.sr)
    session.set_reg("PC", ENTRY_PC)
    # $C236 is a TRAP #5.  Its opcode prefetch can precede the three clearing
    # instructions in MAME's read-tap capture, so observe the settled state at
    # the trap vector instead and recover the pre-trap SR/A7 from its frame.
    zero_abort = case.exit_pc == 0x00C236
    capture_pc = 0x000532 if zero_abort else case.exit_pc
    capture_sp = (
        (case.regs["A7"] - 6) & 0xFFFFFF
        if zero_abort
        else case.regs["A7"] & 0xFFFFFF
    )
    cap = session.cmd(
        "capture_at_pc",
        pc=capture_pc,
        addr=0xF00000,
        len=0x4000,
        nth=1,
        exp_sp=capture_sp,
        maxFrames=30,
        timeout=30,
    )
    if not cap.get("registers"):
        raise RuntimeError(
            f"MAME did not reach ${capture_pc:06X} for {case.name}: {cap!r}"
        )
    encoded_writes = session.exec_lua(
        'local out = table.concat(C172_WRITES or {}, ";") '
        "if C172_TAPS then for _,tap in ipairs(C172_TAPS) do tap:remove() end; C172_TAPS=nil end "
        "return out"
    )
    writes = []
    if encoded_writes:
        for item in encoded_writes.split(";"):
            address, data, mask = (int(field, 16) for field in item.split(","))
            writes.append((address, data, mask))
    expected_regions = [bytearray(video) for _, _, video in case.video_regions]
    for address, data, mask in writes:
        for region_index, (video_address, _shadow_address, video) in enumerate(
            case.video_regions
        ):
            relative = address - video_address
            if mask & 0xFF00 and 0 <= relative < len(video):
                expected_regions[region_index][relative] = (data >> 8) & 0xFF
            if mask & 0x00FF and 0 <= relative + 1 < len(video):
                expected_regions[region_index][relative + 1] = data & 0xFF
    regs = cap["registers"]
    work_result = bytes.fromhex(cap["hex"])
    out_regs = {name: regs[name] & 0xFFFFFFFF for name in REG_NAMES[:-1]}
    out_regs["A7"] = (
        case.regs["A7"] if zero_abort else regs["SP"] & 0xFFFFFFFF
    )
    result_sr = regs["SR"] & 0xFFFF
    if zero_abort:
        frame_offset = capture_sp & 0xFFFF
        result_sr = int.from_bytes(work_result[frame_offset:frame_offset + 2], "big")
    return Result(
        out_regs,
        result_sr,
        work_result,
        [bytes(region) for region in expected_regions],
        writes,
        route="arcade",
    )


def write_u16(m: McpSession, address: int, value: int) -> None:
    m.write_u16(address, value & 0xFFFF, DP_SPACE)


def park_snes_cpu(m: McpSession) -> None:
    """Keep the unrelated video supervisor out of this synthetic RAM lab."""

    park_pc = 0x7EF800
    m.write_memory("snesWorkRam", park_pc & 0x1FFFF, "80fe")
    m.write_memory(SNES_SPACE, 0x4200, "00")
    m.read_memory(SNES_SPACE, 0x4210, 1)
    state = dict(m.get_cpu_state("Snes"))
    state.update(
        {
            "pc": park_pc & 0xFFFF,
            "k": (park_pc >> 16) & 0xFF,
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
    m.tool("set_cpu_state", {key: state[key] for key in allowed if key in state})


def nexen_result(
    m: McpSession,
    nat: Path,
    case: Case,
    entry_hook: int,
    spin_hook: int,
    route_hooks: dict[str, int],
) -> Result:
    m.load_state(str(nat))
    m.pause()

    reg_blob = b"".join(le32(case.regs[f"D{i}"]) for i in range(8))
    reg_blob += b"".join(le32(case.regs[f"A{i}"]) for i in range(7))
    m.write_memory(DP_SPACE, 0x00, reg_blob.hex())
    # The synthetic RTE consumes SR.w + PC.l and must leave the task's A7 at
    # the exact function-entry value.
    rte_sp = (case.regs["A7"] - 6) & 0xFFFFFFFF
    m.write_memory(DP_SPACE, 0x3C, le32(rte_sp).hex())

    for offset in range(0, 0x10000, 0x4000):
        m.write_memory(
            SNES_SPACE,
            0x400000 + offset,
            case.work[offset:offset + 0x4000].hex(),
        )
    for _video_address, shadow_address, video in case.video_regions:
        m.write_memory(SNES_SPACE, shadow_address, video.hex())
    frame = be16(case.sr) + be32(ENTRY_PC)
    m.write_memory(SNES_SPACE, 0x400000 | (rte_sp & 0xFFFF), frame.hex())
    m.write_memory(SNES_SPACE, 0x400000 | (SCRATCH_PC & 0xFFFF), "4e73")

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
    park_snes_cpu(m)

    entry_hit = m.run_until(max_frames=120, hook_handle=entry_hook)
    if (entry_hit or {}).get("reason") != "hookFired":
        raise RuntimeError(f"Nexen did not enter native C172 for {case.name}: {entry_hit!r}")
    start_cycles = int(m.get_cpu_state("Sa1")["cycleCount"])

    route_steps = {
        "inline": ("hot_finish",),
        "helper-fast-callback": ("helper", "callback", "hot_finish"),
        "helper-zero-abort": ("helper", "zero_done"),
        "helper-cold-fallback": ("helper", "cold"),
    }
    try:
        expected_steps = route_steps[case.expected_route]
    except KeyError as exc:
        raise RuntimeError(f"unknown expected route {case.expected_route}") from exc
    for step in expected_steps:
        hit = m.run_until(max_frames=120, hook_handle=route_hooks[step])
        if (hit or {}).get("reason") != "hookFired":
            raise RuntimeError(
                f"Nexen missed C172 route step {step} for {case.name}: {hit!r}"
            )
    if case.expected_route != "helper-zero-abort":
        exit_hit = m.run_until(max_frames=120, hook_handle=spin_hook)
        if (exit_hit or {}).get("reason") != "hookFired" or not m.read_u16(
            0x0712, DP_SPACE
        ):
            raise RuntimeError(
                f"Nexen did not freeze at ${case.exit_pc:06X} for {case.name}: {exit_hit!r}"
            )
    end_cycles = int(m.get_cpu_state("Sa1")["cycleCount"])

    raw_regs = bytes(m.read_memory(DP_SPACE, 0x00, 0x40))
    out_regs = {}
    for index, name in enumerate(REG_NAMES):
        offset = index * 4
        out_regs[name] = int.from_bytes(raw_regs[offset:offset + 4], "little")
    ccr = (
        (1 if m.read_u16(0x6E, DP_SPACE) else 0)
        | ((1 if m.read_u16(0x72, DP_SPACE) else 0) << 1)
        | ((1 if m.read_u16(0x60, DP_SPACE) else 0) << 2)
        | ((1 if m.read_u16(0x70, DP_SPACE) else 0) << 3)
        | ((1 if m.read_u16(0xA2, DP_SPACE) else 0) << 4)
    )
    return Result(
        out_regs,
        (case.sr & ~CCR_MASK) | ccr,
        bytes(m.read_memory(SNES_SPACE, 0x400000, 0x4000)),
        [
            bytes(m.read_memory(SNES_SPACE, shadow_address, len(video)))
            for _video_address, shadow_address, video in case.video_regions
        ],
        [],
        end_cycles - start_cycles,
        case.expected_route,
    )


def compare(case: Case, arcade: Result, console: Result) -> dict:
    reg_mismatches = {
        name: {"mame": arcade.regs[name], "nexen": console.regs[name]}
        for name in REG_NAMES
        if arcade.regs[name] != console.regs[name]
    }
    ccr_mismatch = (arcade.sr & CCR_MASK) != (console.sr & CCR_MASK)
    # The zero-abort function itself does not touch the six bytes below A7.
    # MAME has its outgoing TRAP frame there; Nexen has the incoming synthetic
    # RTE frame used solely to enter the coroutine escape.  Exclude exactly
    # that harness-owned slot and compare every other mapped byte.
    work_exclusions: set[int] = set()
    if case.exit_pc == 0x00C236:
        entry_sp = case.regs["A7"] & 0xFFFF
        work_exclusions.update(range(entry_sp - 6, entry_sp))
    work_mismatches = [
        index
        for index, (left, right) in enumerate(zip(arcade.work, console.work))
        if index not in work_exclusions and left != right
    ]
    video_mismatches = []
    for (
        region_index,
        ((video_address, shadow_address, _video), arcade_region, console_region),
    ) in enumerate(
        zip(case.video_regions, arcade.video_regions, console.video_regions)
    ):
        for offset, (left, right) in enumerate(zip(arcade_region, console_region)):
            if left != right:
                video_mismatches.append(
                    (
                        region_index,
                        offset,
                        video_address,
                        shadow_address,
                        left,
                        right,
                    )
                )
    route_mismatch = console.route != case.expected_route
    return {
        "case": case.name,
        "exit_pc": f"{case.exit_pc:06X}",
        "expected_route": case.expected_route,
        "nexen_route": console.route,
        "result": "green"
        if not reg_mismatches
        and not ccr_mismatch
        and not work_mismatches
        and not video_mismatches
        and not route_mismatch
        else "red",
        "reg_mismatches": reg_mismatches,
        "mame_ccr": arcade.sr & CCR_MASK,
        "nexen_ccr": console.sr & CCR_MASK,
        "work_mismatch_count": len(work_mismatches),
        "work_exclusions": [f"F0{offset:04X}" for offset in sorted(work_exclusions)],
        "work_mismatch_first": [
            {
                "address": f"F0{offset:04X}",
                "mame": arcade.work[offset],
                "nexen": console.work[offset],
            }
            for offset in work_mismatches[:24]
        ],
        "video_mismatch_count": len(video_mismatches),
        "mame_video_write_count": len(arcade.video_writes),
        "video_mismatch_first": [
            {
                "address": f"{video_address + offset:06X}/{shadow_address + offset:06X}",
                "mame": left,
                "nexen": right,
            }
            for (
                _region_index,
                offset,
                video_address,
                shadow_address,
                left,
                right,
            ) in video_mismatches[:24]
        ],
        "sa1_cycles_native_entry_to_exit_freeze": console.cycles,
    }


def symbol_address(path: Path, bank: int, name: str) -> int:
    for raw in path.read_text(encoding="utf-8-sig").splitlines():
        fields = raw.split()
        if len(fields) == 2 and fields[1] == name:
            return bank | int(fields[0].split(":", 1)[1], 16)
    raise RuntimeError(f"missing symbol {name} in {path}")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--rom", type=Path, default=DEFAULT_ROM)
    parser.add_argument("--nexen", type=Path, default=DEFAULT_NEXEN)
    parser.add_argument("--nat", type=Path, default=DEFAULT_NAT)
    parser.add_argument("--port", type=int, default=7517)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    for path in (args.rom, args.nexen, args.nat):
        if not path.exists():
            parser.error(f"missing required input: {path}")

    args.rom = args.rom.resolve()
    args.nexen = args.nexen.resolve()
    args.nat = args.nat.resolve()
    cases = make_cases()
    events: list[dict] = []
    provenance = {
        "event": "provenance",
        "scope": "function-local C172 hot-path MAME/Nexen differential; not fps",
        "mame": "/snap/bin/mame 0.287",
        "nexen": str(args.nexen.resolve()),
        "nexen_sha256": sha256(args.nexen),
        "rom": str(args.rom.resolve()),
        "rom_sha256": sha256(args.rom),
        "nat": str(args.nat.resolve()),
        "nat_sha256": sha256(args.nat),
        "cases": len(cases),
        "time": time.time(),
    }
    events.append(provenance)
    print(json.dumps(provenance, sort_keys=True), flush=True)

    arcade: dict[str, Result] = {}
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
            arcade[case.name] = mame_result(mame, case)
            print(json.dumps({"event": "mame_case", "case": case.name}), flush=True)
    finally:
        mame.stop()

    stderr_log = (
        args.output.with_suffix(".nexen.stderr.log")
        if args.output
        else ROOT / "build/c172-differential.nexen.stderr.log"
    )
    stderr_log.parent.mkdir(parents=True, exist_ok=True)
    with McpSession(
        rom=str(args.rom),
        mesen=str(args.nexen),
        cwd=str(ROOT),
        port=args.port,
        boot_wait=8.0,
        socket_timeout=120.0,
        stderr_log=stderr_log,
    ) as nexen:
        entry_hook = nexen.add_exec_hook(ENTRY_NATIVE, cpu_type="Sa1")
        spin_hook = nexen.add_exec_hook(DF_SPIN, cpu_type="Sa1")
        route_hooks = {
            "helper": nexen.add_exec_hook(0x94D800, cpu_type="Sa1"),
            "callback": nexen.add_exec_hook(
                symbol_address(ROOT / "src/escbank7.sym", 0x9D0000, "h29b6_fast"),
                cpu_type="Sa1",
            ),
            "hot_finish": nexen.add_exec_hook(
                symbol_address(ROOT / "src/escbank2.sym", 0x940000, "hc172_hot_finish"),
                cpu_type="Sa1",
            ),
            "zero_done": nexen.add_exec_hook(
                symbol_address(ROOT / "src/escbank2.sym", 0x940000, "hcx_table_zero_done"),
                cpu_type="Sa1",
            ),
            "cold": nexen.add_exec_hook(
                symbol_address(ROOT / "src/escbank2.sym", 0x940000, "hc172_cold"),
                cpu_type="Sa1",
            ),
        }
        for case in cases:
            console = nexen_result(
                nexen,
                args.nat,
                case,
                entry_hook,
                spin_hook,
                route_hooks,
            )
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
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text("".join(json.dumps(event, sort_keys=True) + "\n" for event in events))
    return 0 if green == len(cases) else 1


if __name__ == "__main__":
    raise SystemExit(main())
