#!/usr/bin/env python3
"""
SUPERSEDED FOR SPRITES — see docs/toolchain/GRAPHICS_PALETTE_EVIDENCE.md.

Tile-aware palette quantization is the WRONG model for Taito X sprites: the
arcade picks a sprite's 16-color bank from its OAM color field at RUNTIME (not
from the tile), the palette RAM is rewritten per scene (dynamic), and at most 7
banks are used simultaneously — so the SNES's 8 OBJ palettes hold every used
bank with ZERO color reduction. Use the bank model in
tools/build_snes_sprite_scene.py, not this quantizer, for sprites. Kept only as
a possible starting point for genuinely-static palettes (if any exist).

Planar tile → SNES palette optimizer bridge.

Reads Taito X System planar tile data and the arcade palette (from MAME),
converts to RGB pixels, then uses tiledpalettequant to produce optimized
SNES palettes (8 palettes × 16 colors) and tile→palette assignments.

Usage:
    python tools/optimize_palettes.py --tile-file data/tiles/sprites_16x16.bin \
        --palette-file tools/mame-trace/arcade_palette.bin \
        --output-dir data/palettes/sprites/

    # Or for tile ROMs:
    python tools/optimize_palettes.py --tile-file data/tiles/tiles_0.bin \
        --palette-file tools/mame-trace/arcade_palette.bin \
        --output-dir data/palettes/tiles/ --mode bg
"""

import argparse
import os
import sys
import struct
import numpy as np
from pathlib import Path

# Add SMI tools to path for tiledpalettequant import
SMI_TOOLS = Path("/home/chad/SNES-SuperMonkeyIsland/tools")
sys.path.insert(0, str(SMI_TOOLS))
from tiledpalettequant import (
    build_palettes_tileaware,
    rgb_to_bgr555,
    bgr555_to_rgb,
    DEFAULT_NUM_PALETTES,
    DEFAULT_COLORS_PER_PALETTE,
    DEFAULT_TILE_SIZE,
)


