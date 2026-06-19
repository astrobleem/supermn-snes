#!/usr/bin/env python3
"""
Analyze the 68K interrupt vector table and key addresses for Superman.
"""

import struct
import json
import os

ROM_PATH = "/home/chad/supermn-snes/data/superman_m68k.bin"
OUT_DIR = "/home/chad/supermn-snes/data"

with open(ROM_PATH, "rb") as f:
    rom = f.read()

print(f"ROM size: {len(rom)} bytes")
print()

# 68K Vector Table
print("=" * 70)
print("68K INTERRUPT VECTOR TABLE")
print("=" * 70)

vector_names = {}
vector_names[0] = "Initial SP"
vector_names[1] = "Initial PC (Reset)"
vector_names[2] = "Bus Error"
vector_names[3] = "Address Error"
vector_names[4] = "Illegal Instruction"
vector_names[5] = "Zero Divide"
vector_names[6] = "CHK Instruction"
vector_names[7] = "TRAPV Instruction"
vector_names[8] = "Privilege Violation"
vector_names[9] = "Trace"
vector_names[10] = "Line 1010 Emulator"
vector_names[11] = "Line 1111 Emulator"
for i in range(12, 15):
    vector_names[i] = "Reserved"
vector_names[15] = "Uninitialized Interrupt"
for i in range(16, 24):
    vector_names[i] = "Reserved"
vector_names[24] = "Spurious Interrupt"
vector_names[25] = "Level 1 IRQ (VBlank?)"
vector_names[26] = "Level 2 IRQ"
vector_names[27] = "Level 3 IRQ"
vector_names[28] = "Level 4 IRQ"
vector_names[29] = "Level 5 IRQ"
vector_names[30] = "Level 6 IRQ (Superman main)"
vector_names[31] = "Level 7 IRQ"
for i in range(32, 48):
    vector_names[i] = f"TRAP {i-32}"

vectors = []
for i in range(256):
    offset = i * 4
    if offset + 4 > len(rom):
        break
    addr = struct.unpack(">I", rom[offset:offset+4])[0]
    
    is_rom = 0x000000 <= addr <= 0x07FFFF
    is_ram = 0x0F0000 <= addr <= 0x0FFFFF
    is_valid = is_rom or is_ram
    
    name = vector_names.get(i, f"Vector {i}")
    
    vectors.append({
        "index": i,
        "name": name,
        "address": f"0x{addr:08X}",
        "valid": is_valid,
        "in_rom": is_rom,
    })
    
    if i < 32 or (is_valid and i < 64):
        marker = " [ROM]" if is_rom else (" [RAM]" if is_ram else "")
        code_str = ""
        if is_rom and addr + 16 <= len(rom):
            code_bytes = rom[addr:addr+16]
            code_str = "  " + " ".join(f"{b:02X}" for b in code_bytes)
        print(f"  Vec {i:3d} (0x{offset:02X}): 0x{addr:08X}  {name}{marker}{code_str}")

# Save vector table
vector_path = os.path.join(OUT_DIR, "vector_table.json")
with open(vector_path, "w") as f:
    json.dump(vectors, f, indent=2)
print(f"\nVector table saved to: {vector_path}")

# Known addresses from MAME
print()
print("=" * 70)
print("KNOWN ADDRESSES FROM MAME SOURCE")
print("=" * 70)

known = [
    ("C-Chip shared RAM", 0x900000, "C-Chip"),
    ("C-Chip ASIC regs", 0x900800, "C-Chip"),
    ("Sound command", 0x800001, "Sound"),
    ("Sound status", 0x800003, "Sound"),
    ("DIP switches", 0x500000, "I/O"),
    ("Palette RAM", 0x0B0000, "Palette"),
    ("Video attr RAM", 0x0D0000, "Video"),
    ("Sprite/tile RAM", 0x0E0000, "Sprites"),
    ("Object RAM bank 2", 0x0E2000, "Sprites"),
    ("Work RAM", 0x0F0000, "RAM"),
    ("Region storage", 0x07FFFE, "ROM"),
    ("Level 1 boss diff.", 0xF00A76, "RAM"),
]

for name, addr, region in known:
    print(f"  {name:30s}: 0x{addr:06X} ({region})")

# Analyze code at key vectors
print()
print("=" * 70)
print("CODE AT KEY VECTORS")
print("=" * 70)

key_vecs = [
    (1, "Reset"),
    (2, "Bus Error"),
    (3, "Address Error"),
    (4, "Illegal Instruction"),
    (25, "IRQ Level 1"),
    (26, "IRQ Level 2"),
    (30, "IRQ Level 6 (main)"),
    (31, "IRQ Level 7"),
]

