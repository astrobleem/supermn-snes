#!/usr/bin/env python3
"""
Superman (Taito F2) ROM analyzer
Maps out the ROM structure for SNES retargeting.

Taito F2 hardware:
- Main CPU: Motorola 68000 @ 16MHz
- Sound CPU: Z80 @ 4MHz
- Sound Chip: YM2610 (OPNB + ADPCM)
- Tilemaps: TC0100SCN (2-3 layers)
- Sprites: PC080SN (sprite+bgtile renderer)
- C-Chip: Encrypted Z80 (protection, game-specific logic)
- Other: TC0040IOC (I/O), TC0060DCA (scroll)

Known superman.zip ROM layout (from MAME taito_f2.cpp):
  b61-01.e18  - 68000 main program (512KB)
  b61-14.f1   - 68000 main program hi (512KB) 
  b61-15.h1   - Tile ROM 0 (512KB)
  b61-16.j1   - Tile ROM 1 (512KB)
  b61-17.k1   - Sprite ROM (512KB)
  b61_07.a5   - C-Chip program (128KB)
  b61_08.a8   - Sound program (128KB) 
  b61_09.a10  - YM2610 samples (128KB)
  b61_10.d18  - C-Chip data (64KB)
  b61_13.a3   - Tile ROM 2 (128KB)
"""

import struct
import os
import sys
import json

ROM_DIR = "/home/chad/superman-arcade"
OUT_DIR = "/home/chad/supermn-snes/data"

# Known file sizes and expected layouts
FILES = {
    "b61-01.e18":  {"size": 524288, "desc": "68K main code (lo)",        "type": "cpu_code_lo"},
    "b61-14.f1":   {"size": 524288, "desc": "68K main code (hi)",        "type": "cpu_code_hi"},
    "b61-15.h1":   {"size": 524288, "desc": "Tile ROM 0 (bg/sp gfx)",    "type": "tile_gfx"},
    "b61-16.j1":   {"size": 524288, "desc": "Tile ROM 1 (bg/sp gfx)",    "type": "tile_gfx"},
    "b61-17.k1":   {"size": 524288, "desc": "Sprite ROM",                "type": "sprite_gfx"},
    "b61_07.a5":   {"size": 131072, "desc": "C-Chip (protection MCU)",   "type": "cchip_code"},
    "b61_08.a8":   {"size": 131072, "desc": "Sound (Z80) program",       "type": "sound_code"},
    "b61_09.a10":  {"size": 131072, "desc": "YM2610 sample ROM",         "type": "sound_samples"},
    "b61_10.d18":  {"size":  65536, "desc": "C-Chip data ROM",           "type": "cchip_data"},
    "b61_13.a3":   {"size": 131072, "desc": "Tile ROM 2",                "type": "tile_gfx"},
}

