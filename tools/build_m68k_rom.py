#!/usr/bin/env python3
"""
Build the Superman 68000 ROM image for Peony disassembly.

From MAME taito_f2.cpp ROM layout for Superman:

68000 Code (512KB at 0x000000-0x07FFFF):
  b61_09.a10  0x00000  128KB  even bytes (word-swapped)
  b61_07.a5   0x00001  128KB  odd bytes (word-swapped)
  b61_08.a8   0x40000  128KB  even bytes (word-swapped)
  b61_13.a3   0x40001  128KB  odd bytes (word-swapped)

Graphics (2MB at 0x080000-0x27FFFF):
  b61-16.j1   0x000000  512KB  Plane 2,3 (word-swapped)
  b61-17.k1   0x100000  512KB  Plane 2,3 (word-swapped)
  b61-14.f1   0x000002  512KB  Plane 0,1 (word-swapped)
  b61-15.h1   0x100002  512KB  Plane 0,1 (word-swapped)

Sound:
  b61_10.d18  Z80 program  64KB
  b61-01.e18  ADPCM samples  512KB (at 0x280000)

ROM_LOAD16_BYTE: loads even/odd bytes of each 16-bit word
ROM_LOAD32_WORD_SWAP: loads 32-bit words with byte swapping within each word

For the 68K code ROM, we need to interleave the byte pairs:
  ROM_LOAD16_BYTE("a", 0x00000, ...) -> bytes at even offsets
  ROM_LOAD16_BYTE("b", 0x00001, ...) -> bytes at odd offsets
  
  But with word-swap: the 16-bit words are stored as [lo, hi] instead of [hi, lo]
  
  Actually, ROM_LOAD16_BYTE just means:
    even bytes of 68K address space = first file
    odd bytes of 68K address space = second file
    
  So for address N in the 68K space:
    if N is even: byte = file1[N/2]
    if N is odd:  byte = file2[N/2]
    
  Wait, that's not right either. Let me think about this more carefully.
  
  ROM_LOAD16_BYTE("a", base, size, ...) means:
    The 68K sees 16-bit words. Each word is split across two ROM chips.
    Chip "a" provides the low byte (bits 0-7) of each word.
    Chip "b" provides the high byte (bits 8-15) of each word.
    
  So for 68K address A:
    word_addr = A >> 1
    if A & 1 == 0: byte = chip_a[word_addr] & 0xFF  (low byte)
    if A & 1 == 1: byte = chip_b[word_addr] >> 8     (high byte)
    
  Actually no. ROM_LOAD16_BYTE with offset 0x00000 and 0x00001 means:
    The first ROM is mapped to the even byte lanes (D0-D7)
    The second ROM is mapped to the odd byte lanes (D8-D15)
    
  For a 68K read at address A:
    if A is even: data = ROM_A[A/2] (byte from even ROM)
    if A is odd:  data = ROM_B[A/2] (byte from odd ROM)
    
  Wait, that's byte-interleaving. Let me just build it and check the reset vector.
"""

import struct
import os

ROM_DIR = "/home/chad/superman-arcade"
OUT_DIR = "/home/chad/supermn-snes/data"

def load(name):
    with open(os.path.join(ROM_DIR, name), "rb") as f:
        return f.read()

# Load 68K code ROMs
# From MAME: ROM_LOAD16_BYTE with offsets 0x00000 and 0x00001
# This means: even bytes from first ROM, odd bytes from second ROM
# For each 16-bit word at address A>>1:
#   low byte (D0-D7) = ROM_even[A>>1]
#   high byte (D8-D15) = ROM_odd[A>>1]

# But wait - the MAME offsets are 0x00000 and 0x00001, which are byte offsets
# in the 68K address space. So:
#   68K address 0x00000 (byte) -> ROM_even[0]
#   68K address 0x00001 (byte) -> ROM_odd[0]
#   68K address 0x00002 (byte) -> ROM_even[1]
#   68K address 0x00003 (byte) -> ROM_odd[1]
#   ...