for vec_num, desc in key_vecs:
    addr = struct.unpack(">I", rom[vec_num*4:vec_num*4+4])[0]
    
    if addr < len(rom) - 32:
        print(f"\n  Vector {vec_num} ({desc}): handler at 0x{addr:06X}")
        code = rom[addr:addr+48]
        for i in range(0, 48, 16):
            hex_str = " ".join(f"{b:02X}" for b in code[i:i+16])
            print(f"    0x{addr+i:06X}: {hex_str}")
        
        # Basic instruction decode
        print(f"    Instructions:")
        pc = addr
        for _ in range(6):
            if pc + 2 > len(rom):
                break
            op = struct.unpack(">H", rom[pc:pc+2])[0]
            decoded = decode_68k_op(rom, pc, op)
            if decoded:
                print(f"      0x{pc:06X}: {decoded}")
                pc += decoded[1]
            else:
                print(f"      0x{pc:06X}: ??? (0x{op:04X})")
                pc += 2
    else:
        print(f"\n  Vector {vec_num} ({desc}): 0x{addr:08X} (outside ROM)")

# Generate Peony entry point file
print()
print("=" * 70)
print("PEONY ENTRY POINTS (for CDL or manual)")
print("=" * 70)

entry_path = os.path.join(OUT_DIR, "entry_points.txt")
with open(entry_path, "w") as f:
    f.write("; Superman 68K Entry Points\n")
    f.write("; Generated from vector table analysis\n\n")
    
    for v in vectors:
        if v["in_rom"] and v["index"] > 1:
            addr = int(v["address"], 16)
            f.write(f"0x{addr:06X}  ; Vector {v['index']}: {v['name']}\n")
    
    # Also add known MAME addresses
    f.write("\n; Known addresses from MAME source\n")
    for name, addr, region in known:
        if addr < len(rom):
            f.write(f"0x{addr:06X}  ; {name} ({region})\n")

print(f"Entry points saved to: {entry_path}")


def decode_68k_op(rom, pc, op):
    """Decode a 68K instruction. Returns (text, size) or None."""
    
    if op == 0x4E71:
        return ("nop", 2)
    if op == 0x4E75:
        return ("rts", 2)
    if op == 0x4E73:
        return ("rte", 2)
    if op == 0x4E70:
        return ("reset", 2)
    if op == 0x4E76:
        return ("trapv", 2)
    if op == 0x4E77:
        return ("rtr", 2)
    
    # Bcc
    if (op & 0xF000) == 0x6000:
        cond = (op >> 8) & 0xF
        conds = ["ra","sr","hi","ls","cc","cs","ne","eq","vc","vs","pl","mi","ge","lt","gt","le"]
        offset = op & 0xFF
        if offset == 0:
            if pc + 4 <= len(rom):
                off = struct.unpack(">h", rom[pc+2:pc+4])[0]
                return (f"b.{conds[cond]} ${off:+d}", 4)
        elif offset == 0xFF:
            if pc + 6 <= len(rom):
                off = struct.unpack(">i", rom[pc+2:pc+6])[0]
                return (f"b.${conds[cond]} ${off:+d}", 6)
        else:
            target = pc + 2 + (offset if offset < 128 else offset - 256)
            return (f"b.{conds[cond]} 0x{target:06X}", 2)
    
    # BRA
    if (op & 0xFF00) == 0x6000:
        offset = op & 0xFF
        if offset == 0:
            if pc + 4 <= len(rom):
                off = struct.unpack(">h", rom[pc+2:pc+4])[0]
                return (f"bra.w ${off:+d}", 4)
        elif offset == 0xFF:
            if pc + 6 <= len(rom):
                off = struct.unpack(">i", rom[pc+2:pc+6])[0]
                return (f"bra.l ${off:+d}", 6)
        else:
            target = pc + 2 + (offset if offset < 128 else offset - 256)
            return (f"bra.b 0x{target:06X}", 2)
    
    # BSR
    if (op & 0xFF00) == 0x6100:
        offset = op & 0xFF
        if offset == 0:
            if pc + 4 <= len(rom):
                off = struct.unpack(">h", rom[pc+2:pc+4])[0]
                return (f"bsr.w ${off:+d}", 4)
        else:
            target = pc + 2 + (offset if offset < 128 else offset - 256)
            return (f"bsr.b 0x{target:06X}", 2)
    
    # LEA (absolute)
    if (op & 0xFFC0) == 0x41F9:
        reg = (op >> 9) & 7
        if pc + 6 <= len(rom):
            addr = struct.unpack(">I", rom[pc+2:pc+6])[0]
            return (f"lea 0x{addr:08X}, a{reg}", 6)
    
    # MOVE
    if (op & 0xF000) == 0x2000:
        reg = (op >> 9) & 7
        return (f"move.l ???, d{reg}", 2)
    if (op & 0xF000) == 0x3000:
        reg = (op >> 9) & 7
        return (f"move.w ???, d{reg}", 2)
    if (op & 0xF000) == 0x1000:
        reg = (op >> 9) & 7
        return (f"move.b ???, d{reg}", 2)
    
    # ORI to SR
    if (op & 0xFFC0) == 0x007C:
        if pc + 4 <= len(rom):
            val = struct.unpack(">H", rom[pc+2:pc+4])[0]
            return (f"ori.w #0x{val:04X}, sr", 4)
    
    # ORI to CCR
    if (op & 0xFFC0) == 0x003C:
        if pc + 4 <= len(rom):
            val = struct.unpack(">H", rom[pc+2:pc+4])[0]
            return (f"ori.b #0x{val:02X}, ccr", 4)
    
    # MOVEC
    if (op & 0xFFF8) == 0x4E78:
        return ("movec ???", 4)
    
    return None
