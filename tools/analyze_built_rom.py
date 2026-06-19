#!/usr/bin/env python3
"""Analyze the built ROM layout."""

with open("/home/chad/supermn-snes/build/superman.sfc", "rb") as f:
    data = f.read()

print(f"ROM size: {len(data)} bytes ({len(data)//1024}KB)")

# Search for reset handler code
reset_pattern = bytes([0x78, 0x18, 0xFB, 0xC2, 0x30])  # sei clc xce rep #30
idx = data.find(reset_pattern)
if idx >= 0:
    print(f"Found reset handler at file offset 0x{idx:06X}")
    # Show the code
    print("Code:")
    for i in range(idx, min(idx+64, len(data)), 16):
        hex_str = " ".join(f"{b:02X}" for b in data[i:i+16])
        print(f"  0x{i:06X}: {hex_str}")

# Search for NMI handler
nmi_pattern = bytes([0xE2, 0x20, 0xAD, 0x10, 0x42, 0xC2, 0x30, 0x68, 0x40])
idx = data.find(nmi_pattern)
if idx >= 0:
    print(f"\nFound NMI handler at file offset 0x{idx:06X}")

# Search for vector table (looking for 00 80 pattern = $8000 address)
print("\nSearching for $8000 address in vector table area...")
for i in range(0, len(data)-1, 2):
    if data[i] == 0x00 and data[i+1] == 0x80:
        # Could be a vector pointing to $8000
        if i % 0x8000 >= 0x7FE0:  # Near end of a bank
            print(f"  Found at 0x{i:06X} (bank {i//0x8000}, offset 0x{i%0x8000:04X})")
