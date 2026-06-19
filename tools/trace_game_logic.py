#!/usr/bin/env python3
"""
Trace Superman game logic from reset handler.
Uses the MAME source as a roadmap and cross-references with disassembly.

Reset vector: PC = $00003EF0, SP = $00F03FFE

From MAME taito_x.cpp, the reset handler at $3EF0 initializes:
1. C-Chip communication ($090001-$090005)
2. Frame registers ($300000, $400000, $600000)
3. Work RAM ($0F0000-$0FFFFF)
4. Then enters main loop calling game update at $3A92
"""

import struct

ROM_PATH = "/home/chad/supermn-snes/data/superman_m68k.bin"

with open(ROM_PATH, "rb") as f:
    rom = f.read()

def read_byte(addr):
    addr &= 0xFFFFFF
    if addr < len(rom): return rom[addr]
    return 0

def read_word(addr):
    return (read_byte(addr) << 8) | read_byte(addr + 1)

def read_long(addr):
    return (read_word(addr) << 16) | read_word(addr + 2)

def decode_op(addr):
    """Decode a 68K instruction. Returns (mnemonic, size)."""
    op = read_word(addr)
    
    # NOP
    if op == 0x4E71: return "nop", 2
    # RTS
    if op == 0x4E75: return "rts", 2
    # RTE
    if op == 0x4E73: return "rte", 2
    # RESET
    if op == 0x4E70: return "reset", 2
    
    # LEA abs.l, An
    if (op & 0xF1C0) == 0x41F9:
        reg = (op >> 9) & 7
        target = read_long(addr + 2)
        return "lea $%06X, a%d" % (target, reg), 6
    
    # MOVE.B #imm, abs.l
    if op == 0x13FC:
        imm = read_byte(addr + 2)
        target = read_long(addr + 4)
        return "move.b #$%02X, $%06X" % (imm, target), 8
    
    # MOVE.W #imm, abs.l
    if op == 0x33FC:
        imm = read_word(addr + 2)
        target = read_long(addr + 4)
        return "move.w #$%04X, $%06X" % (imm, target), 8
    
    # MOVE.L #imm, abs.l
    if op == 0x23FC:
        imm = read_long(addr + 2)
        target = read_long(addr + 6)
        return "move.l #$%08X, $%06X" % (imm, target), 10
    
    # MOVE.L Dn, abs.l
    if (op & 0xF1FF) == 0x23C0:
        dn = (op >> 9) & 7
        target = read_long(addr + 2)
        return "move.l d%d, $%06X" % (dn, target), 6
    
    # MOVE.B Dn, (An)
    if (op & 0xF1C0) == 0x1080:
        dn = (op >> 9) & 7
        an = op & 7
        return "move.b d%d, (a%d)" % (dn, an), 2
    
    # MOVE.B (An), Dn
    if (op & 0xF1C0) == 0x1010:
        an = op & 7
        dn = (op >> 9) & 7
        return "move.b (a%d), d%d" % (an, dn), 2
    
    # MOVE.B abs.l, Dn
    if (op & 0xF1FF) == 0x1039:
        dn = (op >> 9) & 7
        target = read_long(addr + 2)
        return "move.b $%06X, d%d" % (target, dn), 6
    
    # BSR
    if (op & 0xFF00) == 0x6100:
        offset = op & 0xFF
        if offset == 0:
            offset = read_word(addr + 2)
            if offset >= 0x8000: offset -= 0x10000
            return "bsr.w %+d -> $%06X" % (offset, addr + 2 + offset), 4
        else:
            if offset >= 128: offset -= 256
            return "bsr.b %+d -> $%06X" % (offset, addr + 2 + offset), 2
    
    # BRA
    if (op & 0xFF00) == 0x6000:
        offset = op & 0xFF
        if offset == 0:
            offset = read_word(addr + 2)
            if offset >= 0x8000: offset -= 0x10000
            return "bra.w %+d -> $%06X" % (offset, addr + 2 + offset), 4
        else:
            if offset >= 128: offset -= 256
            return "bra.b %+d -> $%06X" % (offset, addr + 2 + offset), 2
    
    # BNE
    if (op & 0xFF00) == 0x6600:
        offset = op & 0xFF
        if offset == 0:
            offset = read_word(addr + 2)
            if offset >= 0x8000: offset -= 0x10000
            return "bne.w %+d -> $%06X" % (offset, addr + 2 + offset), 4
        else:
            if offset >= 128: offset -= 256
            return "bne.b %+d -> $%06X" % (offset, addr + 2 + offset), 2
    
    # BEQ
    if (op & 0xFF00) == 0x6700:
        offset = op & 0xFF
        if offset == 0:
            offset = read_word(addr + 2)
            if offset >= 0x8000: offset -= 0x10000
            return "beq.w %+d -> $%06X" % (offset, addr + 2 + offset), 4
        else:
            if offset >= 128: offset -= 256
            return "beq.b %+d -> $%06X" % (offset, addr + 2 + offset), 2
    
    # BTST #bit, abs.l
    if op == 0x0839:
        bit = read_word(addr + 2)
        target = read_long(addr + 4)
        return "btst #%d, $%06X" % (bit, target), 8
    
    # CMPI.B #imm, abs.l
    if (op & 0xFFC0) == 0x0C39:
        imm = read_word(addr + 2) & 0xFF
        target = read_long(addr + 4)
        return "cmpi.b #$%02X, $%06X" % (imm, target), 8
    
    # CMPI.B #imm, Dn
    if (op & 0xFFC0) == 0x0C00:
        imm = read_word(addr + 2) & 0xFF
        reg = (op >> 9) & 7
        return "cmpi.b #$%02X, d%d" % (imm, reg), 4
    
    # ADDA.L #imm, SP
    if op == 0xDFFC:
        imm = read_long(addr + 2)
        return "adda.l #$%08X, sp" % imm, 6
    
    # MOVEC Rc, Rn (privileged)
    if (op & 0xF1FF) == 0x4E7A:
        return "movec ???", 4
    
    # MOVE SR, abs.l (from disassembly at $6C4 area)
    if (op & 0xFFC0) == 0x40C0 and (op & 0x0038) == 0x0038:
        target = 0
        ea = op & 0x3F
        if ea == 0x38:  # abs.w
            target = read_word(addr + 2)
            return "move sr, $%04X" % target, 4
        elif ea == 0x39:  # abs.l
            target = read_long(addr + 2)
            return "move sr, $%06X" % target, 6
    
    # ORI.W #imm, SR
    if (op & 0xFFFF) == 0x007C:
        imm = read_word(addr + 2)
        return "ori.w #$%04X, sr" % imm, 4
    
    # ANDI.W #imm, SR
    if (op & 0xFFFF) == 0x027C:
        imm = read_word(addr + 2)
        return "andi.w #$%04X, sr" % imm, 4
    
    # MOVE.L #imm, Dn
    if (op & 0xF138) == 0x2038:
        reg = op & 7
        # Check if it's abs.l or abs.w
        ea = (op >> 3) & 7
        if ea == 7:  # abs.l
            target = read_long(addr + 2)
            return "move.l $%06X, d%d" % (target, reg), 6
        elif ea == 1:  # (An) indirect
            an = (op >> 3) & 7
            target = read_long(addr + 2)
            return "move.l $%06X, (a%d)" % (target, an), 6
    
    # MOVE.B Dn, abs.l
    if (op & 0xF1FF) == 0x13C0:
        dn = (op >> 9) & 7
        target = read_long(addr + 2)
        return "move.b d%d, $%06X" % (dn, target), 6
    
    # MOVE.W Dn, abs.l
    if (op & 0xF1FF) == 0x33C0:
        dn = (op >> 9) & 7
        target = read_long(addr + 2)
        return "move.w d%d, $%06X" % (dn, target), 6
    
    return "??? ($%04X)" % op, 2

