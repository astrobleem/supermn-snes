#!/usr/bin/env python3
"""Differentially validate the hand-HLE render helpers against MAME 0.287.

The older per-function validator compares registers and $F0 work RAM from a
recorded-playback entry/exit pair, but it cannot observe arcade $B0/$D0 video
RAM and some valid calls return through RAM in a way its replay exit hook misses.
This harness instead makes deterministic synthetic calls to the original 68000
functions in MAME and to the shipped native escapes in Nexen.  It compares:

  * D0-D7, A0-A7
  * CCR X/N/Z/V/C
  * all 64 KiB of $F0 work RAM (excluding only the synthetic return/code bytes)
  * the exact arcade $B0/$D0 bytes against their SNES $41 shadow mapping

This is function-local differential evidence, not an end-to-end performance or
playability measurement.
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


# The arcade board maps only the live low work-RAM window.  Keep the synthetic
# MAME stack/return inside it; $F0E000 is unmapped and produces a bus derail.
RETURN_PC = 0xF03E00
ENTRY_SP = 0xF03D00
SCRATCH_PC = 0xF0FF00
DP_SPACE = "Sa1Memory"
SNES_SPACE = "snesMemory"
DF_SPIN = 0x00E2CF
NATIVE_RETURN = 0x00D15A  # bank-$00 ispin; reached via the $00FF return sentinel
NATIVE_ENTRIES = {
    0x0008C2: 0x92B338,
    0x0026A0: 0x928EF6,
    0x00158E: 0x99F800,
    0x0017B4: 0x959B00,
    0x0020E8: 0x00EDBA,
}
REG_NAMES = [f"D{i}" for i in range(8)] + [f"A{i}" for i in range(8)]
CCR_MASK = 0x1F


@dataclass
class Case:
    name: str
    target: int
    regs: dict[str, int]
    sr: int
    work: bytes
    video_regions: list[tuple[int, int, bytes]]


@dataclass
class Result:
    regs: dict[str, int]
    sr: int
    work: bytes
    video_regions: list[bytes]
    video_writes: list[tuple[int, int, int]]
    cycles: int = 0


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def be32(value: int) -> bytes:
    return (value & 0xFFFFFFFF).to_bytes(4, "big")


def le32(value: int) -> bytes:
    return (value & 0xFFFFFFFF).to_bytes(4, "little")


def build_case(
    target: int,
    name: str,
    mask: int,
    seed: int,
    a5: int = 0xF00000,
    a7: int = ENTRY_SP,
) -> Case:
    rng = random.Random(seed)
    work = bytearray(rng.randrange(256) for _ in range(0x4000)) + bytearray([0xFF] * 0xC000)
    regs = {reg: rng.randrange(1 << 32) for reg in REG_NAMES}
    regs["A5"] = a5
    regs["A7"] = a7
    sr = 0x2700 | rng.randrange(0x20)

    if target == 0x0008C2:
        base = (a5 & 0xFFFF) + 0x1712
        if base + 0x404 > 0x10000:
            raise ValueError("8c2 test source crosses work RAM")
        for i in range(0x400):
            work[base + i] = rng.randrange(256)
        work[base + 0x400 : base + 0x404] = be32(mask)
        video_regions = [
            (0xB00000, 0x412000, bytes(rng.randrange(256) for _ in range(0x400)))
        ]
    elif target == 0x0026A0:
        fixed = 0x28EA
        source = (a5 & 0xFFFF) + 0x28EA
        if source + 0x40 > 0x10000:
            raise ValueError("26a0 test source crosses work RAM")
        for i in range(0x40):
            work[source + i] = rng.randrange(256)
        for bit in range(16):
            value = work[fixed + bit * 4]
            work[fixed + bit * 4] = (value & 0xFE) | ((mask >> bit) & 1)
        video_regions = [
            (0xD00400, 0x413400, bytes(rng.randrange(256) for _ in range(0x208)))
        ]
    elif target == 0x00158E:
        # Three fixed 1020-byte source streams copied to disjoint arcade video
        # windows.  Keep every source inside the arcade's mapped low 16 KiB.
        for relative in (0x1CF6, 0x20F2, 0x24EE):
            source = (a5 & 0xFFFF) + relative
            if source + 0x03FC > 0x4000:
                raise ValueError("158e test source crosses mapped work RAM")
            for i in range(0x03FC):
                work[source + i] = rng.randrange(256)
        video_regions = [
            (0xD00002, 0x413002, bytes(rng.randrange(256) for _ in range(0x03FC))),
            (0xE00402, 0x414402, bytes(rng.randrange(256) for _ in range(0x03FC))),
            (0xE00002, 0x414002, bytes(rng.randrange(256) for _ in range(0x03FC))),
        ]
    elif target == 0x0017B4:
        # Short form of the same three-plane OBJ transfer: 34 MOVE.Ls (136
        # bytes) per plane. Force the last logical long so the cases exercise
        # MOVE.L's N/Z result as well as byte-for-byte shadow behavior.
        for relative in (0x1CF6, 0x20F2, 0x24EE):
            source = (a5 & 0xFFFF) + relative
            if source + 0x0088 > 0x4000:
                raise ValueError("17b4 test source crosses mapped work RAM")
            for i in range(0x0088):
                work[source + i] = rng.randrange(256)
        final_source = (a5 & 0xFFFF) + 0x24EE + 0x0084
        work[final_source : final_source + 4] = be32(mask)
        video_regions = [
            (0xD00002, 0x413002, bytes(rng.randrange(256) for _ in range(0x0088))),
            (0xE00402, 0x414402, bytes(rng.randrange(256) for _ in range(0x0088))),
            (0xE00002, 0x414002, bytes(rng.randrange(256) for _ in range(0x0088))),
        ]
    elif target == 0x0020E8:
        # Organic $DA62 call shape.  ``mask`` carries the signed row-coordinate
        # argument so the old $0150 capture and the later $014D gameplay state
        # exercise the same descriptor through distinct live positions.
        row_coordinate = mask & 0xFFFF
        stack = a7 & 0xFFFF
        work[stack + 4 : stack + 6] = (0x0380).to_bytes(2, "big")
        work[stack + 6 : stack + 8] = (0x2800).to_bytes(2, "big")
        work[stack + 8 : stack + 10] = (0x0000).to_bytes(2, "big")
        work[stack + 10 : stack + 12] = row_coordinate.to_bytes(2, "big")
        work[stack + 12 : stack + 16] = be32(0x000366F2)
        work[stack + 16 : stack + 18] = (0x003F).to_bytes(2, "big")
        video_regions = [
            (0xE00B80, 0x414B80, bytes(rng.randrange(256) for _ in range(0x0040))),
            (0xE00F80, 0x414F80, bytes(rng.randrange(256) for _ in range(0x0080))),
        ]
    else:
        raise ValueError(f"unsupported helper ${target:06X}")

    # The synthetic MAME call starts at the function entry with [SP]=return.
    work[a7 & 0xFFFF : (a7 & 0xFFFF) + 4] = be32(RETURN_PC)
    # The return PC itself is a safe spin if capture misses by an instruction.
    work[RETURN_PC & 0xFFFF : (RETURN_PC & 0xFFFF) + 2] = bytes.fromhex("60fe")
    return Case(name, target, regs, sr, bytes(work), video_regions)


def make_cases() -> list[Case]:
    return [
        build_case(0x0008C2, "8c2-mask-zero", 0x00000000, 0x8C200),
        build_case(0x0008C2, "8c2-mask-all", 0xFFFFFFFF, 0x8C2FF),
        build_case(0x0008C2, "8c2-mask-sparse", 0x80010021, 0x8C221),
        build_case(0x0026A0, "26a0-mask-zero", 0x0000, 0x26A000),
        build_case(0x0026A0, "26a0-mask-all", 0xFFFF, 0x26A0FF),
        build_case(0x0026A0, "26a0-mask-sparse", 0xA581, 0x26A581),
        build_case(0x00158E, "158e-base-zero", 0, 0x158E00),
        build_case(0x00158E, "158e-base-1000", 0, 0x158E10, a5=0xF01000),
        build_case(0x0017B4, "17b4-fast-zero", 0x00000000, 0x17B400),
        build_case(0x0017B4, "17b4-fast-negative", 0x80000001, 0x17B480),
        build_case(0x0017B4, "17b4-fast-positive", 0x7F010203, 0x17B47F),
        build_case(
            0x0017B4,
            "17b4-fast-production-stack",
            0x80000002,
            0x17B416,
            a7=0xF016C2,
        ),
        build_case(
            0x0017B4,
            "17b4-fallback-base-1000",
            0x80000000,
            0x17B410,
            a5=0xF01000,
        ),
        build_case(0x0020E8, "20e8-row-0000", 0x0000, 0x20E8000),
        build_case(0x0020E8, "20e8-row-014d", 0x014D, 0x20E814D),
        build_case(0x0020E8, "20e8-row-0150", 0x0150, 0x20E8150),
        build_case(0x0020E8, "20e8-row-016f", 0x016F, 0x20E816F),
        # $0170 is the first coordinate rejected by the original visible-row
        # HLE guard; $0180 is the exact lower clipping threshold in the 68000
        # helper.  The final three coordinates are organic calls captured from
        # the active-gameplay overload at ticks 929-931.
        build_case(0x0020E8, "20e8-row-0170", 0x0170, 0x20E8170),
        build_case(0x0020E8, "20e8-row-017f", 0x017F, 0x20E817F),
        build_case(0x0020E8, "20e8-row-0180", 0x0180, 0x20E8180),
        build_case(0x0020E8, "20e8-row-019a", 0x019A, 0x20E819A),
        build_case(0x0020E8, "20e8-row-019d", 0x019D, 0x20E819D),
        build_case(0x0020E8, "20e8-row-01a0", 0x01A0, 0x20E81A0),
        build_case(0x0020E8, "20e8-row-01ff", 0x01FF, 0x20E81FF),
    ]


def mame_result(session: MameSession, case: Case) -> Result:
    session.pause()
    session.write_block(0xF00000, case.work)
    normalized_regions = []
    for video_addr, shadow_addr, video in case.video_regions:
        session.write_block(video_addr, video)
        # Some arcade video devices normalize or ignore byte lanes on write.
        # Feed Nexen the device's actual pre-call readback.
        normalized_regions.append(
            (video_addr, shadow_addr, session.read_block(video_addr, len(video)))
        )
    case.video_regions = normalized_regions
    tap_lines = [
        'if HLE_HELPER_TAPS then for _,tap in ipairs(HLE_HELPER_TAPS) do tap:remove() end end',
        'HLE_HELPER_TAPS = {}',
        'HLE_HELPER_WRITES = {}',
        'local prog = M.devices[":maincpu"].spaces["program"]',
    ]
    for index, (video_addr, _shadow_addr, video) in enumerate(case.video_regions, 1):
        tap_lines.extend(
            [
                f'HLE_HELPER_TAPS[{index}] = prog:install_write_tap(0x{video_addr:X},',
                f'    0x{video_addr + len(video) - 1:X}, "hle_helper_write_{index}",',
                '    function(off, data, mask)',
                '      HLE_HELPER_WRITES[#HLE_HELPER_WRITES+1] = string.format("%06X,%08X,%08X", off, data, mask)',
                '      return data',
                '    end)',
            ]
        )
    tap_lines.append('return "armed"')
    session.exec_lua("\n".join(tap_lines))
    for name in REG_NAMES[:-1]:
        session.set_reg(name, case.regs[name])
    session.set_reg("SP", case.regs["A7"])
    session.set_reg("USP", case.regs["A7"])
    session.set_reg("SR", case.sr)
    session.set_reg("PC", case.target)
    cap = session.cmd(
        "capture_at_pc",
        pc=RETURN_PC,
        addr=0xF00000,
        len=0x10000,
        nth=1,
        exp_sp=(case.regs["A7"] + 4) & 0xFFFFFF,
        maxFrames=30,
        timeout=30,
    )
    if not cap.get("registers"):
        raise RuntimeError(f"MAME did not return from {case.name}: {cap!r}")
    encoded_writes = session.exec_lua(
        'local out = table.concat(HLE_HELPER_WRITES or {}, ";") '
        'if HLE_HELPER_TAPS then for _,tap in ipairs(HLE_HELPER_TAPS) do tap:remove() end; HLE_HELPER_TAPS=nil end '
        'return out'
    )
    writes = []
    if encoded_writes:
        for item in encoded_writes.split(";"):
            addr, data, mask = (int(field, 16) for field in item.split(","))
            writes.append((addr, data, mask))
    expected_regions = [bytearray(video) for _, _, video in case.video_regions]
    for addr, data, mask in writes:
        for region_index, (video_addr, _shadow_addr, video) in enumerate(case.video_regions):
            rel = addr - video_addr
            if mask & 0xFF00 and 0 <= rel < len(video):
                expected_regions[region_index][rel] = (data >> 8) & 0xFF
            if mask & 0x00FF and 0 <= rel + 1 < len(video):
                expected_regions[region_index][rel + 1] = data & 0xFF
    regs = cap["registers"]
    out_regs = {name: regs[name] & 0xFFFFFFFF for name in REG_NAMES[:-1]}
    out_regs["A7"] = regs["SP"] & 0xFFFFFFFF
    return Result(
        out_regs,
        regs["SR"] & 0xFFFF,
        bytes.fromhex(cap["hex"]),
        [bytes(region) for region in expected_regions],
        writes,
    )


def _write_u16(m: McpSession, addr: int, value: int, space: str = DP_SPACE) -> None:
    m.write_u16(addr, value & 0xFFFF, space)


def _set_sa1_pc(m: McpSession, address: int) -> None:
    state = dict(m.get_cpu_state("Sa1"))
    state["pc"] = address & 0xFFFF
    state["k"] = (address >> 16) & 0xFF
    state["d"] = 0
    state["dbr"] = 0
    # Function isolation only: keep an IRQ from swapping the shared emulated
    # register file during the native span.
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

    # Native reg file is little-endian DP cells.  Start A7 four bytes above the
    # desired function-entry SP because the synthetic JSR itself pushes RETURN.
    reg_blob = b"".join(le32(case.regs[f"D{i}"]) for i in range(8))
    reg_blob += b"".join(le32(case.regs[f"A{i}"]) for i in range(7))
    m.write_memory(DP_SPACE, 0x00, reg_blob.hex())
    synthetic_a7 = (case.regs["A7"] + 4) & 0xFFFFFFFF
    m.write_memory(DP_SPACE, 0x3C, le32(synthetic_a7).hex())

    # Restore the complete work/video inputs.  Enter the actual native body
    # directly: a synthetic jsr.l is not valid evidence for helpers that are
    # reached only through the separate BSR/PC-relative dispatch chain.
    for off in range(0, 0x10000, 0x4000):
        m.write_memory(SNES_SPACE, 0x400000 + off, case.work[off : off + 0x4000].hex())
    for _video_addr, shadow_addr, video in case.video_regions:
        m.write_memory(SNES_SPACE, shadow_addr, video.hex())

    # These entries re-simulate the skipped 68K call push.  Seed the eventual
    # stack slot too so the harness remains deterministic even if its saved
    # SA-1 write-protection register differs from production.  The $00FF
    # sentinel makes ors_pre return to the stable native ispin address.
    sentinel = 0x00FF0000 | NATIVE_RETURN
    m.write_memory(
        SNES_SPACE,
        0x400000 | (case.regs["A7"] & 0xFFFF),
        be32(sentinel).hex(),
    )

    m.write_memory(DP_SPACE, 0x40, le32(sentinel).hex())
    flags = case.sr & CCR_MASK
    _write_u16(m, 0x6E, flags & 1)
    _write_u16(m, 0x72, (flags >> 1) & 1)
    _write_u16(m, 0x60, (flags >> 2) & 1)
    _write_u16(m, 0x70, (flags >> 3) & 1)
    _write_u16(m, 0xA2, (flags >> 4) & 1)
    _write_u16(m, 0x7C, 7)
    _write_u16(m, 0xA4, case.regs["A7"] & 0xFFFF)
    _write_u16(m, 0xA6, (case.regs["A7"] >> 16) & 0xFFFF)
    _write_u16(m, 0xA8, 1)
    _write_u16(m, 0xAA, 0)
    _write_u16(m, 0x4A, 0)
    _write_u16(m, 0x4C, 0)
    _write_u16(m, 0xAC, 0x7000)
    _write_u16(m, 0x0718, 0xFFF8)
    _write_u16(m, 0x071A, 1)
    _write_u16(m, 0x0712, 0)
    _write_u16(m, 0x0714, 0)
    _write_u16(m, 0x0702, 0)
    _write_u16(m, 0x0704, 1)
    # The production $158E path now synchronously asks the live 5A22 supervisor
    # to capture into private WRAM.  This synthetic native-only state has no
    # runnable supervisor, so exercise the retained unpaced semantic path here;
    # paced capture/cache equivalence is a separate whole-system gate.
    _write_u16(m, 0x0734, 0)

    return_hook = m.add_exec_hook(NATIVE_RETURN, cpu_type="Sa1")
    m.drain_notifications(timeout=0.05)
    native_entry = NATIVE_ENTRIES[case.target]
    _set_sa1_pc(m, native_entry)
    start_cycles = int(m.get_cpu_state("Sa1")["cycleCount"])
    hit = m.run_until(max_frames=120, hook_handle=return_hook)
    if (hit or {}).get("reason") != "hookFired":
        raise RuntimeError(
            f"Nexen native ${native_entry:06X} did not return for {case.name}: {hit!r}"
        )
    m.pause()
    m.remove_hook(return_hook)
    end_cycles = int(m.get_cpu_state("Sa1")["cycleCount"])

    raw_regs = bytes(m.read_memory(DP_SPACE, 0x00, 0x40))
    out_regs = {}
    for i, name in enumerate(REG_NAMES):
        off = i * 4
        out_regs[name] = int.from_bytes(raw_regs[off : off + 4], "little")
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
        bytes(m.read_memory(SNES_SPACE, 0x400000, 0x10000)),
        [
            bytes(m.read_memory(SNES_SPACE, shadow_addr, len(video)))
            for _video_addr, shadow_addr, video in case.video_regions
        ],
        [],
        end_cycles - start_cycles,
    )


def compare(case: Case, arcade: Result, snes: Result) -> dict:
    reg_mismatches = {
        name: {"mame": arcade.regs[name], "nexen": snes.regs[name]}
        for name in REG_NAMES
        if arcade.regs[name] != snes.regs[name]
    }
    ccr_mismatch = (arcade.sr & CCR_MASK) != (snes.sr & CCR_MASK)

    excluded = set(range(SCRATCH_PC & 0xFFFF, (SCRATCH_PC & 0xFFFF) + 6))
    entry_sp = case.regs["A7"] & 0xFFFF
    excluded.update(range(entry_sp, entry_sp + 4))
    # The arcade maps the live low 16 KiB window; upper $F0 offsets are open bus.
    # The SNES backing allocation is larger, but those bytes are not part of the
    # original helper's observable address-space contract.
    work_mismatches = [
        i
        for i, (a, b) in enumerate(zip(arcade.work[:0x4000], snes.work[:0x4000]))
        if i not in excluded and a != b
    ]
    video_mismatches = []
    for region_index, ((video_addr, shadow_addr, _video), arcade_region, snes_region) in enumerate(
        zip(case.video_regions, arcade.video_regions, snes.video_regions)
    ):
        for offset, (a, b) in enumerate(zip(arcade_region, snes_region)):
            if a != b:
                video_mismatches.append((region_index, offset, video_addr, shadow_addr, a, b))
    return {
        "case": case.name,
        "target": f"{case.target:06X}",
        "native_entry": f"{NATIVE_ENTRIES[case.target]:06X}",
        "nexen_cycles": snes.cycles,
        "result": "green"
        if not reg_mismatches and not ccr_mismatch and not work_mismatches and not video_mismatches
        else "red",
        "reg_mismatches": reg_mismatches,
        "mame_ccr": arcade.sr & CCR_MASK,
        "nexen_ccr": snes.sr & CCR_MASK,
        "work_mismatch_count": len(work_mismatches),
        "work_mismatch_first": [
            {
                "address": f"F0{i:04X}",
                "mame": arcade.work[i],
                "nexen": snes.work[i],
            }
            for i in work_mismatches[:16]
        ],
        "video_mismatch_count": len(video_mismatches),
        "mame_video_write_count": len(arcade.video_writes),
        "video_mismatch_first": [
            {
                "address": f"{video_addr + offset:06X}/{shadow_addr + offset:06X}",
                "mame": mame_value,
                "nexen": nexen_value,
            }
            for _region_index, offset, video_addr, shadow_addr, mame_value, nexen_value
            in video_mismatches[:16]
        ],
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--rom", type=Path, default=DEFAULT_ROM)
    ap.add_argument("--nexen", type=Path, default=DEFAULT_NEXEN)
    ap.add_argument("--nat", type=Path, default=DEFAULT_NAT)
    ap.add_argument("--port", type=int, default=7515)
    ap.add_argument("--output", type=Path)
    args = ap.parse_args()
    for path in (args.rom, args.nexen, args.nat):
        if not path.exists():
            ap.error(f"missing required input: {path}")

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
            print(json.dumps({"event": "mame_case", "case": case.name, "result": "captured"}), flush=True)
    finally:
        mame.stop()

    stderr_log = (
        args.output.with_suffix(".nexen.stderr.log")
        if args.output
        else ROOT / "build/render-helper-diff.nexen.stderr.log"
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
        for case in cases:
            console = nexen_result(nexen, args.nat, case)
            event = {"event": "case", **compare(case, arcade_results[case.name], console)}
            events.append(event)
            print(json.dumps(event, sort_keys=True), flush=True)

    green = sum(event.get("result") == "green" for event in events if event.get("event") == "case")
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
