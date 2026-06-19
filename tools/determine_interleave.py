#!/usr/bin/env python3
"""Determine correct ROM interleaving for Taito X system."""

import struct

with open("/home/chad/superman-arcade/b61-01.e18", "rb") as f:
    rom1 = f.read()
with open("/home/chad/superman-arcade/b61-14.f1", "rb") as f:
    rom2 = f.read()

print(f"ROM1: {len(rom1)} bytes, ROM2: {len(rom2)} bytes")

# Try all interleaving configurations
configs = {
    "ROM1 only": rom1,
    "ROM2 only": rom2,
    "Byte interleave (R2 even, R1 odd)": None,
    "Byte interleave (R1 even, R2 odd)": None,
    "Word interleave (R1 lo, R2 hi)": None,
    "Word interleave (R2 lo, R1 hi)": None,
}

# Build interleaved versions
# Config: ROM2 even, ROM1 odd
byt_int1 = bytearray(len(rom1) + len(rom2))
byt_int1[0::2] = rom2[:len(byt_int1)//2]
byt_int1[1::2] = rom1[:len(byt_int1)//2]
configs["Byte interleave (R2 even, R1 odd)"] = byt_int1

# Config: ROM1 even, ROM2 odd
byt_int2 = bytearray(len(rom1) + len(rom2))
byt_int2[0::2] = rom1[:len(byt_int2)//2]
byt_int2[1::2] = rom2[:len(byt_int2)//2]
configs["Byte interleave (R1 even, R2 odd)"] = byt_int2

# Word interleaving
def word_interleave(r1, r2):
    result = bytearray(len(r1) + len(r2))
    for i in range(0, min(len(r1), len(r2)), 4):
        result[i*2:i*2+4] = r1[i:i+4]
        result[i*2+4:i*2+8] = r2[i:i+4]
    return result

configs["Word interleave (R1 lo, R2 hi)"] = word_interleave(rom1, rom2)
configs["Word interleave (R2 lo, R1 hi)"] = word_interleave(rom2, rom1)

print("\n--- Vector Table Analysis ---")
for name, data in configs.items():
    if data is None:
        continue
    sp = struct.unpack(">I", data[0:4])[0]
    pc = struct.unpack(">I", data[4:8])[0]
    
    # Check validity
    sp_valid = 0x00100000 <= sp <= 0x00FFFFFF  # RAM area
    pc_valid = 0x00000000 <= pc <= 0x00FFFFFF  # ROM area
    both_valid = sp_valid and pc_valid
    
    marker = " <<< VALID" if both_valid else ""
    print(f"\n{name}:")
    print(f"  SP = 0x{sp:08X} {'(valid RAM)' if sp_valid else '(suspicious)'}")
    print(f"  PC = 0x{pc:08X} {'(valid ROM)' if pc_valid else '(suspicious)'}{marker}")
    
    if both_valid:
        print(f"  First 16 bytes at PC:")
        if pc < len(data) - 16:
            for i in range(pc, min(pc+16, len(data)), 16):
                hex_str = " ".join(f"{b:02X}" for b in data[i:i+16])
                print(f"    0x{i:06X}: {hex_str}")
