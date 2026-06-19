#!/usr/bin/env python3
"""
Generate a CDL (Code/Data Log) file for Peony.
CDL format: each line is either:
  C <addr>    - Code
  D <addr>    - Data  
  S <addr>    - Skip (unused)
  X <addr>    - Reference to code from data
"""

import json

# Load vector table
with open("/home/chad/supermn-snes/data/vector_table.json") as f:
    vectors = json.load(f)

# Also include all TRAP vectors and key addresses
code_addrs = set()

# From vector table - all valid ROM addresses
for v in vectors:
    if v["in_rom"] and v["index"] > 1:
        code_addrs.add(int(v["address"], 16))

# Known entry points from MAME analysis
known = [
    0x003EF0,  # Reset handler start
    0x0006C4,  # IRQ 2/6 handler
    0x00082C,  # IRQ 4 handler
    0x000466,  # TRAP 1
    0x00042A,  # TRAP 2
    0x00044E,  # TRAP 3
    0x000500,  # TRAP 4
    0x000532,  # TRAP 5
    0x00057A,  # TRAP 6
    0x000554,  # TRAP 7
    0x0005AC,  # TRAP 8
    0x0005EE,  # TRAP 9
    0x00063E,  # TRAP 10
    0x000684,  # TRAP 11
    0x0006C2,  # TRAP 12 (just rte)
]

for addr in known:
    code_addrs.add(addr)

# Generate CDL
lines = []
for addr in sorted(code_addrs):
    lines.append(f"C 0x{addr:06X}")

cdl_path = "/home/chad/supermn-snes/data/superman.cdl"
with open(cdl_path, "w") as f:
    f.write("\n".join(lines) + "\n")

print(f"Generated CDL with {len(code_addrs)} code entry points")
print(f"Saved to: {cdl_path}")

# Also generate the addr file for Peony
addr_path = "/home/chad/supermn-snes/data/superman_addrs.txt"
with open(addr_path, "w") as f:
    for addr in sorted(code_addrs):
        f.write(f"0x{addr:06X}\n")
print(f"Address list saved to: {addr_path}")