# So the interleaving is: even bytes from ROM_even, odd bytes from ROM_odd
# This is exactly what we found earlier (Config 4)!

# For the first 512KB of 68K code:
# b61_09.a10 at offset 0x00000 (128KB) -> even bytes
# b61_07.a5  at offset 0x00001 (128KB) -> odd bytes
# But wait, 128KB each with byte interleaving = 256KB total
# We need 512KB total, so there must be more ROMs

# Looking at MAME again:
# b61_09.a10  0x00000  128KB  (even)
# b61_07.a5   0x00001  128KB  (odd)
# These cover 0x00000-0x0FFFF (128KB words = 256KB bytes)

# b61_08.a8   0x40000  128KB  (even)
# b61_13.a3   0x40001  128KB  (odd)
# These cover 0x40000-0x4FFFF (128KB words = 256KB bytes)

# Total: 512KB of 68K code space

# But wait, the ROM sizes are 128KB each. With byte interleaving:
# 128KB even + 128KB odd = 256KB of 68K address space per pair
# Two pairs = 512KB total

# Actually I think the MAME ROM_LOAD16_BYTE works differently.
# The size parameter is the size of each ROM chip, not the address range.
# With 128KB chips and byte interleaving, each pair covers 128KB of 68K words
# = 256KB of 68K bytes. But the offset is in bytes...

# Let me just try the simple approach: interleave and check the vector table

print("Building 68K code ROM...")

# Load the four code ROMs
rom_a1 = load("b61_09.a10")  # 128KB - even bytes, low bank
rom_b1 = load("b61_07.a5")   # 128KB - odd bytes, low bank
rom_a2 = load("b61_08.a8")   # 128KB - even bytes, high bank
rom_b2 = load("b61_13.a3")   # 128KB - odd bytes, high bank

print(f"  b61_09.a10: {len(rom_a1)} bytes")
print(f"  b61_07.a5:  {len(rom_b1)} bytes")
print(f"  b61_08.a8:  {len(rom_a2)} bytes")
print(f"  b61_13.a3:  {len(rom_b2)} bytes")

# Build the 512KB 68K ROM
# Low bank: interleave rom_a1 (even) and rom_b1 (odd)
low_bank = bytearray(256 * 1024)  # 256KB
for i in range(min(len(rom_a1), len(rom_b1))):
    low_bank[i * 2] = rom_a1[i]
    low_bank[i * 2 + 1] = rom_b1[i]

# High bank: interleave rom_a2 (even) and rom_b2 (odd)
high_bank = bytearray(256 * 1024)  # 256KB
for i in range(min(len(rom_a2), len(rom_b2))):
    high_bank[i * 2] = rom_a2[i]
    high_bank[i * 2 + 1] = rom_b2[i]

# Combine: low bank at 0x00000, high bank at 0x40000
# But that leaves a gap from 0x10000-0x3FFFF
# Actually, the 68K address space is continuous:
# 0x00000-0x0FFFF: low bank (256KB)
# 0x10000-0x1FFFF: ??? (256KB gap?)
# 0x20000-0x2FFFF: ??? 
# 0x30000-0x3FFFF: ???
# 0x40000-0x4FFFF: high bank (256KB)

# Hmm, that doesn't make sense. Let me re-read the MAME source.
# The offsets 0x00000 and 0x40000 are byte offsets in the 68K space.
# With 128KB ROMs and byte interleaving:
# Pair 1 covers 0x00000-0x0FFFF (128K words = 256K bytes)
# Pair 2 covers 0x40000-0x4FFFF (128K words = 256K bytes)

# But that's only 512KB total with a 768KB gap. That seems wrong.
# Let me check: maybe the ROMs are 256KB each, not 128KB?

# Actually wait - the MAME size is 0x20000 = 131072 = 128KB per ROM
# With byte interleaving, 128KB even + 128KB odd = 256KB address space
# Two pairs at 0x00000 and 0x40000 = 512KB total address space

