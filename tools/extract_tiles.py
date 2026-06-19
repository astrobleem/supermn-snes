#!/usr/bin/env python3
"""
Taito X → SNES tile format converter.

Taito X tile format (planar 4bpp):
  Each 8×8 tile = 32 bytes
  Bitplane layout (standard planar):
    Bytes 0-7:   Bitplane 0 (LSB of color index)
    Bytes 8-15:  Bitplane 1
    Bytes 16-23: Bitplane 2
    Bytes 24-31: Bitplane 3 (MSB of color index)

SNES tile format (packed 4bpp):
  Each 8×8 tile = 32 bytes
  Bitplane layout (interleaved pairs):
    Bytes 0-1:   Bitplane 0+1 for row 0 (2 bytes: bp0, bp1)
    Bytes 2-3:   Bitplane 0+1 for row 1
    ...
    Bytes 14-15: Bitplane 0+1 for row 7
    Bytes 16-17: Bitplane 2+3 for row 0
    ...
    Bytes 30-31: Bitplane 2+3 for row 7

Conversion: For each row, interleave bitplanes 0,1 and 2,3 into packed pairs.
"""

import struct
import os
import sys
import argparse

def convert_tile_planar_to_snes(src_32bytes):
    """Convert one 8×8 tile from Taito X planar to SNES packed 4bpp."""
    if len(src_32bytes) != 32:
        raise ValueError(f"Expected 32 bytes, got {len(src_32bytes)}")
    
    # Extract bitplanes from source
    bp0 = src_32bytes[0:8]    # bitplane 0 (LSB)
    bp1 = src_32bytes[8:16]   # bitplane 1
    bp2 = src_32bytes[16:24]  # bitplane 2
    bp3 = src_32bytes[24:32]  # bitplane 3 (MSB)
    
    out = bytearray(32)
    
    # SNES 4bpp format: interleaved bitplane pairs
    # First 16 bytes: bp0 + bp1 interleaved (2 bytes per row)
    # Last 16 bytes: bp2 + bp3 interleaved (2 bytes per row)
    for row in range(8):
        out[row * 2] = bp0[row]
        out[row * 2 + 1] = bp1[row]
        out[16 + row * 2] = bp2[row]
        out[16 + row * 2 + 1] = bp3[row]
    
    return bytes(out)


def convert_tile_alternative_format(src_32bytes):
    """
    Alternative Taito X format (some games use different bitplane ordering).
    Try: bp0=bytes 0-7, bp1=bytes 8-15, bp2=bytes 16-23, bp3=bytes 24-31
    but with different row ordering.
    """
    # Some Taito games store tiles column-first instead of row-first
    # This is a fallback converter
    bp0 = src_32bytes[0:8]
    bp1 = src_32bytes[8:16]
    bp2 = src_32bytes[16:24]
    bp3 = src_32bytes[24:32]
    
    out = bytearray(32)
    for row in range(8):
        out[row * 2] = bp0[row]
        out[row * 2 + 1] = bp1[row]
        out[16 + row * 2] = bp2[row]
        out[16 + row * 2 + 1] = bp3[row]
    
    return bytes(out)


def extract_tiles(input_path, output_path, tile_count=None, bpp=4):
    """Extract and convert all tiles from a ROM file."""
    
    with open(input_path, "rb") as f:
        data = f.read()
    
    tile_size = 8 * bpp  # 32 bytes for 4bpp, 16 bytes for 2bpp, 64 bytes for 8bpp
    total_tiles = len(data) // tile_size
    
    if tile_count is None:
        tile_count = total_tiles
    else:
        tile_count = min(tile_count, total_tiles)
    
    print(f"Input: {input_path} ({len(data)} bytes)")
    print(f"Tile size: {tile_size} bytes ({bpp}bpp)")
    print(f"Total tiles in ROM: {total_tiles}")
    print(f"Converting: {tile_count} tiles")
    
    output = bytearray()
    empty_tiles = 0
    
    for i in range(tile_count):
        offset = i * tile_size
        tile_data = data[offset:offset + tile_size]
        
        # Check if tile is empty
        if tile_data == b'\x00' * tile_size:
            empty_tiles += 1
        
        if bpp == 4:
            converted = convert_tile_planar_to_snes(tile_data)
        else:
            converted = tile_data  # passthrough for other formats
        
        output.extend(converted)
    
    with open(output_path, "wb") as f:
        f.write(output)
    
    print(f"Output: {output_path} ({len(output)} bytes)")
    print(f"Empty tiles: {empty_tiles}/{tile_count} ({empty_tiles*100//tile_count}%)")
    
    return output


