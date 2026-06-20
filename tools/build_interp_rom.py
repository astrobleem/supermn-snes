#!/usr/bin/env python3
"""
Build the full-ROM 68K-interpreter harness: a 1MB HiROM .sfc embedding the
65816 interpreter (file $8000, CPU $00/$C0:8000-FFFF) + the entire 512KB 68K
program image (file $10000, CPU $C1:0000+ — so 68K addr A reads flat at $C10000+A).
Load this in Mesen (MESEN_ROM) to let the interpreter follow cross-ROM control flow.
"""
from pathlib import Path

INTERP = Path("src/interp.bin").read_bytes()        # 32KB ($8000-$FFFF)
IMG = Path("data/superman_m68k.bin").read_bytes()   # 512KB 68K program
GFX = Path("tools/mame-trace/gfx1.bin").read_bytes() # 2MB arcade tile ROM (16x16 planar 4bpp)
assert len(INTERP) == 0x8000, len(INTERP)
assert len(IMG) == 0x80000, len(IMG)
assert len(GFX) == 0x200000, len(GFX)

# 4MB HiROM: interp @ $C0:8000, 68K image @ $C1:0000 (file $10000), arcade tile ROM
# gfx1 @ $C9:0000 (file $90000) so the runtime tile decoder reads gfx[code*1024+off]
# at flat CPU address $C90000 + code*1024.
ROM = bytearray(0x400000)                            # 4MB HiROM
ROM[0x8000:0x10000] = INTERP                         # interpreter + vectors @ $00/$C0:8000
ROM[0x10000:0x90000] = IMG                           # 68K image @ $C1:0000 (flat $C10000+A)
ROM[0x90000:0x290000] = GFX                          # arcade tiles @ $C9:0000 (flat $C90000+off)

# HiROM cartridge header at file $FFC0 (= CPU $00:FFC0)
H = 0xFFC0
title = b"SUPERMAN INTERP H>SNES"[:21].ljust(21, b" ")
ROM[H:H+21] = title
ROM[H+0x15] = 0x31      # map mode: HiROM + FastROM
ROM[H+0x16] = 0x00      # cart type: ROM only
ROM[H+0x17] = 0x0C      # ROM size: 4MB (2^12 KB)
ROM[H+0x18] = 0x00      # SRAM size: none
ROM[H+0x19] = 0x01      # country
ROM[H+0x1A] = 0x33      # licensee
ROM[H+0x1B] = 0x00      # version
# checksum (zero the fields, sum, write complement+checksum)
for i in range(H+0x1C, H+0x20):
    ROM[i] = 0x00
total = sum(ROM) & 0xFFFF
comp = (~total) & 0xFFFF
ROM[H+0x1C] = comp & 0xFF
ROM[H+0x1D] = (comp >> 8) & 0xFF
ROM[H+0x1E] = total & 0xFF
ROM[H+0x1F] = (total >> 8) & 0xFF

out = Path("build/interp.sfc")
out.parent.mkdir(exist_ok=True)
out.write_bytes(ROM)
print(f"wrote {out} ({len(ROM)} bytes, HiROM)")
print(f"reset vector @file $FFFC: ${ROM[0xFFFC]|(ROM[0xFFFD]<<8):04X}")
print(f"68K image @ $C1:0000 (file $10000); 68K reset bytes @ image $3EF0: "
      f"{IMG[0x3EF0:0x3EF6].hex()}")
