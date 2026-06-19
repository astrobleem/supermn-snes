#!/usr/bin/env python3
"""
Generate a comprehensive CDL file for the Superman 68K ROM.

Strategy: Scan the entire ROM for valid 68K instruction patterns and mark them as code.
This is a heuristic approach — we look for common 68K opcode patterns.
"""

import struct
import os

ROM_PATH = "/home/chad/supermn-snes/data/superman_m68k.bin"
CDL_PATH = "/home/chad/supermn-snes/data/superman_full.cdl"

with open(ROM_PATH, "rb") as f:
    rom = f.read()

def is_valid_68k_op(addr):
    """Check if the bytes at addr look like a valid 68K instruction."""
    if addr + 2 > len(rom):
        return False
    
    op = struct.unpack(">H", rom[addr:addr+2])[0]
    top = (op >> 12) & 0xF
    
    # Known valid 68K opcode top nibbles:
    # 0: ori/andi/eori/subi/addi/btst/bset/bclr/cmpi/move (with sub-fields)
    # 1-3: move.b, move.l, move.w
    # 4: various (negx, clr, neg, not, ext, nbcd, swap, pea, movem, tst, jsr, jmp, etc.)
    # 5: addq/subq/scc/dbcc
    # 6: bcc/bsr/bra
    # 7: moveq
    # 8: or/div/sbcd
    # 9: sub/suba/subx
    # A: trap (unimplemented in normal 68K, but used)
    # B: cmp/cmpa/cmpx/eor
    # C: and/mulu/muls/exg
    # D: add/adda/addx
    # E: shift/rotate
    # F: trap/coprocessor
    
    # All 16 top nibbles are potentially valid for 68K
    # But some patterns are clearly invalid
    
    # Reject if it looks like data (all zeros, all 0xFF, etc.)
    if op == 0x0000:
        return False  # Could be data
    if op == 0xFFFF:
        return False
    
    return True

def scan_for_code():
    """Scan ROM for code-like patterns."""
    code_set = set()
    data_set = set()
    
    # Start from known entry points and follow branches
    # For now, just mark everything that looks like code
    addr = 0
    while addr < len(rom) - 1:
        if is_valid_68k_op(addr):
            code_set.add(addr)
            # Skip the instruction (at least 2 bytes)
            op = struct.unpack(">H", rom[addr:addr+2])[0]
            size = instr_size_estimate(op, addr, rom)
            addr += size
        else:
            data_set.add(addr)
            addr += 2
    
    return code_set, data_set

def instr_size_estimate(op, addr, rom):
    """Rough estimate of instruction size."""
    # Most instructions are 2 bytes + optional extension words
    # For scanning purposes, just return 2
    return 2

# Load existing CDL data
existing_code = set()
existing_data = set()

cdl_base = "/home/chad/supermn-snes/data/superman.cdl"
if os.path.exists(cdl_base):
    with open(cdl_base) as f:
        for line in f:
            line = line.strip()
            if line.startswith("C "):
                existing_code.add(int(line[2:], 16))
            elif line.startswith("D "):
                existing_data.add(int(line[2:], 16))

# Scan for more code
print("Scanning ROM for valid 68K instruction patterns...")
code_addrs, data_addrs = scan_for_code()
print(f"  Found {len(code_addrs)} potential code addresses")
print(f"  Found {len(data_addrs)} potential data addresses")

# Merge with existing CDL
all_code = code_addrs | existing_code
all_data = data_addrs | existing_data

# Don't mark the same address as both code and data
overlap = all_code & all_data
if overlap:
    # Prefer code for overlapping addresses
    all_data -= overlap

print(f"  Total code: {len(all_code)}")
print(f"  Total data: {len(all_data)}")

# Write CDL
with open(CDL_PATH, "w") as f:
    for addr in sorted(all_code):
        f.write(f"C 0x{addr:06X}\n")
    for addr in sorted(all_data):
        f.write(f"D 0x{addr:06X}\n")

print(f"\nCDL saved to: {CDL_PATH}")
print(f"Total entries: {len(all_code) + len(all_data)}")
