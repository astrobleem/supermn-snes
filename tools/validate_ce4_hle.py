#!/usr/bin/env python3
"""Function-local MAME/Nexen differential for the $000CE4 sprite renderer.

MAME executes the original 68000 routine through RTS.  Nexen enters the
bank-$94 table-convention escape with the same already-pushed return contract
used by production native callers.  Every D/A register, CCR X/N/Z/V/C bit,
and byte of mapped low-16-KiB work RAM (apart from the synthetic return) is
compared.  This is bounded semantic/cycle evidence, not an FPS measurement.
"""

from __future__ import annotations

import argparse
import json
import random
import time
from pathlib import Path

import validate_d96_hle as base

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_ROM = ROOT / "build" / "interp.sfc"
WORK_FRAME = 0xF02B00
ENTRY_SP = 0xF03D00
ENTRY_PC = 0x000CE4
ENTRY_NATIVE = 0x948F7C
RETURN_PC = 0xF03E80
NATIVE_RETURN = 0x00D15A
FAST_2X2_CASES = {
    "two-by-two-full-visible-hot",
    "two-by-two-x-clip-hot",
    "two-by-two-y-clip-hot",
    "two-by-two-x-positive-hidden-edge",
    "two-by-two-x-positive-visible-edge",
    "two-by-two-x-negative-visible-edge",
    "two-by-two-x-negative-hidden-edge",
    "two-by-two-y-negative-hidden-edge",
    "two-by-two-y-negative-visible-edge",
    "two-by-two-y-positive-visible-edge",
    "two-by-two-y-positive-hidden-edge",
    "rom-shape-4072e-two-by-two-hot",
}
FAST_STAGE3_PANEL_CASES = {
    "rom-shape-42aea-stage3-panel-hot",
    "rom-shape-42b18-stage3-panel-hot",
}
FAST_STAGE3_PANEL_GUARD_MISS_CASES = {
    "rom-shape-42b46-stage3-panel-source-miss",
    "rom-shape-42aea-stage3-panel-cursor-miss",
    "rom-shape-42aea-stage3-panel-attr-miss",
    "rom-shape-42aea-stage3-panel-x-miss",
    "rom-shape-42aea-stage3-panel-y-miss",
    "rom-shape-42aea-stage3-panel-capacity-miss",
}

# Reuse the already-proven transport/register comparison machinery while
# selecting CE4's original and native entry points.
base.ENTRY_PC = ENTRY_PC
base.ENTRY_NATIVE = ENTRY_NATIVE
base.RETURN_PC = RETURN_PC
base.NATIVE_RETURN = NATIVE_RETURN


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
    x: int = 0x0060,
    y: int = 0x0040,
    frame_pointer: int = WORK_FRAME,
    entry_sp: int = ENTRY_SP,
    a5: int = 0x00F00000,
    x_flag: int = 0,
) -> base.Case:
    expected_tiles = (outer_count + 1) * (inner_count + 1)
    if frame_pointer == WORK_FRAME and len(tiles) != expected_tiles:
        raise ValueError(f"{name}: expected {expected_tiles} tile words")

    rng = random.Random(seed)
    work = bytearray(rng.randrange(256) for _ in range(0x10000))
    regs = {reg: rng.randrange(1 << 32) for reg in base.REG_NAMES}
    regs["A5"] = a5
    regs["A7"] = entry_sp
    sr = 0x2700 | rng.randrange(0x10) | ((x_flag & 1) << 4)

    if frame_pointer == WORK_FRAME:
        frame = base.be16(outer_count) + base.be16(inner_count)
        frame += b"".join(base.be16(tile) for tile in tiles)
        offset = frame_pointer & 0xFFFF
        work[offset : offset + len(frame)] = frame

    stack = entry_sp & 0xFFFF
    # CE4's C(a6)/E(a6) arguments are X/Y, the opposite ordering of D96.
    args = (
        base.be16(cursor)
        + base.be16(attr)
        + base.be16(x)
        + base.be16(y)
        + base.be32(frame_pointer)
        + base.be16(capacity_minus_one)
    )
    work[stack : stack + 4] = base.be32(RETURN_PC)
    work[stack + 4 : stack + 4 + len(args)] = args
    work[RETURN_PC & 0xFFFF : (RETURN_PC & 0xFFFF) + 2] = bytes.fromhex("60fe")
    return base.Case(name, regs, sr, bytes(work))


