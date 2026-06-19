#!/usr/bin/env python3
"""
Generate a comprehensive CDL file using all known entry points.
Format: C <addr> for code, D <addr> for data
"""

import struct
import json
import os

ROM_PATH = "/home/chad/supermn-snes/data/superman_m68k.bin"
CDL_PATH = "/home/chad/supermn-snes/data/superman_vectors.cdl"

with open(ROM_PATH, "rb") as f:
    rom = f.read()

# Load vector table
with open("/home/chad/supermn-snes/data/vector_table.json") as f:
    vectors = json.load(f)

code_addrs = set()

# Add all valid ROM vectors
for v in vectors:
    if v["in_rom"]:
        addr = int(v["address"], 16)
        # For vectors, the address IS the handler address (not a pointer)
        code_addrs.add(addr)

# Add known MAME addresses that are in ROM
known_rom_addrs = [
    0x07FFFE,  # Region storage
]

for addr in known_rom_addrs:
    if addr < len(rom):
        code_addrs.add(addr)

# Now do a simple linear scan from each entry point
# Mark consecutive valid-looking instructions as code
# Stop when we hit an invalid opcode or a known data area

def looks_like_code(addr):
    """Check if bytes at addr look like a valid 68K instruction."""
    if addr + 2 > len(rom):
        return False
    op = struct.unpack(">H", rom[addr:addr+2])[0]
    
    # Reject obvious data patterns
    if op == 0x0000:
        return False
    if op == 0xFFFF:
        return False
    
    # Check top nibble — all 0-F are valid for 68K
    return True

# For each entry point, scan forward until we hit something that doesn't look like code
for entry in sorted(code_addrs):
    addr = entry
    consecutive_bad = 0
    while addr < len(rom) - 1 and consecutive_bad < 3:
        if looks_like_code(addr):
            code_addrs.add(addr)
            consecutive_bad = 0
            addr += 2
        else:
            consecutive_bad += 1
            addr += 2

print(f"Total code addresses: {len(code_addrs)}")
print(f"Total code bytes: {len(code_addrs) * 2}")
print(f"Coverage: {len(code_addrs) * 2 / len(rom) * 100:.1f}%")

# Write CDL
with open(CDL_PATH, "w") as f:
    for addr in sorted(code_addrs):
        f.write(f"C 0x{addr:06X}\n")

print(f"CDL saved to: {CDL_PATH}")
