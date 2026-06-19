#!/usr/bin/env python3
"""
Superman ROM preparation for Peony disassembly.

Taito X System memory map (from MAME taito_x.cpp):
  68000 ROM mapping:
    The two 512KB program ROMs are interleaved or mapped contiguously.
    b61-01.e18 = even bytes (or low 256KB)
    b61-14.f1  = odd bytes (or high 256KB)
    
  For Peony, we need a single contiguous ROM file.
  
  Taito F2/X games typically interleave the two ROMs:
    Byte 0 = ROM1[0], Byte 1 = ROM2[0], Byte 2 = ROM1[1], Byte 3 = ROM2[1]...
  
  OR they might be mapped as:
    ROM1 at $000000-$07FFFF, ROM2 at $080000-$0FFFFF
    
  We need to determine the correct interleaving by checking the reset vector.
"""

import struct
import os
import sys

ROM_DIR = "/home/chad/superman-arcade"
OUT_DIR = "/home/chad/data/superman-roms"
os.makedirs(OUT_DIR, exist_ok=True)

def load_rom(name):
    path = os.path.join(ROM_DIR, name)
    with open(path, "rb") as f:
        return f.read()

# Load the two program ROMs
rom1 = load_rom("b61-01.e18")  # 512KB
rom2 = load_rom("b61-14.f1")   # 512KB

print(f"ROM1 (b61-01.e18): {len(rom1)} bytes")
print(f"ROM2 (b61-14.f1):  {len(rom2)} bytes")

# Check for 68000 reset vector in different configurations
# 68000 reset vector: first 4 bytes = SP, next 4 bytes = PC (both big-endian)

# Config 1: ROM1 only (not interleaved)
sp = struct.unpack(">I", rom1[0:4])[0]
pc = struct.unpack(">I", rom1[4:8])[0]
print(f"\nConfig 1 - ROM1 only:")
print(f"  SP = ${sp:08X}, PC = ${pc:08X}")
if 0x10000 <= sp <= 0x1000000 and 0x10000 <= pc <= 0x1000000:
    print(f"  -> VALID VECTORS!")
else:
    print(f"  -> Invalid (SP or PC out of typical range)")

# Config 2: ROM2 only
sp = struct.unpack(">I", rom2[0:4])[0]
pc = struct.unpack(">I", rom2[4:8])[0]
print(f"\nConfig 2 - ROM2 only:")
print(f"  SP = ${sp:08X}, PC = ${pc:08X}")
if 0x10000 <= sp <= 0x1000000 and 0x10000 <= pc <= 0x1000000:
    print(f"  -> VALID VECTORS!")
else:
    print(f"  -> Invalid")

# Config 3: Byte-interleaved (ROM1=even, ROM2=odd)
interleaved = bytearray(len(rom1) + len(rom2))
interleaved[0::2] = rom1
interleaved[1::2] = rom2
sp = struct.unpack(">I", interleaved[0:4])[0]
pc = struct.unpack(">I", interleaved[4:8])[0]
print(f"\nConfig 3 - Byte interleaved (ROM1=even, ROM2=odd):")
print(f"  SP = ${sp:08X}, PC = ${pc:08X}")
if 0x10000 <= sp <= 0x1000000 and 0x10000 <= pc <= 0x1000000:
    print(f"  -> VALID VECTORS!")
else:
    print(f"  -> Invalid")

# Config 4: Byte-interleaved (ROM2=even, ROM1=odd)
interleaved2 = bytearray(len(rom1) + len(rom2))
interleaved2[0::2] = rom2
interleaved2[1::2] = rom1
sp = struct.unpack(">I", interleaved2[0:4])[0]
pc = struct.unpack(">I", interleaved2[4:8])[0]
print(f"\nConfig 4 - Byte interleaved (ROM2=even, ROM1=odd):")
print(f"  SP = ${sp:08X}, PC = ${pc:08X}")
if 0x10000 <= sp <= 0x1000000 and 0x10000 <= pc <= 0x1000000:
    print(f"  -> VALID VECTORS!")
else:
    print(f"  -> Invalid")

# Config 5: Word-interleaved (ROM1=low word, ROM2=high word per 32-bit)
# Each 4 bytes: ROM1[0:2] + ROM2[0:2]
word_interleaved = bytearray(len(rom1) * 2)
for i in range(0, min(len(rom1), len(rom2)), 2):
    word_interleaved[i*2:i*2+2] = rom1[i:i+2]
    word_interleaved[i*2+2:i*2+4] = rom2[i:i+2]
sp = struct.unpack(">I", word_interleaved[0:4])[0]
pc = struct.unpack(">I", word_interleaved[4:8])[0]
print(f"\nConfig 5 - Word interleaved:")
print(f"  SP = ${sp:08X}, PC = ${pc:08X}")
if 0x10000 <= sp <= 0x1000000 and 0x10000 <= pc <= 0x1000000:
    print(f"  -> VALID VECTORS!")
else:
    print(f"  -> Invalid")

# Config 6: Contiguous (ROM1 at $000000, ROM2 at $080000 for 1MB total)
# For this we just concatenate
contiguous = rom1 + rom2
# Check at offset $080000 (8KB into the combined file)
sp = struct.unpack(">I", contiguous[0:4])[0]
pc = struct.unpack(">I", contiguous[4:8])[0]
print(f"\nConfig 6 - Contiguous (ROM1 low, ROM2 high):")
print(f"  ROM1 at 0x000000: SP = ${sp:08X}, PC = ${pc:08X}")
if 0x10000 <= sp <= 0x1000000 and 0x10000 <= pc <= 0x1000000:
    print(f"  -> VALID VECTORS at ROM1!")
sp2 = struct.unpack(">I", contiguous[0x80000:0x80004])[0]
pc2 = struct.unpack(">I", contiguous[0x80004:0x80008])[0]
print(f"  ROM2 at 0x080000: SP = ${sp2:08X}, PC = ${pc2:08X}")
if 0x10000 <= sp2 <= 0x1000000 and 0x10000 <= pc2 <= 0x1000000:
    print(f"  -> VALID VECTORS at ROM2!")

# Also check: maybe the first ROM is mapped at a different address
# Let's search for a valid vector across the first few KB of each ROM
print("\n\nSearching for valid 68K vector tables...")
for rom_name, rom_data in [("ROM1", rom1), ("ROM2", rom2)]:
    for offset in range(0, min(len(rom_data), 0x10000), 0x100):
        sp = struct.unpack(">I", rom_data[offset:offset+4])[0]
        pc = struct.unpack(">I", rom_data[offset+4:offset+8])[0]
        if (0x10000 <= sp <= 0x1000000 and 
            0x10000 <= pc <= 0x800000 and
            pc < len(rom_data) * 2):
            print(f"  {rom_name} offset 0x{offset:06X}: SP=${sp:08X} PC=${pc:08X}")