def s16(value: int) -> int:
    value &= 0xFFFF
    return value - 0x10000 if value & 0x8000 else value


def fast_2x2_after_link_instructions(case: base.Case) -> int:
    """Return $000CE4's exact post-LINK count for a nonzero 2x2/capacity-4 call."""

    stack = case.regs["A7"] & 0xFFFF
    x = int.from_bytes(case.work[stack + 8 : stack + 10], "big")
    y = int.from_bytes(case.work[stack + 10 : stack + 12], "big")
    d1_row0 = (0x00EA - x) & 0xFFFF
    d1_row1 = (d1_row0 - 0x0010) & 0xFFFF
    y_column0 = y
    y_column1 = (y + 0x0010) & 0xFFFF

    def x_path(value: int) -> int:
        signed = s16(value)
        if signed >= 250:
            return 3
        if signed <= -6:
            return 5
        return 6

    def live_y_path(value: int) -> int:
        signed = s16(value)
        if signed <= -16:
            return 14
        if signed >= 384:
            return 16
        return 15

    # 17 prologue, three row-setup instructions per row, two instructions
    # after each nonterminal tile, two more after the first row, and four
    # epilogue instructions.  The final tile exhausts D7 and branches directly
    # to the epilogue.
    return (
        17
        + x_path(d1_row0)
        + 3
        + live_y_path(y_column0)
        + 2
        + live_y_path(y_column1)
        + 4
        + x_path(d1_row1)
        + 3
        + live_y_path(y_column0)
        + 2
        + live_y_path(y_column1)
        + 4
    )


def stage3_panel_after_link_instructions(case: base.Case) -> int:
    """Return CE4's post-LINK count for the guarded 3x7 Stage-3 panel."""

    stack = case.regs["A7"] & 0xFFFF
    cursor = int.from_bytes(case.work[stack + 4 : stack + 6], "big")
    attr = int.from_bytes(case.work[stack + 6 : stack + 8], "big")
    x = int.from_bytes(case.work[stack + 8 : stack + 10], "big")
    y = int.from_bytes(case.work[stack + 10 : stack + 12], "big")
    source = int.from_bytes(case.work[stack + 12 : stack + 16], "big")
    capacity = int.from_bytes(case.work[stack + 16 : stack + 18], "big")
    expected = (0x01DE, 0x0800, 0x0060, 0x0010, 0x0012)
    if (cursor, attr, x, y, capacity) != expected:
        raise ValueError(f"{case.name}: not the guarded Stage-3 panel arguments")
    if source not in (0x042AEA, 0x042B18):
        raise ValueError(f"{case.name}: not a guarded Stage-3 panel source")

    # Prologue through SUB.W: 17.  All three row-X and seven column-Y
    # coordinates are visible.  Fourteen live cells each execute the
    # 15-instruction live body plus the two-instruction inner tail; seven
    # zero cells execute only the read/BEQ and inner tail.  Each row executes
    # its two-instruction outer tail.  Five unused capacity slots then take
    # the fill loop before the four-instruction epilogue.
    return 17 + 3 * (6 + 3) + 14 * 17 + 7 * 4 + 3 * 2 + 3 + 5 * 2 + 4