def read_arcade_palette(path, max_entries=2048):
    """Read the arcade palette dumped from MAME.
    
    Format: xRGB_555 (16-bit LE), 2048 entries at $B00000.
    Each word: xRRRRRGGGGGBBBBB
    """
    with open(path, "rb") as f:
        data = f.read()
    
    num_entries = min(len(data) // 2, max_entries)
    palette = np.zeros((num_entries, 3), dtype=np.uint8)  # R, G, B (0-31)
    
    for i in range(num_entries):
        # The MAME byte dump stores read_u8(even)=HIGH byte, read_u8(odd)=LOW
        # byte (68K is big-endian), so the logical 16-bit word is big-endian.
        # (Ground-truth-validated against MAME's screen — see
        # docs/toolchain/GRAPHICS_PALETTE_EVIDENCE.md.
        #  An earlier little-endian reading here produced scrambled colors that a
        #  self-referential proof failed to catch.)
        w = (data[i * 2] << 8) | data[i * 2 + 1]
        # Taito X palette is xRGB_555: bits14-10=R, bits9-5=G, bits4-0=B.
        r = (w >> 10) & 0x1F
        g = (w >> 5) & 0x1F
        b = w & 0x1F
        palette[i] = [r, g, b]
    
    return palette


def read_snes_bitplane_tiles(path, tile_size=8):
    """Read SNES bitplane-format tiles and extract pixel color indices.
    
    SNES 4bpp format: 32 bytes per 8×8 tile
    Bytes 0-15: bitplane pairs (bp0, bp1) for rows 0-7
    Bytes 16-31: bitplane pairs (bp2, bp3) for rows 0-7
    
    Color index = bp0 | (bp1 << 1) | (bp2 << 2) | (bp3 << 3)
    """
    with open(path, "rb") as f:
        data = f.read()
    
    tile_bytes = tile_size * 4  # 32 bytes for 4bpp 8×8
    num_tiles = len(data) // tile_bytes
    
    tiles = np.zeros((num_tiles, tile_size, tile_size), dtype=np.uint8)
    
    for t in range(num_tiles):
        offset = t * tile_bytes
        for row in range(tile_size):
            bp0 = data[offset + row * 2]
            bp1 = data[offset + row * 2 + 1]
            bp2 = data[offset + 16 + row * 2]
            bp3 = data[offset + 16 + row * 2 + 1]
            for px in range(tile_size):
                idx = (
                    ((bp0 >> (7 - px)) & 1)
                    | (((bp1 >> (7 - px)) & 1) << 1)
                    | (((bp2 >> (7 - px)) & 1) << 2)
                    | (((bp3 >> (7 - px)) & 1) << 3)
                )
                tiles[t, row, px] = idx
    
    return tiles


def read_planar_tiles(path, tile_size=8):
    """Read Taito X planar-format tiles and extract pixel color indices.
    
    Taito X planar 4bpp: 32 bytes per 8×8 tile
    Bytes 0-7: bitplane 0 (LSB)
    Bytes 8-15: bitplane 1
    Bytes 16-23: bitplane 2
    Bytes 24-31: bitplane 3 (MSB)
    """
    with open(path, "rb") as f:
        data = f.read()
    
    tile_bytes = tile_size * 4
    num_tiles = len(data) // tile_bytes
    
    tiles = np.zeros((num_tiles, tile_size, tile_size), dtype=np.uint8)
    
    for t in range(num_tiles):
        offset = t * tile_bytes
        for row in range(tile_size):
            bp0 = data[offset + row]
            bp1 = data[offset + 8 + row]
            bp2 = data[offset + 16 + row]
            bp3 = data[offset + 24 + row]
            for px in range(tile_size):
                idx = (
                    ((bp0 >> (7 - px)) & 1)
                    | (((bp1 >> (7 - px)) & 1) << 1)
                    | (((bp2 >> (7 - px)) & 1) << 2)
                    | (((bp3 >> (7 - px)) & 1) << 3)
                )
                tiles[t, row, px] = idx
    
    return tiles


def indices_to_rgb(tiles, palette, base_index=0):
    """Convert tile pixel indices to RGB values using the arcade palette.
    
    Args:
        tiles: (n_tiles, 8, 8) uint8 color indices
        palette: (n_colors, 3) uint8 RGB values (0-31 per channel)
        base_index: offset added to indices (for palette banking)
    
    Returns:
        rgb_tiles: (n_tiles, 8, 8) uint16 BGR555 values
    """
    n_tiles = tiles.shape[0]
    h = tiles.shape[1]
    w = tiles.shape[2]
    
    # Map indices through palette to get RGB
    # tiles contains indices 0-15, palette maps index → (R,G,B)
    flat_indices = tiles.reshape(-1) + base_index
    flat_rgb = palette[flat_indices]  # (n_tiles*64, 3) in 0-31 range
    
    # Convert to BGR555
    r = flat_rgb[:, 0].astype(np.uint16)
    g = flat_rgb[:, 1].astype(np.uint16)
    b = flat_rgb[:, 2].astype(np.uint16)
    bgr555 = (r | (g << 5) | (b << 10)).reshape(n_tiles, h, w)
    
    return bgr555


def optimize_palettes(rgb_tiles, num_palettes=8, colors_per_palette=16,
                      base_index=0, trans_color=None):
    """Run tiledpalettequant on RGB tile data.
    
    Args:
        rgb_tiles: (n_tiles, 8, 8) uint16 BGR555 values
        num_palettes: number of SNES OBJ palettes (default 8)
        colors_per_palette: colors per palette including transparent (default 16)
        base_index: palette index offset (for reporting)
        trans_color: BGR555 transparent color (default: 0x0000)
    
    Returns:
        palettes: list of lists of BGR555 colors
        indexed_tiles: (n_tiles, 8, 8) uint8 palette-relative indices
        tile_pal_ids: (n_tiles,) uint8 palette assignments
    """
    if trans_color is None:
        trans_color = 0x0000
    
    palettes, indexed_tiles, tile_pal_ids = build_palettes_tileaware(
        rgb_tiles,
        num_palettes=num_palettes,
        colors_per_palette=colors_per_palette,
        trans_color=trans_color,
    )
    
    return palettes, indexed_tiles, tile_pal_ids


def write_cgram(palettes, output_path):
    """Write palettes as SNES CGRAM binary (BGR555, little-endian).
    
    256 bytes total: 8 palettes × 16 colors × 2 bytes.
    """
    data = bytearray()
    for pal in palettes:
        for color in pal:
            data += struct.pack("<H", color & 0x7FFF)
    
    # Pad to 256 bytes if needed
    while len(data) < 256:
        data += b"\x00\x00"
    
    Path(output_path).write_bytes(bytes(data[:256]))
    return len(data[:256])


def write_snes_bitplane_tiles(indexed_tiles, tile_pal_ids, num_palettes, output_path):
    """Write remapped tile indices as SNES bitplane format.
    
    Each 8×8 tile = 32 bytes in SNES 4bpp bitplane format.
    The indexed_tiles contain palette-relative indices (0-15).
    """
    n_tiles = indexed_tiles.shape[0]
    data = bytearray()
    
    for t in range(n_tiles):
        tile = indexed_tiles[t]  # (8, 8) with values 0-15
        # SNES 4bpp bitplane encoding:
        # For each row, pack 8 pixels into bitplanes
        bp0_bytes = bytearray(8)
        bp1_bytes = bytearray(8)
        bp2_bytes = bytearray(8)
        bp3_bytes = bytearray(8)
        
        for row in range(8):
            for px in range(8):
                idx = int(tile[row, px])
                bp0_bytes[row] |= ((idx >> 0) & 1) << (7 - px)
                bp1_bytes[row] |= ((idx >> 1) & 1) << (7 - px)
                bp2_bytes[row] |= ((idx >> 2) & 1) << (7 - px)
                bp3_bytes[row] |= ((idx >> 3) & 1) << (7 - px)
        
        # Interleave: bp0+bp1 pairs for rows 0-7, then bp2+bp3 pairs
        for row in range(8):
            data += struct.pack("BB", bp0_bytes[row], bp1_bytes[row])
        for row in range(8):
            data += struct.pack("BB", bp2_bytes[row], bp3_bytes[row])
    
    Path(output_path).write_bytes(bytes(data))
    return len(data)


def write_tile_assignments(tile_pal_ids, output_path):
    """Write tile→palette assignments as binary."""
    data = bytes(int(p) for p in tile_pal_ids)
    Path(output_path).write_bytes(data)
    return len(data)


def write_assignments_text(tile_pal_ids, output_path):
    """Write tile→palette assignments as human-readable text."""
    with open(output_path, "w") as f:
        for i, pid in enumerate(tile_pal_ids):
            f.write(f"{i}\t{int(pid)}\n")


def write_palettes_text(palettes, output_path):
    """Write palettes as human-readable text."""
    with open(output_path, "w") as f:
        for pi, pal in enumerate(palettes):
            f.write(f"Palette {pi}:\n")
            for ci, color in enumerate(pal):
                r = color & 0x1F
                g = (color >> 5) & 0x1F
                b = (color >> 10) & 0x1F
                f.write(f"  {ci}: ${color:04X}  RGB({r:2d},{g:2d},{b:2d})\n")


def main():
    parser = argparse.ArgumentParser(
        description="Optimize SNES palettes from arcade tile data + palette")
    parser.add_argument("--tile-file", required=True,
                        help="Input tile binary (SNES bitplane format)")
    parser.add_argument("--palette-file", required=True,
                        help="Arcade palette binary (from MAME dump)")
    parser.add_argument("--output-dir", required=True,
                        help="Output directory for palette files")
    parser.add_argument("--num-palettes", type=int, default=DEFAULT_NUM_PALETTES,
                        help=f"Number of SNES palettes (default: {DEFAULT_NUM_PALETTES})")
    parser.add_argument("--colors-per-palette", type=int, default=DEFAULT_COLORS_PER_PALETTE,
                        help=f"Colors per palette (default: {DEFAULT_COLORS_PER_PALETTE})")
    parser.add_argument("--base-index", type=int, default=0,
                        help="Base palette index offset (default: 0)")
    parser.add_argument("--tile-size", type=int, default=DEFAULT_TILE_SIZE,
                        help=f"Tile size in pixels (default: {DEFAULT_TILE_SIZE})")
    parser.add_argument("--format", choices=["snes", "planar"], default="snes",
                        help="Input tile format: snes (bitplane) or planar (Taito X)")
    parser.add_argument("--verify", action="store_true",
                        help="Generate verification PNG")
    args = parser.parse_args()
    
    # Read inputs
    print(f"Reading tiles: {args.tile_file}")
    if args.format == "snes":
        tiles = read_snes_bitplane_tiles(args.tile_file, args.tile_size)
    else:
        tiles = read_planar_tiles(args.tile_file, args.tile_size)
    
    num_tiles = tiles.shape[0]
    print(f"  {num_tiles} tiles ({args.tile_size}×{args.tile_size})")
    
    # Count unique indices
    unique_indices = np.unique(tiles)
    print(f"  Unique color indices: {unique_indices.tolist()}")
    
    print(f"Reading palette: {args.palette_file}")
    palette = read_arcade_palette(args.palette_file)
    print(f"  {len(palette)} entries")
    
    # Convert indices to RGB
    print("Converting indices to RGB...")
    rgb_tiles = indices_to_rgb(tiles, palette, args.base_index)
    
    # Check for any indices outside palette range
    max_idx = tiles.max() + args.base_index
    if max_idx >= len(palette):
        print(f"  WARNING: Max index {max_idx} exceeds palette size {len(palette)}")
    
    # Run optimizer
    print(f"Optimizing {args.num_palettes} palettes × {args.colors_per_palette} colors...")
    palettes, indexed_tiles, tile_pal_ids = optimize_palettes(
        rgb_tiles,
        num_palettes=args.num_palettes,
        colors_per_palette=args.colors_per_palette,
        base_index=args.base_index,
    )

    # Report results
    pals_used = sum(1 for p in palettes if any(c != 0 for c in p[1:]))
    print(f"  Palettes used: {pals_used}/{args.num_palettes}")

    from collections import Counter
    counts = Counter(int(p) for p in tile_pal_ids)
    for pid in sorted(counts):
        print(f"    Palette {pid}: {counts[pid]} tiles")

    # Write outputs
    out_dir = Path(args.output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    stem = Path(args.tile_file).stem

    cgram_path = out_dir / f"{stem}.cgram"
    write_cgram(palettes, cgram_path)
    print(f"Wrote CGRAM: {cgram_path}")

    assign_path = out_dir / f"{stem}.palassign"
    write_tile_assignments(tile_pal_ids, assign_path)
    print(f"Wrote assignments: {assign_path}")

    # Write remapped tile data (SNES bitplane format)
    remapped_path = out_dir / f"{stem}.tiles"
    write_snes_bitplane_tiles(indexed_tiles, tile_pal_ids, args.num_palettes,
                              remapped_path)
    print(f"Wrote remapped tiles: {remapped_path}")

    # Text versions for debugging
    write_palettes_text(palettes, out_dir / f"{stem}_palettes.txt")
    write_assignments_text(tile_pal_ids, out_dir / f"{stem}_assignments.txt")
    print(f"Wrote text files")

    # Verification PNG
    if args.verify:
        try:
            from PIL import Image

            # Determine grid size
            grid_w = min(16, num_tiles)
            grid_h = (num_tiles + grid_w - 1) // grid_w

            img = Image.new("RGB", (grid_w * 8, grid_h * 8), (0, 0, 0))
            px = img.load()

            pal_rgb = []
            for pal in palettes:
                pal_rgb.append([bgr555_to_rgb(c) for c in pal])

            for t in range(num_tiles):
                row = t // grid_w
                col = t % grid_w
                pal_id = int(tile_pal_ids[t])
                colors = pal_rgb[pal_id]

                for ty in range(8):
                    for tx in range(8):
                        ci = int(indexed_tiles[t, ty, tx])
                        rgb = colors[ci] if ci < len(colors) else (255, 0, 255)
                        px[col * 8 + tx, row * 8 + ty] = rgb

            verify_path = out_dir / f"{stem}_verify.png"
            img.save(verify_path)
            print(f"Wrote verification: {verify_path}")
        except ImportError:
            print("  (PIL not available, skipping verification PNG)")

    print("Done!")


if __name__ == "__main__":
    main()