def extract_sprite_data(input_path, output_path, sprite_w=16, sprite_h=16, bpp=4):
    """
    Extract sprite data from Taito X sprite ROM.
    
    Taito X sprites are composed of multiple 8×8 tiles arranged in a grid.
    For a 16×16 sprite: 4 tiles (2×2 grid)
    For a 32×32 sprite: 16 tiles (4×4 grid)
    
    Tile ordering within a sprite: left-to-right, top-to-bottom
    """
    
    tile_size = 8 * bpp
    tiles_per_row = sprite_w // 8
    tiles_per_col = sprite_h // 8
    tiles_per_sprite = tiles_per_row * tiles_per_col
    sprite_size = tiles_per_sprite * tile_size
    
    with open(input_path, "rb") as f:
        data = f.read()
    
    total_sprites = len(data) // sprite_size
    
    print(f"Sprite ROM: {input_path}")
    print(f"Sprite size: {sprite_w}×{sprite_h} ({tiles_per_sprite} tiles, {sprite_size} bytes)")
    print(f"Total sprites: {total_sprites}")
    
    output = bytearray()
    
    for s in range(total_sprites):
        sprite_offset = s * sprite_size
        
        # Convert each tile in the sprite
        for ty in range(tiles_per_col):
            for tx in range(tiles_per_row):
                tile_idx = ty * tiles_per_row + tx
                tile_offset = sprite_offset + tile_idx * tile_size
                tile_data = data[tile_offset:tile_offset + tile_size]
                
                if bpp == 4:
                    converted = convert_tile_planar_to_snes(tile_data)
                else:
                    converted = tile_data
                
                output.extend(converted)
    
    with open(output_path, "wb") as f:
        f.write(output)
    
    print(f"Output: {output_path} ({len(output)} bytes)")
    
    return output


def main():
    parser = argparse.ArgumentParser(description="Taito X → SNES tile converter")
    subparsers = parser.add_subparsers(dest="command")
    
    # Tile extraction
    tile_parser = subparsers.add_parser("tiles", help="Extract tile data")
    tile_parser.add_argument("input", help="Input ROM file")
    tile_parser.add_argument("output", help="Output binary file")
    tile_parser.add_argument("--count", type=int, default=None, help="Number of tiles")
    tile_parser.add_argument("--bpp", type=int, default=4, choices=[2, 4, 8])
    
    # Sprite extraction
    spr_parser = subparsers.add_parser("sprites", help="Extract sprite data")
    spr_parser.add_argument("input", help="Input ROM file")
    spr_parser.add_argument("output", help="Output binary file")
    spr_parser.add_argument("--width", type=int, default=16, help="Sprite width in pixels")
    spr_parser.add_argument("--height", type=int, default=16, help="Sprite height in pixels")
    spr_parser.add_argument("--bpp", type=int, default=4, choices=[2, 4, 8])
    
    # Batch extraction
    batch_parser = subparsers.add_parser("batch", help="Batch extract all Superman ROMs")
    batch_parser.add_argument("--rom-dir", default="/home/chad/superman-arcade")
    batch_parser.add_argument("--out-dir", default="/home/chad/supermn-snes/data/tiles")
    
    args = parser.parse_args()
    
    if args.command == "tiles":
        extract_tiles(args.input, args.output, args.count, args.bpp)
    elif args.command == "sprites":
        extract_sprite_data(args.input, args.output, args.width, args.height, args.bpp)
    elif args.command == "batch":
        batch_extract(args.rom_dir, args.out_dir)
    else:
        parser.print_help()


def batch_extract(rom_dir, out_dir):
    """Batch extract all tile and sprite data from Superman ROMs."""
    os.makedirs(out_dir, exist_ok=True)
    
    # Tile ROMs
    tile_roms = [
        ("b61-15.h1", "tiles_0.bin", "Tile ROM 0"),
        ("b61-16.j1", "tiles_1.bin", "Tile ROM 1"),
        ("b61-13.a3", "tiles_2.bin", "Tile ROM 2"),
    ]
    
    for rom_name, out_name, desc in tile_roms:
        rom_path = os.path.join(rom_dir, rom_name)
        out_path = os.path.join(out_dir, out_name)
        if os.path.exists(rom_path):
            print(f"\n--- {desc} ({rom_name}) ---")
            extract_tiles(rom_path, out_path)
        else:
            print(f"WARNING: {rom_name} not found")
    
    # Sprite ROM
    spr_path = os.path.join(rom_dir, "b61-17.k1")
    spr_out = os.path.join(out_dir, "sprites_16x16.bin")
    if os.path.exists(spr_path):
        print(f"\n--- Sprite ROM (b61-17.k1) ---")
        extract_sprite_data(spr_path, spr_out, 16, 16)
    
    # Also extract as 32×32 sprites
    spr_out_32 = os.path.join(out_dir, "sprites_32x32.bin")
    if os.path.exists(spr_path):
        extract_sprite_data(spr_path, spr_out_32, 32, 32)
    
    print(f"\nBatch extraction complete. Output in: {out_dir}")


if __name__ == "__main__":
    main()