def make_cases() -> list[base.Case]:
    return [
        build_case(
            "single-row-zero-skip-and-fill-x0",
            0xCE400,
            outer_count=0,
            inner_count=2,
            tiles=[0x0001, 0x0000, 0x0345],
            capacity_minus_one=5,
            x_flag=0,
        ),
        build_case(
            "two-columns-offscreen-negative-cursor-x1",
            0xCE401,
            outer_count=1,
            inner_count=2,
            tiles=[0x0010, 0x0011, 0x0012, 0x0020, 0x0000, 0x0022],
            capacity_minus_one=8,
            cursor=0xFFF0,
            attr=0x6400,
            x=0xFFF8,
            y=0x0190,
            x_flag=1,
        ),
        build_case(
            "capacity-exhausts-mid-row",
            0xCE402,
            outer_count=0,
            inner_count=4,
            tiles=[0x0100, 0x0101, 0x0102, 0x0103, 0x0104],
            capacity_minus_one=1,
            x_flag=0,
        ),
        build_case(
            "two-by-two-full-visible-hot",
            0xCE416,
            outer_count=1,
            inner_count=1,
            tiles=[0x0123, 0x4567, 0x89AB, 0xD234],
            capacity_minus_one=3,
            x=0x0080,
            y=0x0040,
            x_flag=0,
        ),
        build_case(
            "two-by-two-zero-tile-guard-miss",
            0xCE417,
            outer_count=1,
            inner_count=1,
            tiles=[0x0123, 0x0000, 0x89AB, 0xD234],
            capacity_minus_one=3,
            x=0x0080,
            y=0x0040,
            x_flag=1,
        ),
        build_case(
            "two-by-two-x-clip-hot",
            0xCE418,
            outer_count=1,
            inner_count=1,
            tiles=[0x0123, 0x4567, 0x89AB, 0xD234],
            capacity_minus_one=3,
            x=0x00DB,
            y=0x0040,
            x_flag=0,
        ),
        build_case(
            "two-by-two-y-clip-hot",
            0xCE419,
            outer_count=1,
            inner_count=1,
            tiles=[0x0123, 0x4567, 0x89AB, 0xD234],
            capacity_minus_one=3,
            x=0x0080,
            y=0x0170,
            x_flag=1,
        ),
        # Signed X clipping boundaries.  d1=$EA-X is visible only for
        # -5..249; the second row independently repeats the test at d1-$10.
        build_case(
            "two-by-two-x-positive-hidden-edge",
            0xCE41B,
            outer_count=1,
            inner_count=1,
            tiles=[0x1111, 0x2222, 0x3333, 0x4444],
            capacity_minus_one=3,
            x=0xFFF0,  # row-0 d1=250
            y=0x0040,
            x_flag=0,
        ),
        build_case(
            "two-by-two-x-positive-visible-edge",
            0xCE41C,
            outer_count=1,
            inner_count=1,
            tiles=[0x1111, 0x2222, 0x3333, 0x4444],
            capacity_minus_one=3,
            x=0xFFF1,  # row-0 d1=249
            y=0x0040,
            x_flag=1,
        ),
        build_case(
            "two-by-two-x-negative-visible-edge",
            0xCE41D,
            outer_count=1,
            inner_count=1,
            tiles=[0x1111, 0x2222, 0x3333, 0x4444],
            capacity_minus_one=3,
            x=0x00EF,  # row-0 d1=-5
            y=0x0040,
            x_flag=0,
        ),
        build_case(
            "two-by-two-x-negative-hidden-edge",
            0xCE41E,
            outer_count=1,
            inner_count=1,
            tiles=[0x1111, 0x2222, 0x3333, 0x4444],
            capacity_minus_one=3,
            x=0x00F0,  # row-0 d1=-6
            y=0x0040,
            x_flag=1,
        ),
        # Signed Y clipping boundaries.  A column is visible only for
        # -15..383; column one independently adds $10 with word wrap.
        build_case(
            "two-by-two-y-negative-hidden-edge",
            0xCE41F,
            outer_count=1,
            inner_count=1,
            tiles=[0x1111, 0x2222, 0x3333, 0x4444],
            capacity_minus_one=3,
            x=0x0080,
            y=0xFFF0,  # -16
            x_flag=0,
        ),
        build_case(
            "two-by-two-y-negative-visible-edge",
            0xCE420,
            outer_count=1,
            inner_count=1,
            tiles=[0x1111, 0x2222, 0x3333, 0x4444],
            capacity_minus_one=3,
            x=0x0080,
            y=0xFFF1,  # -15
            x_flag=1,
        ),
        build_case(
            "two-by-two-y-positive-visible-edge",
            0xCE421,
            outer_count=1,
            inner_count=1,
            tiles=[0x1111, 0x2222, 0x3333, 0x4444],
            capacity_minus_one=3,
            x=0x0080,
            y=0x017F,  # 383
            x_flag=0,
        ),
        build_case(
            "two-by-two-y-positive-hidden-edge",
            0xCE422,
            outer_count=1,
            inner_count=1,
            tiles=[0x1111, 0x2222, 0x3333, 0x4444],
            capacity_minus_one=3,
            x=0x0080,
            y=0x0180,  # 384
            x_flag=1,
        ),
        build_case(
            "rom-shape-4072e-two-by-two-hot",
            0xCE41A,
            outer_count=1,
            inner_count=1,
            tiles=[],
            capacity_minus_one=3,
            cursor=0x0234,
            attr=0x6000,
            x=0x0080,
            y=0x004E,
            frame_pointer=0x04072E,
            x_flag=0,
        ),
        build_case(
            "rom-shape-42aea-stage3-panel-hot",
            0xCE423,
            outer_count=2,
            inner_count=6,
            tiles=[],
            capacity_minus_one=0x0012,
            cursor=0x01DE,
            attr=0x0800,
            x=0x0060,
            y=0x0010,
            frame_pointer=0x042AEA,
            x_flag=0,
        ),
        build_case(
            "rom-shape-42b18-stage3-panel-hot",
            0xCE424,
            outer_count=2,
            inner_count=6,
            tiles=[],
            capacity_minus_one=0x0012,
            cursor=0x01DE,
            attr=0x0800,
            x=0x0060,
            y=0x0010,
            frame_pointer=0x042B18,
            x_flag=1,
        ),
        # Guard-neighbor cases deliberately preserve a valid 3x7 ROM stream
        # while changing exactly one fast-path admission field.  They must
        # execute CE4's generic renderer and remain exact through the
        # production native-off/native-on dispatcher.
        build_case(
            "rom-shape-42b46-stage3-panel-source-miss",
            0xCE425,
            outer_count=2,
            inner_count=6,
            tiles=[],
            capacity_minus_one=0x0012,
            cursor=0x01DE,
            attr=0x0800,
            x=0x0060,
            y=0x0010,
            frame_pointer=0x042B46,
            x_flag=0,
        ),
        build_case(
            "rom-shape-42aea-stage3-panel-cursor-miss",
            0xCE426,
            outer_count=2,
            inner_count=6,
            tiles=[],
            capacity_minus_one=0x0012,
            cursor=0x01E0,
            attr=0x0800,
            x=0x0060,
            y=0x0010,
            frame_pointer=0x042AEA,
            x_flag=1,
        ),
        build_case(
            "rom-shape-42aea-stage3-panel-attr-miss",
            0xCE427,
            outer_count=2,
            inner_count=6,
            tiles=[],
            capacity_minus_one=0x0012,
            cursor=0x01DE,
            attr=0x0801,
            x=0x0060,
            y=0x0010,
            frame_pointer=0x042AEA,
            x_flag=0,
        ),
        build_case(
            "rom-shape-42aea-stage3-panel-x-miss",
            0xCE428,
            outer_count=2,
            inner_count=6,
            tiles=[],
            capacity_minus_one=0x0012,
            cursor=0x01DE,
            attr=0x0800,
            x=0x0061,
            y=0x0010,
            frame_pointer=0x042AEA,
            x_flag=1,
        ),
        build_case(
            "rom-shape-42aea-stage3-panel-y-miss",
            0xCE429,
            outer_count=2,
            inner_count=6,
            tiles=[],
            capacity_minus_one=0x0012,
            cursor=0x01DE,
            attr=0x0800,
            x=0x0060,
            y=0x0011,
            frame_pointer=0x042AEA,
            x_flag=0,
        ),
        build_case(
            "rom-shape-42aea-stage3-panel-capacity-miss",
            0xCE42A,
            outer_count=2,
            inner_count=6,
            tiles=[],
            capacity_minus_one=0x0013,
            cursor=0x01DE,
            attr=0x0800,
            x=0x0060,
            y=0x0010,
            frame_pointer=0x042AEA,
            x_flag=1,
        ),
        build_case(
            "negative-capacity-cold-fallback",
            0xCE403,
            outer_count=0,
            inner_count=1,
            tiles=[0x0007, 0x0008],
            capacity_minus_one=0xFFFE,
            cursor=0xFFF0,
            x_flag=1,
        ),
        # Arcade ROM $00084A is header 0,3 followed by words 0,4,0,5.
        build_case(
            "rom-backed-frame-stream",
            0xCE404,
            outer_count=0,
            inner_count=3,
            tiles=[],
            capacity_minus_one=4,
            frame_pointer=0x0000084A,
            cursor=0x0020,
            x=0x00EF,
            y=0x0004,
            x_flag=0,
        ),
        build_case(
            "rom-shape-3762e-hot",
            0xCE407,
            outer_count=3,
            inner_count=3,
            tiles=[],
            capacity_minus_one=0x000F,
            cursor=0x034A,
            attr=0x2000,
            x=0x00A0,
            y=0x0047,
            frame_pointer=0x03762E,
            x_flag=1,
        ),
        build_case(
            "rom-shape-341c2-hot",
            0xCE408,
            outer_count=4,
            inner_count=5,
            tiles=[],
            capacity_minus_one=0x000F,
            cursor=0x0270,
            attr=0x4000,
            x=0x0028,
            y=0x00AD,
            frame_pointer=0x0341C2,
            x_flag=0,
        ),
        build_case(
            "rom-shape-428d6-hot",
            0xCE409,
            outer_count=5,
            inner_count=5,
            tiles=[],
            capacity_minus_one=0x0012,
            cursor=0x01B6,
            attr=0x0800,
            x=0x0010,
            y=0x0130,
            frame_pointer=0x0428D6,
            x_flag=1,
        ),
        build_case(
            "rom-shape-4288a-hot",
            0xCE40A,
            outer_count=5,
            inner_count=5,
            tiles=[],
            capacity_minus_one=0x0012,
            cursor=0x01B6,
            attr=0x0800,
            x=0x0010,
            y=0x0130,
            frame_pointer=0x04288A,
            x_flag=0,
        ),
        build_case(
            "rom-shape-337f0-hot",
            0xCE40B,
            outer_count=4,
            inner_count=4,
            tiles=[],
            capacity_minus_one=0x0011,
            cursor=0x0228,
            attr=0x3000,
            x=0x002C,
            y=0x0086,
            frame_pointer=0x0337F0,
            x_flag=1,
        ),
        build_case(
            "rom-shape-33c0a-hot",
            0xCE40C,
            outer_count=4,
            inner_count=4,
            tiles=[],
            capacity_minus_one=0x0011,
            cursor=0x0228,
            attr=0x3000,
            x=0x002B,
            y=0x0087,
            frame_pointer=0x033C0A,
            x_flag=0,
        ),
        build_case(
            "rom-shape-3762e-negative-y-hot",
            0xCE40E,
            outer_count=3,
            inner_count=3,
            tiles=[],
            capacity_minus_one=0x000F,
            cursor=0x036A,
            attr=0x2000,
            x=0x00A0,
            y=0xFFCA,
            frame_pointer=0x03762E,
            x_flag=0,
        ),
        build_case(
            "rom-shape-33f6e-exhaust-hot",
            0xCE40F,
            outer_count=1,
            inner_count=2,
            tiles=[],
            capacity_minus_one=0x0005,
            cursor=0x017C,
            attr=0x0800,
            x=0x0064,
            y=0x0138,
            frame_pointer=0x033F6E,
            x_flag=1,
        ),
        build_case(
            "rom-shape-ca8e-wrap-exhaust-hot",
            0xCE410,
            outer_count=0,
            inner_count=3,
            tiles=[],
            capacity_minus_one=0x0003,
            cursor=0x003C,
            attr=0x0000,
            x=0x00E0,
            y=0x0090,
            frame_pointer=0x00CA8E,
            x_flag=0,
        ),
        build_case(
            "rom-shape-42a52-exhaust-hot",
            0xCE411,
            outer_count=5,
            inner_count=5,
            tiles=[],
            capacity_minus_one=0x0012,
            cursor=0x01B6,
            attr=0x0800,
            x=0x0013,
            y=0x0112,
            frame_pointer=0x042A52,
            x_flag=1,
        ),
        build_case(
            "rom-shape-42a9e-exhaust-hot",
            0xCE412,
            outer_count=5,
            inner_count=5,
            tiles=[],
            capacity_minus_one=0x0012,
            cursor=0x01B6,
            attr=0x0800,
            x=0x0013,
            y=0x0106,
            frame_pointer=0x042A9E,
            x_flag=0,
        ),
        # One step outside each specialized geometry must remain on the
        # already-proven generic path without changing function semantics.
        build_case(
            "rom-shape-42a52-x-guard-miss",
            0xCE413,
            outer_count=5,
            inner_count=5,
            tiles=[],
            capacity_minus_one=0x0012,
            cursor=0x01B6,
            attr=0x0800,
            x=0x009B,
            y=0x0112,
            frame_pointer=0x042A52,
            x_flag=1,
        ),
        build_case(
            "rom-shape-42a9e-y-guard-miss",
            0xCE414,
            outer_count=5,
            inner_count=5,
            tiles=[],
            capacity_minus_one=0x0012,
            cursor=0x01B6,
            attr=0x0800,
            x=0x0013,
            y=0x0140,
            frame_pointer=0x042A9E,
            x_flag=0,
        ),
        build_case(
            "rom-shape-3762e-negative-y-guard-miss",
            0xCE415,
            outer_count=3,
            inner_count=3,
            tiles=[],
            capacity_minus_one=0x000F,
            cursor=0x036A,
            attr=0x2000,
            x=0x00A0,
            y=0xFFD1,
            frame_pointer=0x03762E,
            x_flag=1,
        ),
        build_case(
            "rom-shape-428d6-hot-guard-edge",
            0xCE40D,
            outer_count=5,
            inner_count=5,
            tiles=[],
            capacity_minus_one=0x0012,
            cursor=0x0180,
            attr=0x6800,
            x=0x009A,
            y=0x013F,
            frame_pointer=0x0428D6,
            x_flag=0,
        ),
        build_case(
            "low-task-stack",
            0xCE405,
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
            0xCE406,
            outer_count=0,
            inner_count=1,
            tiles=[0x0042, 0x0043],
            capacity_minus_one=3,
            a5=0x00F00010,
            cursor=0x0010,
            x_flag=0,
        ),
    ]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--rom", type=Path, default=DEFAULT_ROM)
    parser.add_argument("--nexen", type=Path, default=base.DEFAULT_NEXEN)
    parser.add_argument("--nat", type=Path, default=base.DEFAULT_NAT)
    parser.add_argument("--port", type=int, default=7543)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    for path in (args.rom, args.nexen, args.nat):
        if not path.is_file():
            parser.error(f"missing required input: {path}")

    cases = make_cases()
    events: list[dict] = []
    provenance = {
        "event": "provenance",
        "scope": (
            "function-local CE4 MAME/Nexen register/CCR/X/work-RAM "
            "differential plus clipping-aware 2x2 and immutable Stage-3 "
            "panel AC-charge checks; not fps"
        ),
        "mame": "/snap/bin/mame 0.287",
        "nexen": str(args.nexen.resolve()),
        "nexen_sha256": base.sha256(args.nexen),
        "rom": str(args.rom.resolve()),
        "rom_sha256": base.sha256(args.rom),
        "nat": str(args.nat.resolve()),
        "nat_sha256": base.sha256(args.nat),
        "entry_native": f"{ENTRY_NATIVE:06X}",
        "cases": len(cases),
        "time": time.time(),
    }
    events.append(provenance)
    print(json.dumps(provenance, sort_keys=True), flush=True)

    arcade_results: dict[str, base.Result] = {}
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
            arcade_results[case.name] = base.mame_result(mame, case)
            print(json.dumps({"event": "mame_case", "case": case.name}), flush=True)
    finally:
        mame.stop()

    with base.McpSession(
        rom=str(args.rom),
        mesen=str(args.nexen),
        cwd=ROOT,
        port=args.port,
        boot_wait=8.0,
        socket_timeout=120.0,
        stderr_log=ROOT / "build" / "playability-20260719" / "ce4-nexen.stderr.log",
    ) as nexen:
        for case in cases:
            console = base.nexen_result(nexen, args.nat, case)
            event = {
                "event": "case",
                **base.compare(case, arcade_results[case.name], console),
            }
            if case.name in FAST_2X2_CASES:
                instruction_count = fast_2x2_after_link_instructions(case)
            elif case.name in FAST_STAGE3_PANEL_CASES:
                instruction_count = stage3_panel_after_link_instructions(case)
            else:
                instruction_count = None
            if instruction_count is not None:
                expected_ac = (0x7000 - instruction_count) & 0xFFFF
                event.update(
                    {
                        "post_link_instruction_count": instruction_count,
                        "expected_ac": expected_ac,
                        "nexen_ac": console.ac,
                        "ac_charge_green": console.ac == expected_ac,
                    }
                )
                if not event["ac_charge_green"]:
                    event["result"] = "red"
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