# But the gap from 0x10000-0x3FFFF is suspicious. Let me check if maybe
# the ROMs are actually mapped contiguously without gaps.

# Actually, I think the issue is that ROM_LOAD16_BYTE with size 0x20000
# means each ROM is 128KB, and together they cover 128KB of 68K words.
# The 68K word at address N uses:
#   D0-D7 = ROM_even[N % 128K]
#   D8-D15 = ROM_odd[N % 128K]
# So the total address space covered is 128K words = 256KB bytes.

# For the full 512KB ROM, we need to map:
# 0x00000-0x0FFFF: pair 1 (low)
# 0x10000-0x1FFFF: pair 1 mirror? Or pair 2?
# 0x20000-0x2FFFF: ???
# 0x30000-0x3FFFF: ???
# 0x40000-0x4FFFF: pair 2 (high)

# This is getting complicated. Let me just build a contiguous 512KB ROM
# by placing the low bank at 0x00000 and high bank at 0x10000
# (ignoring the MAME offset gap for now)

# Actually, the simplest interpretation: the two pairs are mapped at
# 0x00000-0x0FFFF and 0x10000-0x1FFFF (contiguous)
# The MAME offset 0x40000 might be for a different ROM bank mode

# Let me just try: low bank at 0x00000, high bank at 0x10000
full_rom = bytearray(512 * 1024)  # 512KB
full_rom[0:len(low_bank)] = low_bank
full_rom[0x10000:0x10000+len(high_bank)] = high_bank

# Check the reset vector
sp = struct.unpack(">I", full_rom[0:4])[0]
pc = struct.unpack(">I", full_rom[4:8])[0]
print(f"\nReset vector (low+high contiguous):")
print(f"  SP = 0x{sp:08X}")
print(f"  PC = 0x{pc:08X}")

# Also try: low bank at 0x00000, high bank at 0x40000 (MAME layout)
full_rom2 = bytearray(512 * 1024)
full_rom2[0:len(low_bank)] = low_bank
full_rom2[0x40000:0x40000+len(high_bank)] = high_bank

sp2 = struct.unpack(">I", full_rom2[0:4])[0]
pc2 = struct.unpack(">I", full_rom2[4:8])[0]
print(f"\nReset vector (MAME layout with gap):")
print(f"  SP = 0x{sp2:08X}")
print(f"  PC = 0x{pc2:08X}")

# Check which PC values are valid (point into ROM)
for name, rom in [("contiguous", full_rom), ("MAME layout", full_rom2)]:
    sp = struct.unpack(">I", rom[0:4])[0]
    pc = struct.unpack(">I", rom[4:8])[0]
    
    # Valid SP: should be in RAM area (0x00F00000-0x00FFFFFF based on MAME map)
    # Valid PC: should be in ROM area (0x00000000-0x0007FFFF)
    sp_valid = 0x00F00000 <= sp <= 0x00FFFFFF
    pc_valid = 0x00000000 <= pc <= 0x0007FFFF
    
    print(f"\n{name}:")
    print(f"  SP = 0x{sp:08X} {'VALID' if sp_valid else 'invalid'}")
    print(f"  PC = 0x{pc:08X} {'VALID' if pc_valid else 'invalid'}")
    
    if pc_valid and pc < len(rom):
        print(f"  Code at PC:")
        for i in range(pc, min(pc+32, len(rom)), 16):
            hex_str = " ".join(f"{b:02X}" for b in rom[i:i+16])
            print(f"    0x{i:06X}: {hex_str}")

# Save the best configuration
if pc_valid:
    output_path = os.path.join(OUT_DIR, "superman_m68k.bin")
    with open(output_path, "wb") as f:
        f.write(rom)
    print(f"\nSaved to {output_path}")
elif pc2_valid:
    output_path = os.path.join(OUT_DIR, "superman_m68k.bin")
    with open(output_path, "wb") as f:
        f.write(full_rom2)
    print(f"\nSaved to {output_path}")