def analyze_roms():
    os.makedirs(OUT_DIR, exist_ok=True)
    
    report = {
        "game": "Superman (Taito F2, 1996)",
        "total_rom_size": 0,
        "hardware": {
            "main_cpu": "Motorola 68000 @ 16MHz",
            "sound_cpu": "Z80 @ 4MHz", 
            "sound_chip": "YM2610 (OPNB + 2x ADPCM-A + 4x ADPCM-B)",
            "tilemap_chip": "TC0100SCN (2-3 layers)",
            "sprite_chip": "PC080SN",
            "protection": "C-Chip (encrypted Z80)",
            "total_vram": "Unknown - needs MAME analysis",
        },
        "roms": {},
        "snes_mapping": {
            "main_cpu": "SA-1 (65C816 @ 10.74MHz) + main 5A22 (3.58MHz)",
            "graphics": "SNES PPU (Mode 7, 4bpp tiles, 128 sprites)",
            "audio": "SPC700 + Terrific Audio Driver",
            "c_chip_emulation": "SA-1 coprocessor or main CPU",
            "tilemap_strategy": "SNES BG layers (Mode 0-2) or software rendering",
            "sprite_strategy": "SNES OAM (128 sprites, 32x32 max) or SA-1 CC Type 2",
        }
    }
    
    for fname, info in sorted(FILES.items()):
        path = os.path.join(ROM_DIR, fname)
        if not os.path.exists(path):
            print(f"WARNING: {fname} not found")
            continue
            
        with open(path, "rb") as f:
            data = f.read()
        
        actual_size = len(data)
        expected_size = info["size"]
        report["total_rom_size"] += actual_size
        
        # Analyze content
        zero_pct = data.count(0) / len(data) * 100
        ff_pct = data.count(0xFF) / len(data) * 100
        
        # Look for readable strings
        strings = []
        current = b""
        for b in data[:16384]:
            if 32 <= b < 127:
                current += bytes([b])
            else:
                if len(current) >= 6:
                    strings.append(current.decode("ascii"))
                current = b""
        
        # Check for 68000 vector table
        sp = struct.unpack(">I", data[0:4])[0]
        pc = struct.unpack(">I", data[4:8])[0]
        has_vector_table = (0x10000 <= sp <= 0x1000000) and (0x4000 <= pc <= 0x1000000)
        
        # Entropy analysis (sample every 256th byte)
        sample = data[::256][:1024]
        unique_bytes = len(set(sample))
        
        rom_info = {
            "size": actual_size,
            "expected_size": expected_size,
            "size_ok": actual_size >= expected_size,
            "zero_bytes_pct": round(zero_pct, 1),
            "ff_bytes_pct": round(ff_pct, 1),
            "entropy_sample_unique": unique_bytes,
            "description": info["desc"],
            "type": info["type"],
            "readable_strings": strings[:10],
        }
        
        if has_vector_table:
            rom_info["m68k_sp"] = f"${sp:08X}"
            rom_info["m68k_pc"] = f"${pc:08X}"
        
        report["roms"][fname] = rom_info
        
        print(f"\n{'='*60}")
        print(f"{fname} ({info['type']})")
        print(f"  {info['desc']}")
        print(f"  Size: {actual_size//1024}KB (expected {expected_size//1024}KB) {'OK' if actual_size >= expected_size else 'SHORT'}")
        print(f"  Zeros: {zero_pct:.1f}%  0xFF: {ff_pct:.1f}%")
        print(f"  Entropy: {unique_bytes}/256 unique bytes (sampled)")
        
        if has_vector_table:
            print(f"  68K SP: ${sp:08X}  PC: ${pc:08X}")
        
        if strings:
            print(f"  Strings: {', '.join(repr(s) for s in strings[:5])}")
        
        # Tile/Sprite data analysis
        if info["type"] in ("tile_gfx", "sprite_gfx"):
            analyze_gfx_rom(fname, data, info["type"])

    # Save report
    report_path = os.path.join(OUT_DIR, "rom_analysis.json")
    with open(report_path, "w") as f:
        json.dump(report, f, indent=2)
    
    print(f"\n{'='*60}")
    print(f"Total ROM size: {report['total_rom_size']//1024}KB ({report['total_rom_size']//(1024*1024)}MB)")
    print(f"Report saved to: {report_path}")
    
    return report


def analyze_gfx_rom(fname, data, gfx_type):
    """Analyze a graphics ROM for tile/sprite data patterns."""
    
    # Taito F2 tile ROMs are typically 4bpp planar format
    # Each 8x8 tile = 32 bytes (4 bitplanes x 8 bytes)
    # Sprite ROMs may be 4bpp or 8bpp
    
    tile_size_4bpp = 32   # 8x8 4bpp = 32 bytes
    tile_size_8bpp = 64   # 8x8 8bpp = 64 bytes
    
    n_tiles_4bpp = len(data) // tile_size_4bpp
    n_tiles_8bpp = len(data) // tile_size_8bpp
    
    print(f"  As 4bpp tiles: {n_tiles_4bpp} tiles ({n_tiles_4bpp*32//1024}KB of tile data)")
    print(f"  As 8bpp tiles: {n_tiles_8bpp} tiles")
    
    # Check for empty tiles
    empty_4bpp = sum(1 for i in range(0, len(data), tile_size_4bpp) 
                     if data[i:i+tile_size_4bpp] == b'\x00' * tile_size_4bpp)
    empty_8bpp = sum(1 for i in range(0, len(data), tile_size_8bpp)
                     if data[i:i+tile_size_8bpp] == b'\x00' * tile_size_8bpp)
    
    print(f"  Empty 4bpp tiles: {empty_4bpp}/{n_tiles_4bpp} ({empty_4bpp*100//n_tiles_4bpp}%)")
    print(f"  Empty 8bpp tiles: {empty_8bpp}/{n_tiles_8bpp} ({empty_8bpp*100//n_tiles_8bpp}%)")


if __name__ == "__main__":
    report = analyze_roms()