# Trace from reset handler
print("=" * 70)
print("SUPERMAN GAME LOGIC TRACE — Reset Handler")
print("=" * 70)

# Start at reset vector
pc = 0x3EF0
sp = read_long(0)

print(f"\nReset Vector:")
print(f"  SP = $%08X" % sp)
print(f"  PC = $%08X" % pc)
print()

# Decode the reset handler (first 50 instructions)
print("Reset Handler ($3EF0):")
print("-" * 70)
for i in range(50):
    if pc >= len(rom) - 1:
        break
    instr, size = decode_op(pc)
    
    # Highlight interesting addresses
    marker = ""
    if "09000" in instr: marker = " [C-CHIP]"
    elif "300000" in instr or "400000" in instr or "600000" in instr: marker = " [FRAME]"
    elif "0F0000" in instr: marker = " [WRAM]"
    elif "bsr" in instr.lower() or "jsr" in instr.lower(): marker = " [CALL]"
    elif "rts" in instr.lower() or "rte" in instr.lower(): marker = " [RETURN]"
    
    raw = " ".join("%02X" % read_byte(pc + j) for j in range(min(size, 8)))
    print(f"  $%06X: %-40s %-8s%s" % (pc, instr, raw, marker))
    pc += size

# Now trace the main game loop
print("\n" + "=" * 70)
print("MAIN GAME FUNCTION ($3A92):")
print("-" * 70)

