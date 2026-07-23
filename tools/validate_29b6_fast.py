#!/usr/bin/env python3
"""MAME/Nexen differential for the guarded bank-$9D $0029B6 wrapper.

The shared $2742 harness supplies the table-call setup, exact MAME video taps,
full D/A + CCR + mapped-work-RAM comparison, and Nexen sentinel return.  These
cases exercise both $29B6 attribute branches, both final X values, signed rows,
packed-ROM bank variation, and the generic work-RAM-source fallback.

This is function-local semantic and cycle evidence, not an fps measurement.
"""

from __future__ import annotations

import random
from pathlib import Path

import validate_2742_hle as impl


ENTRY_PC = 0x0029B6
ENTRY_NATIVE = 0x9DFC00
VIDEO_BYTES = 0x38


def put16(data: bytearray, offset: int, value: int) -> None:
    data[offset : offset + 2] = (value & 0xFFFF).to_bytes(2, "big")


def put32(data: bytearray, offset: int, value: int) -> None:
    data[offset : offset + 4] = impl.base.be32(value)


def build_case(
    name: str,
    seed: int,
    *,
    row: int,
    tile_base: int,
    source: int,
) -> impl.base.Case:
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
        source_rng = random.Random(seed ^ 0xF029B6)
        work[source_offset : source_offset + 56] = bytes(
            source_rng.randrange(256) for _ in range(56)
        )
    regs = {reg: rng.randrange(1 << 32) for reg in impl.base.REG_NAMES}
    regs["A5"] = 0x00F00000
    regs["A7"] = impl.ENTRY_SP
    sr = 0x2700 | rng.randrange(0x20)

    stack = impl.ENTRY_SP & 0xFFFF
    put32(work, stack, impl.RETURN_PC)
    put16(work, stack + 4, row)
    put16(work, stack + 6, tile_base)
    put16(work, stack + 8, rng.randrange(0x10000))
    put16(work, stack + 10, rng.randrange(0x10000))
    put32(work, stack + 12, source)
    put16(work, stack + 16, rng.randrange(0x10000))
    work[impl.RETURN_PC & 0xFFFF : (impl.RETURN_PC & 0xFFFF) + 2] = bytes.fromhex(
        "60fe"
    )

    return impl.base.Case(
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


def make_cases() -> list[impl.base.Case]:
    # The selected packed-ROM sources have audited final words covering:
    # base/X=0 ($0000), base/X=1 ($0466), attribute/X=0 ($3E2D), and
    # attribute/X=1 ($FFFF).  $0304BE is the organic C0BC source family.
    return [
        build_case(
            "organic-source", 0x29B600, row=0x0000, tile_base=0x9000,
            source=0x0304BE,
        ),
        # Exact first-call descriptors for all five $C0BC selector tables.
        # These turn the whole-root failures into independently reproducible
        # callback cases instead of relying on hand-selected source words.
        build_case(
            "c0bc-selector-0", 0x29B610, row=0x0000, tile_base=0x9800,
            source=0x046874,
        ),
        build_case(
            "c0bc-selector-1", 0x29B611, row=0x0000, tile_base=0x9800,
            source=0x047D74,
        ),
        build_case(
            "c0bc-selector-2", 0x29B612, row=0x0000, tile_base=0x9800,
            source=0x0497B4,
        ),
        build_case(
            "c0bc-selector-3", 0x29B613, row=0x0000, tile_base=0x9800,
            source=0x04B734,
        ),
        build_case(
            "c0bc-selector-4", 0x29B614, row=0x0000, tile_base=0x9800,
            source=0x04D6B4,
        ),
        build_case(
            "base-zero-x0", 0x29B601, row=0x0040, tile_base=0x0000,
            source=0x00002A,
        ),
        build_case(
            "base-negative-x1", 0x29B602, row=0x01C0, tile_base=0xFFFF,
            source=0x000050,
        ),
        build_case(
            "attribute-x0", 0x29B603, row=0xFFC0, tile_base=0x1234,
            source=0x0003DC,
        ),
        build_case(
            "attribute-x1", 0x29B604, row=0xF800, tile_base=0x8000,
            source=0x000000,
        ),
        build_case(
            "fallback-work-source", 0x29B6F0, row=0x0080,
            tile_base=0x3456, source=0xF01000,
        ),
    ]


def symbol_address(name: str) -> int:
    for raw in Path("src/escbank7.sym").read_text(encoding="utf-8-sig").splitlines():
        fields = raw.split()
        if len(fields) >= 2 and fields[1] == name:
            return 0x9D0000 | int(fields[0].split(":", 1)[1], 16)
    raise RuntimeError(f"missing src/escbank7.sym symbol {name}")


def main() -> int:
    impl.ENTRY_PC = ENTRY_PC
    impl.ENTRY_NATIVE = ENTRY_NATIVE
    impl.TRACE_POINTS = {
        "hle": ENTRY_NATIVE,
        "fast": symbol_address("h29b6_fast"),
        "reject": symbol_address("h29b6_reject"),
    }
    impl.EVIDENCE_SCOPE = (
        "function-local $29B6 MAME/Nexen differential; not fps"
    )
    impl.LOG_STEM = "29b6-fast-differential"
    impl.make_cases = make_cases
    impl.base.NATIVE_ENTRIES[ENTRY_PC] = ENTRY_NATIVE
    return impl.main()


if __name__ == "__main__":
    raise SystemExit(main())
