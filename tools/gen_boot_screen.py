#!/usr/bin/env python3
"""Generate the original, ROM-safe Mode 7 boot-indicator assets.

The asset contains no arcade ROM material.  It is a small SA-1 diamond, an
8x8 status font/OAM image, palettes, and a 64-step rotation matrix.  The ROM
packer imports :func:`build_asset` directly; the command-line form is useful
for byte auditing.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path


ASSET_SIZE = 0x8000
MAP_OFFSET = 0x0000
MAP_SIZE = 0x4000
MODE7_TILES_OFFSET = 0x4000
MODE7_TILES_SIZE = 0x2800
OBJ_TILES_OFFSET = 0x6800
OBJ_TILES_SIZE = 0x1000
OAM_OFFSET = 0x7800
OAM_SIZE = 0x0220
PALETTE_OFFSET = 0x7C00
PALETTE_SIZE = 0x0200
MATRIX_OFFSET = 0x7E00
MATRIX_SIZE = 0x0200

EMBLEM_WIDTH = 96
EMBLEM_HEIGHT = 96
EMBLEM_MAP_X = 10
EMBLEM_MAP_Y = 8

STATUS_LINES = (
    ("SUPERMAN ROM LOADED", 32),
    ("SA-1 68000 CORE ACTIVE", 48),
    ("ARCADE BOOT IN PROGRESS", 192),
)


# Five pixels wide, seven high.  Only project-authored boot text uses this
# compact font; game graphics still come from the user's private arcade input.
GLYPHS: dict[str, tuple[int, ...]] = {
    "-": (0x00, 0x00, 0x00, 0x1F, 0x00, 0x00, 0x00),
    "0": (0x0E, 0x11, 0x13, 0x15, 0x19, 0x11, 0x0E),
    "1": (0x04, 0x0C, 0x04, 0x04, 0x04, 0x04, 0x0E),
    "6": (0x06, 0x08, 0x10, 0x1E, 0x11, 0x11, 0x0E),
    "8": (0x0E, 0x11, 0x11, 0x0E, 0x11, 0x11, 0x0E),
    "A": (0x0E, 0x11, 0x11, 0x1F, 0x11, 0x11, 0x11),
    "B": (0x1E, 0x11, 0x11, 0x1E, 0x11, 0x11, 0x1E),
    "C": (0x0F, 0x10, 0x10, 0x10, 0x10, 0x10, 0x0F),
    "D": (0x1E, 0x11, 0x11, 0x11, 0x11, 0x11, 0x1E),
    "E": (0x1F, 0x10, 0x10, 0x1E, 0x10, 0x10, 0x1F),
    "G": (0x0F, 0x10, 0x10, 0x13, 0x11, 0x11, 0x0F),
    "I": (0x0E, 0x04, 0x04, 0x04, 0x04, 0x04, 0x0E),
    "L": (0x10, 0x10, 0x10, 0x10, 0x10, 0x10, 0x1F),
    "M": (0x11, 0x1B, 0x15, 0x15, 0x11, 0x11, 0x11),
    "N": (0x11, 0x19, 0x15, 0x13, 0x11, 0x11, 0x11),
    "O": (0x0E, 0x11, 0x11, 0x11, 0x11, 0x11, 0x0E),
    "P": (0x1E, 0x11, 0x11, 0x1E, 0x10, 0x10, 0x10),
    "R": (0x1E, 0x11, 0x11, 0x1E, 0x14, 0x12, 0x11),
    "S": (0x0F, 0x10, 0x10, 0x0E, 0x01, 0x01, 0x1E),
    "T": (0x1F, 0x04, 0x04, 0x04, 0x04, 0x04, 0x04),
    "U": (0x11, 0x11, 0x11, 0x11, 0x11, 0x11, 0x0E),
    "V": (0x11, 0x11, 0x11, 0x11, 0x11, 0x0A, 0x04),
}


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def snes_color(red: int, green: int, blue: int) -> bytes:
    value = ((blue >> 3) << 10) | ((green >> 3) << 5) | (red >> 3)
    return value.to_bytes(2, "little")


def point_in_polygon(x: float, y: float, points: tuple[tuple[int, int], ...]) -> bool:
    inside = False
    previous = points[-1]
    for current in points:
        x1, y1 = previous
        x2, y2 = current
        if (y1 > y) != (y2 > y):
            crossing = (x2 - x1) * (y - y1) / (y2 - y1) + x1
            if x < crossing:
                inside = not inside
        previous = current
    return inside


def draw_scaled_glyph(
    pixels: list[list[int]],
    char: str,
    x0: int,
    y0: int,
    scale: int,
    color: int,
) -> None:
    rows = GLYPHS[char]
    for row, bits in enumerate(rows):
        for col in range(5):
            if not bits & (1 << (4 - col)):
                continue
            for yy in range(scale):
                y = y0 + row * scale + yy
                if not 0 <= y < len(pixels):
                    continue
                for xx in range(scale):
                    x = x0 + col * scale + xx
                    if 0 <= x < len(pixels[0]):
                        pixels[y][x] = color


def build_emblem() -> list[list[int]]:
    pixels = [[0 for _ in range(EMBLEM_WIDTH)] for _ in range(EMBLEM_HEIGHT)]
    outer = ((48, 2), (91, 20), (81, 70), (48, 94), (15, 70), (5, 20))
    shadow = tuple((x + 3, y + 2) for x, y in outer)
    inner = ((48, 8), (84, 24), (75, 65), (48, 86), (21, 65), (12, 24))
    core = ((48, 15), (76, 28), (68, 60), (48, 77), (28, 60), (20, 28))

    for y in range(EMBLEM_HEIGHT):
        for x in range(EMBLEM_WIDTH):
            if point_in_polygon(x + 0.5, y + 0.5, shadow):
                pixels[y][x] = 1
            if point_in_polygon(x + 0.5, y + 0.5, outer):
                pixels[y][x] = 3
            if point_in_polygon(x + 0.5, y + 0.5, inner):
                pixels[y][x] = 2
            if point_in_polygon(x + 0.5, y + 0.5, core):
                pixels[y][x] = 5 if y >= 49 else 6

    label = "SA-1"
    scale = 3
    advance = 6 * scale
    width = len(label) * advance - scale
    x0 = (EMBLEM_WIDTH - width) // 2
    y0 = 36
    for index, char in enumerate(label):
        x = x0 + index * advance
        draw_scaled_glyph(pixels, char, x + 2, y0 + 2, scale, 1)
        draw_scaled_glyph(pixels, char, x, y0, scale, 4)

    # Small highlight points give the rotating surface a deliberately
    # cartridge-era, "hardware is alive" sparkle.
    for x, y in ((24, 26), (72, 26), (32, 69), (64, 69)):
        for yy in range(2):
            for xx in range(2):
                pixels[y + yy][x + xx] = 3
    return pixels


def mode7_sections() -> tuple[bytes, bytes]:
    tilemap = bytearray(MAP_SIZE)
    tile_data = bytearray(MODE7_TILES_SIZE)
    pixels = build_emblem()
    tile_index = 1  # tile zero is the transparent/backdrop field
    for tile_y in range(EMBLEM_HEIGHT // 8):
        for tile_x in range(EMBLEM_WIDTH // 8):
            tile = bytes(
                pixels[tile_y * 8 + row][tile_x * 8 + col]
                for row in range(8)
                for col in range(8)
            )
            start = tile_index * 64
            tile_data[start : start + 64] = tile
            map_x = EMBLEM_MAP_X + tile_x
            map_y = EMBLEM_MAP_Y + tile_y
            tilemap[map_y * 128 + map_x] = tile_index
            tile_index += 1
    assert tile_index == 145
    return bytes(tilemap), bytes(tile_data)


def font_tile(char: str) -> bytes:
    pixels = [[0 for _ in range(8)] for _ in range(8)]
    rows = GLYPHS[char]
    # One-pixel navy shadow, then the white 5x7 face.
    for row, bits in enumerate(rows):
        for col in range(5):
            if bits & (1 << (4 - col)):
                if col + 2 < 8 and row + 1 < 8:
                    pixels[row + 1][col + 2] = 2
                pixels[row][col + 1] = 1

    planar = bytearray(32)
    for row in range(8):
        p0 = p1 = p2 = p3 = 0
        for col, value in enumerate(pixels[row]):
            bit = 1 << (7 - col)
            if value & 1:
                p0 |= bit
            if value & 2:
                p1 |= bit
            if value & 4:
                p2 |= bit
            if value & 8:
                p3 |= bit
        planar[row * 2] = p0
        planar[row * 2 + 1] = p1
        planar[16 + row * 2] = p2
        planar[16 + row * 2 + 1] = p3
    return bytes(planar)


def obj_sections() -> tuple[bytes, bytes, dict[str, int], int]:
    characters = sorted({char for text, _y in STATUS_LINES for char in text if char != " "})
    missing = sorted(set(characters) - GLYPHS.keys())
    if missing:
        raise AssertionError(f"missing boot font glyphs: {missing}")
    tile_for_char = {char: index for index, char in enumerate(characters)}

    tiles = bytearray(OBJ_TILES_SIZE)
    for char, index in tile_for_char.items():
        tile = font_tile(char)
        tiles[index * 32 : index * 32 + 32] = tile

    low_oam = bytearray(512)
    for sprite in range(128):
        low_oam[sprite * 4 + 1] = 0xF0
        low_oam[sprite * 4 + 3] = 0x30
    sprite = 0
    for text, y in STATUS_LINES:
        x0 = (256 - len(text) * 8) // 2
        for index, char in enumerate(text):
            if char == " ":
                continue
            if sprite >= 128:
                raise AssertionError("boot status text exceeds SNES OAM")
            offset = sprite * 4
            low_oam[offset] = x0 + index * 8
            low_oam[offset + 1] = y
            low_oam[offset + 2] = tile_for_char[char]
            low_oam[offset + 3] = 0x30  # OBJ palette 0, priority 3, no flips
            sprite += 1
    high_oam = bytes(32)  # all X<256 and all sprites use the 8x8 small size
    return bytes(tiles), bytes(low_oam) + high_oam, tile_for_char, sprite


def palette_section() -> bytes:
    colors = bytearray(PALETTE_SIZE)
    bg_colors = {
        0: (2, 4, 12),
        1: (7, 18, 55),
        2: (214, 30, 48),
        3: (250, 190, 42),
        4: (248, 248, 255),
        5: (118, 10, 30),
        6: (24, 68, 170),
    }
    obj_colors = {
        128: (0, 0, 0),
        129: (248, 248, 255),
        130: (5, 16, 48),
        131: (250, 190, 42),
    }
    for index, rgb in {**bg_colors, **obj_colors}.items():
        colors[index * 2 : index * 2 + 2] = snes_color(*rgb)
    return bytes(colors)


def matrix_section() -> bytes:
    table = bytearray()
    scale = 0x00C0  # 0.75 in signed 8.8; enlarges the 96px emblem on screen
    for step in range(64):
        angle = 2.0 * math.pi * step / 64.0
        cosine = round(math.cos(angle) * scale)
        sine = round(math.sin(angle) * scale)
        for value in (cosine, -sine, sine, cosine):
            table += (value & 0xFFFF).to_bytes(2, "little")
    assert len(table) == MATRIX_SIZE
    return bytes(table)


def build_asset() -> tuple[bytes, dict[str, object]]:
    tilemap, mode7_tiles = mode7_sections()
    obj_tiles, oam, tile_for_char, visible_sprites = obj_sections()
    palette = palette_section()
    matrices = matrix_section()

    asset = bytearray(ASSET_SIZE)
    asset[MAP_OFFSET : MAP_OFFSET + MAP_SIZE] = tilemap
    asset[
        MODE7_TILES_OFFSET : MODE7_TILES_OFFSET + MODE7_TILES_SIZE
    ] = mode7_tiles
    asset[OBJ_TILES_OFFSET : OBJ_TILES_OFFSET + OBJ_TILES_SIZE] = obj_tiles
    asset[OAM_OFFSET : OAM_OFFSET + OAM_SIZE] = oam
    asset[PALETTE_OFFSET : PALETTE_OFFSET + PALETTE_SIZE] = palette
    asset[MATRIX_OFFSET : MATRIX_OFFSET + MATRIX_SIZE] = matrices

    report: dict[str, object] = {
        "asset_size": len(asset),
        "sha256": sha256(asset),
        "mode7_tiles": 145,
        "visible_obj_sprites": visible_sprites,
        "font_tiles": len(tile_for_char),
        "font_map": tile_for_char,
        "status_lines": [text for text, _y in STATUS_LINES],
        "sections": {
            "tilemap_low": [MAP_OFFSET, MAP_SIZE],
            "mode7_tile_high": [MODE7_TILES_OFFSET, MODE7_TILES_SIZE],
            "obj_tiles": [OBJ_TILES_OFFSET, OBJ_TILES_SIZE],
            "oam": [OAM_OFFSET, OAM_SIZE],
            "palette": [PALETTE_OFFSET, PALETTE_SIZE],
            "matrices": [MATRIX_OFFSET, MATRIX_SIZE],
        },
    }
    return bytes(asset), report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--report", type=Path)
    args = parser.parse_args()

    asset, report = build_asset()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_bytes(asset)
    if args.report:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    print(json.dumps(report, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
