#!/usr/bin/env python3
"""
Generate a focused CDL with only the most reliable entry points.
Use the vector table + known MAME addresses + recursive descent from those.
"""

import struct
import os
from collections import deque

ROM_PATH = "/home/chad/supermn-snes/data/superman_m68k.bin"
CDL_PATH = "/home/chad/supermn-snes/data/superman_focused.cdl"

with open(ROM_PATH, "rb") as f:
    rom = f.read()

# Start with vector table addresses that point to ROM
entry_points = set()

# From vector analysis — only vectors with valid ROM addresses
vector_targets = [
    (2, 0x0000DE),   # Bus Error
    (3, 0x0000FA),   # Address Error
    (4, 0x00011A),   # Illegal Instruction
    (5, 0x000142),   # Zero Divide
    (6, 0x000162),   # CHK
    (7, 0x000186),   # TRAPV
    (8, 0x0001AC),   # Privilege Violation
    (9, 0x0001D6),   # Trace
    (10, 0x0001F0),  # Line 1010
    (11, 0x000214),  # Line 1111
    (26, 0x0006C4),  # IRQ 2
    (28, 0x00082C),  # IRQ 4
    (30, 0x0006C4),  # IRQ 6 (same as IRQ 2)
    (33, 0x000466),  # TRAP 1
    (34, 0x00042A),  # TRAP 2
    (35, 0x00044E),  # TRAP 3
    (36, 0x000500),  # TRAP 4
    (37, 0x000532),  # TRAP 5
    (38, 0x00057A),  # TRAP 6
    (39, 0x000554),  # TRAP 7
    (40, 0x0005AC),  # TRAP 8
    (41, 0x0005EE),  # TRAP 9
    (42, 0x00063E),  # TRAP 10
    (43, 0x000684),  # TRAP 11
    (44, 0x0006C2),  # TRAP 12
]

for vec_num, addr in vector_targets:
    entry_points.add(addr)

# Also add the reset handler area
entry_points.add(0x003EF0)

# Recursive descent to find branch targets
def get_branch_target(op, addr):
    """Get branch target or None."""
    if (op & 0xF000) == 0x6000:  # Bcc
        offset = op & 0xFF
        if offset == 0:
            if addr + 4 <= len(rom):
                off = struct.unpack(">h", rom[addr+2:addr+4])[0]
                return addr + 2 + off
        elif offset == 0xFF:
            if addr + 6 <= len(rom):
                off = struct.unpack(">i", rom[addr+2:addr+6])[0]
                return addr + 2 + off
        else:
            if offset >= 128:
                offset -= 256
            return addr + 2 + offset
    return None

def get_instr_size(op, addr):
    """Estimate instruction size."""
    if (op & 0xF000) == 0x6000:
        offset = op & 0xFF
        if offset == 0:
            return 4
        elif offset == 0xFF:
            return 6
    if (op & 0xFFC0) in (0x4EF9, 0x4EB9):
        return 6
    if (op & 0xFFC0) in (0x4EF8, 0x4EB8):
        return 4
    if (op & 0xFFC0) in (0x007C, 0x003C):
        return 4
    return 2

# Follow branches from each entry point (limited depth)
code_addrs = set()
for entry in entry_points:
    queue = deque([(entry, 0)])
    visited = set()
    
    while queue:
        addr, depth = queue.popleft()
        if addr in visited or depth > 100:
            continue
        if addr < 0 or addr >= len(rom) - 1:
            continue
        
        visited.add(addr)
        
        # Follow this code path
        pc = addr
        for _ in range(50):  # Max 50 instructions per path
            if pc >= len(rom) - 1:
                break
            
            op = struct.unpack(">H", rom[pc:pc+2])[0]
            code_addrs.add(pc)
            
            # Check for branches
            target = get_branch_target(op, pc)
            if target is not None and 0 <= target < len(rom):
                queue.append((target, depth + 1))
            
            # Stop at RTS/RTE/JMP
            if op == 0x4E75:  # rts
                break
            if op == 0x4E73:  # rte
                break
            if (op & 0xFFC0) == 0x4EF9:  # jmp
                break
            if (op & 0xFF00) == 0x6000 and (op & 0x0F00) == 0x0000:  # bra
                break
            
            size = get_instr_size(op, pc)
            pc += size

print(f"Found {len(code_addrs)} code addresses")
print(f"Code bytes: {len(code_addrs) * 2}")
print(f"Coverage: {len(code_addrs) * 2 / len(rom) * 100:.1f}%")

# Write CDL
with open(CDL_PATH, "w") as f:
    for addr in sorted(code_addrs):
        f.write(f"C 0x{addr:06X}\n")

print(f"CDL saved to: {CDL_PATH}")
