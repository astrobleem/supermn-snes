#!/usr/bin/env python3
"""Regression gate for the BG empty-cell/physical-slot-zero contract.

The staged tilemap uses word zero for an empty 16x16 cell.  SNES tile number
zero therefore must remain blank, while all nonempty artwork is assigned to
physical cache slots 1..191.  Check the source paths and the exact production
ROM payload so a future allocator or prepared-map change cannot reintroduce the
repeating-background failure.
"""

from __future__ import annotations

import hashlib
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
VIDEO = (ROOT / "src/video.pasm").read_text(encoding="utf-8")
ESC8 = (ROOT / "src/escbank8.pasm").read_text(encoding="utf-8")
BUILDER = (ROOT / "tools/build_interp_rom.py").read_text(encoding="utf-8")
ROM_PATH = ROOT / "build/interp.sfc"

PREPARED_OFFSET = 0x2F9000
PREPARED_LENGTH = 0x107A
PREPARED_SHA256 = (
    "015bfe5186c7c5b6e72b168981f83c7ba8932a4c95ffa4f58f3025c0b3cdfd1d"
)


def require(text: str, snippet: str, label: str) -> None:
    assert snippet in text, f"missing {label} blank-slot invariant"


def cell_words(tilemap: bytes, cell: int) -> list[int]:
    column, row = divmod(cell, 32)
    horizontal = column * 8 + (row & 1) * 4
    if horizontal & 0x40:
        horizontal = (horizontal & 0x3F) + 0x0800
    destination = (row & 0x1E) * 64 + horizontal
    return [
        int.from_bytes(tilemap[offset:offset + 2], "little")
        for offset in (
            destination,
            destination + 2,
            destination + 0x40,
            destination + 0x42,
        )
    ]


def main() -> int:
    require(
        VIDEO,
        "stz $E4              ; arcade graphics code zero is a verified blank record\n"
        "    stz $DA              ; overwrite Mode 7 boot pixels in reserved BG slot zero\n"
        "    jsr bg_tile_dma",
        "dynamic blank upload",
    )
    require(
        VIDEO,
        "sta $7E89C2\n"
        "    inc a               ; slot zero is the permanent empty-cell/blank-tile sentinel\n"
        "    sta $DC             ; first dynamic allocation is physical slot one\n"
        "    lda #$B7C5",
        "dynamic allocator reset",
    )
    require(
        VIDEO,
        "tya\n"
        "    lsr a\n"
        "    inc a               ; prepared artwork starts at physical slot one\n"
        "    sta $7EA400,x",
        "prepared hash slot",
    )
    require(
        VIDEO,
        "tya\n"
        "    clc\n"
        "    adc #$0002          ; reverse word index for physical slot (Y/2)+1",
        "prepared reverse slot",
    )
    require(
        ESC8,
        "cmp #$017E          ; 191 artwork slots * two-byte code; physical zero is blank",
        "prepared producer capacity",
    )
    require(
        ESC8,
        "lda $AC00,x\n"
        "    inc a               ; prepared physical slot zero is the empty-cell sentinel\n"
        "    asl a\n"
        "    asl a",
        "prepared producer tile base",
    )
    require(
        BUILDER,
        "slots = {code: index + 1 for index, code in enumerate(unique_codes)}",
        "immutable C0BC slot assignment",
    )
    require(
        BUILDER,
        "assert SNES_GFX[:128] == bytes(128)",
        "authenticated blank graphics record",
    )
    require(
        VIDEO,
        "bg_upload:\n"
        "    sep #$20\n"
        "    lda #$01\n"
        "bg_upload_commit:       ; every completed staging map has exactly one PPU authority",
        "single staging/display map authority",
    )
    assert "bg_upload_conserve_sparse" not in VIDEO, (
        "the rejected sparse-upload gate split staging and displayed map authority"
    )

    assert ROM_PATH.is_file(), "build/interp.sfc is required for the binary gate"
    rom = ROM_PATH.read_bytes()
    assert len(rom) == 0x400000, "production ROM is not 4 MiB"
    assert rom[0x90000:0x90080] == bytes(0x80), (
        "native graphics record zero is not the authenticated blank tile"
    )

    prepared = rom[PREPARED_OFFSET:PREPARED_OFFSET + PREPARED_LENGTH]
    observed_sha = hashlib.sha256(prepared).hexdigest()
    assert observed_sha == PREPARED_SHA256, (
        f"immutable C0BC prepared payload changed: {observed_sha}"
    )
    tilemap = prepared[:0x1000]
    nonempty = 0
    empty = 0
    observed_slots: set[int] = set()
    for cell in range(512):
        words = cell_words(tilemap, cell)
        tile_numbers = [word & 0x03FF for word in words]
        if any(words):
            nonempty += 1
            base = tile_numbers[0]
            assert base >= 4 and base % 4 == 0, (
                f"cell {cell} uses reserved/unaligned base tile {base}"
            )
            assert tile_numbers == list(range(base, base + 4)), (
                f"cell {cell} quadrants are not one complete physical slot: "
                f"{tile_numbers}"
            )
            slot = base // 4
            assert 1 <= slot <= 45, f"cell {cell} uses invalid slot {slot}"
            observed_slots.add(slot)
        else:
            empty += 1
            assert words == [0, 0, 0, 0]

    assert (nonempty, empty) == (392, 120), (
        f"unexpected C0BC cell shape: nonempty={nonempty}, empty={empty}"
    )
    assert observed_slots == set(range(1, 46)), (
        f"prepared slots are not exactly 1..45: {sorted(observed_slots)}"
    )
    print(
        "BG blank-slot invariant green: slot0 blank; "
        "C0BC nonempty cells use physical slots 1..45 (392 artwork, 120 empty)"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