pc = 0x3A92
for i in range(50):
    if pc >= len(rom) - 1:
        break
    instr, size = decode_op(pc)
    
    marker = ""
    if "09000" in instr: marker = " [C-CHIP]"
    elif "300000" in instr or "400000" in instr or "600000" in instr: marker = " [FRAME]"
    elif "0F0000" in instr: marker = " [WRAM]"
    elif "bsr" in instr.lower() or "jsr" in instr.lower(): marker = " [CALL]"
    elif "rts" in instr.lower() or "rte" in instr.lower(): marker = " [RETURN]"
    elif "0E000" in instr: marker = " [SPRITE]"
    elif "0B000" in instr: marker = " [PALETTE]"
    elif "0D000" in instr: marker = " [VIDEO]"
    elif "80000" in instr: marker = " [SOUND]"
    
    raw = " ".join("%02X" % read_byte(pc + j) for j in range(min(size, 8)))
    print(f"  $%06X: %-40s %-8s%s" % (pc, instr, raw, marker))
    pc += size

# Also check the IRQ handler
print("\n" + "=" * 70)
print("IRQ HANDLER (from vector table):")
print("-" * 70)

# Read IRQ vectors from the vector table
for vec in [25, 26, 27, 28, 29, 30, 31]:
    addr = read_long(vec * 4)
    if addr > 0 and addr < len(rom) - 1 and addr != 0xFFFFFFFF:
        print(f"\n  IRQ Vector {vec}: handler at $%06X" % addr)
        pc = addr
        for i in range(15):
            if pc >= len(rom) - 1:
                break
            instr, size = decode_op(pc)
            marker = ""
            if "jsr" in instr.lower(): marker = " [CALL]"
            raw = " ".join("%02X" % read_byte(pc + j) for j in range(min(size, 8)))
            print(f"    $%06X: %-40s %-8s%s" % (pc, instr, raw, marker))
            pc += size

# Find all JSR $xxxxxx targets in the first 0x10000 bytes
print("\n" + "=" * 70)
print("JSR TARGETS IN LOW ROM ($0000-$FFFF):")
print("-" * 70)

jsr_targets = {}
target_counts = {}
for addr in range(0, min(len(rom) - 6, 0x10000), 2):
    op = read_word(addr)
    # JSR abs.l
    if op == 0x4EB9:
        target = read_long(addr + 2)
        if target < len(rom):
            target_counts[target] = target_counts.get(target, 0) + 1

# Print targets sorted by count
sorted_targets = sorted(target_counts.items(), key=lambda x: x[1], reverse=True)
for target, count in sorted_targets[:30]:
    if count >= 2:
        print(f"  $%06X: %d references" % (target, count))

# Show all single JSR targets in key ranges
print("\nJSR targets in key ranges:")
for target, count in sorted_targets:
    if count == 1:
        if 0x2000 <= target < 0x3000:
            print(f"  $%06X (sound/input area)" % target)
        elif 0x3000 <= target < 0x4000:
            print(f"  $%06X (game logic area)" % target)
        elif 0x4000 <= target < 0x5000:
            print(f"  $%06X (graphics area)" % target)
        elif target >= 0x8000:
            print(f"  $%06X (high ROM)" % target)
