#!/usr/bin/env python3
"""
Recursive descent CDL generator for Superman 68K ROM.
Starting from known entry points, follow branches and calls to discover code.
"""

import struct
import os
from collections import deque

ROM_PATH = "/home/chad/supermn-snes/data/superman_m68k.bin"

with open(ROM_PATH, "rb") as f:
    rom = f.read()

ROM_SIZE = len(rom)

# Known entry points from vector table analysis
ENTRY_POINTS = [
    0x003EF0,  # Reset
    0x0000DE,  # Bus Error handler (vec 2)
    0x0000FA,  # Address Error
    0x00011A,  # Illegal Instruction
    0x000142,  # Zero Divide
    0x000162,  # CHK
    0x000186,  # TRAPV
    0x0001AC,  # Privilege Violation
    0x0001D6,  # Trace
    0x0006C4,  # IRQ 2/6
    0x00082C,  # IRQ 4
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
    0x0006C2,  # TRAP 12 (rte)
]

# Compute possible branch targets
def get_branch_target(op, addr):
    """Get the branch target address from a branch instruction, or None."""
    if addr + 2 > ROM_SIZE:
        return None
    
    # Bcc (0x6xxx)
    if (op & 0xF000) == 0x6000:
        offset = op & 0xFF
        if offset == 0:
            if addr + 4 <= ROM_SIZE:
                off = struct.unpack(">h", rom[addr+2:addr+4])[0]
                return addr + 2 + off
        elif offset == 0xFF:
            if addr + 6 <= ROM_SIZE:
                off = struct.unpack(">i", rom[addr+2:addr+6])[0]
                return addr + 2 + off
        else:
            if offset >= 128:
                offset -= 256
            return addr + 2 + offset
    
    # BRA (0x60xx without condition, but condition is in bits 8-11)
    # Actually BRA is 0x60xx where cond = 0 (always)
    if (op & 0xFF00) == 0x6000:
        offset = op & 0xFF
        if offset == 0:
            if addr + 4 <= ROM_SIZE:
                off = struct.unpack(">h", rom[addr+2:addr+4])[0]
                return addr + 2 + off
        elif offset == 0xFF:
            if addr + 6 <= ROM_SIZE:
                off = struct.unpack(">i", rom[addr+2:addr+6])[0]
                return addr + 2 + off
        else:
            if offset >= 128:
                offset -= 256
            return addr + 2 + offset
    
    # JMP
    if (op & 0xFFC0) == 0x4ED0:  # jmp (a0)
        return None  # Indirect, can't follow
    if (op & 0xFFC0) == 0x4EF9:  # jmp (abs.l)
        if addr + 6 <= ROM_SIZE:
            return struct.unpack(">I", rom[addr+2:addr+6])[0]
        return None
    if (op & 0xFFC0) == 0x4EF8:  # jmp (abs.w)
        if addr + 4 <= ROM_SIZE:
            target = struct.unpack(">H", rom[addr+2:addr+4])[0]
            return target
        return None
    
    # JSR
    if (op & 0xFFC0) == 0x4E90:  # jsr (a0)
        return None  # Indirect
    if (op & 0xFFC0) == 0x4EB9:  # jsr (abs.l)
        if addr + 6 <= ROM_SIZE:
            return struct.unpack(">I", rom[addr+2:addr+6])[0]
        return None
    if (op & 0xFFC0) == 0x4EB8:  # jsr (abs.w)
        if addr + 4 <= ROM_SIZE:
            target = struct.unpack(">H", rom[addr+2:addr+4])[0]
            return target
        return None
    
    return None


def scan_code():
    """Recursive descent from known entry points."""
    code_addrs = set()
    visited = set()
    queue = deque(ENTRY_POINTS)
    
    while queue:
        addr = queue.popleft()
        
        if addr in visited:
            continue
        if addr < 0 or addr >= ROM_SIZE:
            continue
        
        visited.add(addr)
        
        # Follow this code path
        pc = addr
        while pc < ROM_SIZE - 1:
            if pc in visited and pc != addr:
                break
            
            visited.add(pc)
            
            op = struct.unpack(">H", rom[pc:pc+2])[0]
            
            # Mark as code
            code_addrs.add(pc)
            
            # Check for branch/call targets
            target = get_branch_target(op, pc)
            if target is not None and 0 <= target < ROM_SIZE:
                queue.append(target)
            
            # Check for instructions that end the flow
            if op == 0x4E75:  # rts
                break
            if op == 0x4E73:  # rte
                break
            if (op & 0xFFC0) == 0x4EF9:  # jmp (abs.l)
                pc += 6
                break
            if (op & 0xFF00) == 0x6000 and (op & 0x0F00) == 0x0000:  # bra
                pc += get_instr_size(op, pc)
                break
            
            # Advance
            pc += get_instr_size(op, pc)
    
    return code_addrs


def get_instr_size(op, addr):
    """Get instruction size in bytes."""
    # 2 bytes base
    size = 2
    
    # Check for extension words
    # Bcc with 0 offset -> +2
    if (op & 0xF000) == 0x6000 and (op & 0xFF) == 0:
        size = 4
    elif (op & 0xF000) == 0x6000 and (op & 0xFF) == 0xFF:
        size = 6
    # JMP/JSR absolute long -> +4
    elif (op & 0xFFC0) in (0x4EF9, 0x4EB9):
        size = 6
    # JMP/JSR absolute short -> +2
    elif (op & 0xFFC0) in (0x4EF8, 0x4EB8):
        size = 4
    # Immediate instructions
    elif (op & 0xFFC0) in (0x007C, 0x003C):  # ori sr, ori ccr
        size = 4
    
    return size


# Run recursive descent
print("Running recursive descent from known entry points...")
found_code = scan_code()
print(f"  Found {len(found_code)} code addresses")
print(f"  Total code bytes: {len(found_code) * 2} ({len(found_code) * 2 / 1024:.1f}KB)")

# Generate CDL
CDL_PATH = "/home/chad/supermn-snes/data/superman_recursive.cdl"
with open(CDL_PATH, "w") as f:
    for addr in sorted(found_code):
        f.write(f"C 0x{addr:06X}\n")

print(f"CDL saved to: {CDL_PATH}")

# Count by region
regions = {}
for addr in found_code:
    region = "low" if addr < 0x10000 else "mid" if addr < 0x40000 else "high"
    regions[region] = regions.get(region, 0) + 1

print("\nCode by region:")
for region, count in sorted(regions.items()):
    print(f"  {region}: {count} instructions ({count*2/1024:.1f}KB)")
