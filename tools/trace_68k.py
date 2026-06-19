#!/usr/bin/env python3
"""
Simple 68K emulator to trace Superman game execution.
Focuses on identifying the main game loop and C-Chip interactions.
"""

import struct
import sys

ROM_PATH = "/home/chad/supermn-snes/data/superman_m68k.bin"
RAM_SIZE = 0x100000  # 1MB address space

# Memory
rom = bytearray(512 * 1024)
ram = bytearray(RAM_SIZE)
cchip_ram = bytearray(1024)  # C-Chip shared RAM window
cchip_bank = 0
cchip_asic = bytearray(4)  # ASIC internal RAM

with open(ROM_PATH, "rb") as f:
    rom = bytearray(f.read())

# CPU state
regs = {'d0': 0, 'd1': 0, 'd2': 0, 'd3': 0, 'd4': 0, 'd5': 0, 'd6': 0, 'd7': 0,
        'a0': 0, 'a1': 0, 'a2': 0, 'a3': 0, 'a4': 0, 'a5': 0, 'a6': 0, 'sp': 0}
pc = 0
sr = 0x2700  # Supervisor mode, interrupts enabled

# Trace log
trace = []
cchip_commands = []
sound_commands = []
frame_count = 0
max_instructions = 100000

def read_byte(addr):
    addr &= 0xFFFFFF
    if addr < len(rom):
        return rom[addr]
    elif addr < RAM_SIZE:
        return ram[addr]
    return 0

def read_word(addr):
    return (read_byte(addr) << 8) | read_byte(addr + 1)

def read_long(addr):
    return (read_word(addr) << 16) | read_word(addr + 2)

def write_byte(addr, val):
    global cchip_bank
    addr &= 0xFFFFFF
    val &= 0xFF
    
    if addr < RAM_SIZE:
        ram[addr] = val
    
    # C-Chip shared RAM window at $900000
    if 0x900000 <= addr < 0x900800:
        offset = (addr - 0x900000) + (cchip_bank * 1024)
        if offset < len(cchip_ram):
            cchip_ram[offset] = val
    
    # C-Chip ASIC registers at $900800
    if addr == 0x900800:
        cchip_bank = val & 0x07
        cchip_commands.append(('bank', val & 0x07, pc))
    elif 0x900801 <= addr <= 0x900804:
        cchip_asic[addr - 0x900801] = val
        cchip_commands.append(('asic_w', addr - 0x900801, val, pc))
    elif addr == 0x900805:
        cchip_commands.append(('cmd', val, pc))
    
    # Sound command port at $800001
    if addr == 0x800001:
        sound_commands.append(('cmd', val, pc))
    if addr == 0x800003:
        sound_commands.append(('data', val, pc))

def read_reg(name):
    return regs[name] & 0xFFFFFFFF

def write_reg(name, val):
    regs[name] = val & 0xFFFFFFFF

def decode_op(addr):
    """Basic 68K opcode decoder. Returns (mnemonic, size, target_addr)."""
    op = read_word(addr)
    
    # NOP
    if op == 0x4E71:
        return "nop", 2, None
    
    # RTS
    if op == 0x4E75:
        return "rts", 2, None
    
    # RTE
    if op == 0x4E73:
        return "rte", 2, None
    
    # MOVE.L #imm, addr
    if op == 0x23FC:  # move.l #imm, abs.l
        imm = read_long(addr + 2)
        target = read_long(addr + 6)
        return f"move.l #${imm:08x}, ${target:06x}", 10, None
    
    # MOVE.W #imm, addr
    if op == 0x21FC:  # move.w #imm3, abs.l — wait, 33fc
        pass
    
    # MOVE.B #imm, addr
    if op == 0x13FC:  # move.b #imm, abs.l
        imm = read_byte(addr + 2)
        target = read_long(addr + 4)
        return f"move.b #${imm:02x}, ${target:06x}", 8, None
    
    # MOVE.B #imm, addr (word version)
    if op == 0x33FC:  # move.w #imm, abs.l
        imm = read_word(addr + 2)
        target = read_long(addr + 4)
        return f"move.w #${imm:04x}, ${target:06x}", 8, None
    
    # BSR
    if (op & 0xFF00) == 0x6100:
        offset = op & 0xFF
        if offset == 0:
            offset = read_word(addr + 2)
            if offset >= 0x8000:
                offset -= 0x10000
            return f"bsr.w ${offset:+d}", 4, (addr + 2 + offset) & 0xFFFFFF
        else:
            if offset >= 128:
                offset -= 256
            return f"bsr.b ${offset:+d}", 2, (addr + 2 + offset) & 0xFFFFFF
    
    # BRA
    if (op & 0xFF00) == 0x6000:
        offset = op & 0xFF
        if offset == 0:
            offset = read_word(addr + 2)
            if offset >= 0x8000:
                offset -= 0x10000
            return f"bra.w ${offset:+d}", 4, (addr + 2 + offset) & 0xFFFFFF
        else:
            if offset >= 128:
                offset -= 256
            return f"bra.b ${offset:+d}", 2, (addr + 2 + offset) & 0xFFFFFF
    
    # Bcc
    if (op & 0xF000) == 0x6000:
        cond = (op >> 8) & 0xF
        conds = ["ra","sr","hi","ls","cc","cs","ne","eq","vc","vs","pl","mi","ge","lt","gt","le"]
        offset = op & 0xFF
        if offset == 0:
            offset = read_word(addr + 2)
            if offset >= 0x8000:
                offset -= 0x10000
            return f"b.{conds[cond]}.w ${offset:+d}", 4, (addr + 2 + offset) & 0xFFFFFF
        elif offset == 0xFF:
            offset = read_long(addr + 2)
            if offset >= 0x800000:
                offset -= 0x1000000
            return f"b.{conds[cond]}.l ${offset:+d}", 6, (addr + 2 + offset) & 0xFFFFFF
        else:
            if offset >= 128:
                offset -= 256
            return f"b.{conds[cond]}.b ${offset:+d}", 2, (addr + 2 + offset) & 0xFFFFFF
    
    # JSR abs.l
    if op == 0x4EB9:
        target = read_long(addr + 2)
        return f"jsr ${target:06x}", 6, target
    
    # JSR (addr)
    if (op & 0xFFC0) == 0x4E90:
        reg = (op >> 3) & 7
        regs_list = ['a0','a1','a2','a3','a4','a5','a6','a7']
        return f"jsr ({regs_list[reg]})", 2, None
    
    # BTST #bit, abs.l
    if op == 0x0839:
        bit = read_word(addr + 2)
        target = read_long(addr + 4)
        return f"btst #{bit}, ${target:06x}", 8, None
    
    # ORI.B #imm, abs.l
    if (op & 0xFF00) == 0x0000 and (op & 0x00C0) == 0x00C0:
        imm = read_word(addr + 2) & 0xFF
        target = read_long(addr + 4)
        return f"ori.b #${imm:02x}, ${target:06x}", 8, None
    
    # CMPI.B #imm, abs.l
    if (op & 0xFF00) == 0x0C00 and (op & 0x00C0) == 0x00C0:
        imm = read_word(addr + 2) & 0xFF
        target = read_long(addr + 4)
        return f"cmpi.b #${imm:02x}, ${target:06x}", 8, None
    
    # LEA abs.l, An
    if (op & 0xF1C0) == 0x41F9:
        reg = (op >> 9) & 7
        target = read_long(addr + 2)
        return f"lea ${target:06x}, a{reg}", 6, None
    
    # MOVE.B Dn, (An)
    if (op & 0xF1C0) == 0x1080:
        dn = (op >> 9) & 7
        an = op & 7
        return f"move.b d{dn}, (a{an})", 2, None
    
    # MOVE.B (An), Dn
    if (op & 0xF1C0) == 0x1010:
        an = op & 7
        dn = (op >> 9) & 7
        return f"move.b (a{an}), d{dn}", 2, None
    
    # MOVE.B abs.l, Dn
    if (op & 0xF1FF) == 0x1039:
        dn = (op >> 9) & 7
        target = read_long(addr + 2)
        return f"move.b ${target:06x}, d{dn}", 6, None
    
    # ADDA.L #imm, SP
    if op == 0xDFFC:
        imm = read_long(addr + 2)
        return f"adda.l #${imm:08x}, sp", 6, None
    
    # MOVE.L Dn, abs.l
    if (op & 0xF1FF) == 0x23C0:
        dn = (op >> 9) & 7
        target = read_long(addr + 2)
        return f"move.l d{dn}, ${target:06x}", 6, None
    
    return f"??? (${op:04x})", 2, None

# Initialize CPU
sp = read_long(0)  # Initial SP from vector 0
pc = read_long(4)  # Initial PC from vector 1
write_reg('sp', sp)

print(f"Initial SP: ${sp:08X}")
print(f"Initial PC: ${pc:08X}")
print(f"ROM size: {len(rom)} bytes")
print()

# Run emulation
for i in range(max_instructions):
    if pc >= len(rom):
        print(f"PC out of ROM: ${pc:08X}")
        break
    
    instr, size, target = decode_op(pc)
    
    # Log interesting instructions
    is_interesting = False
    log_line = f"${pc:08X}: {instr}"
    
    # C-Chip accesses
    if '09000' in instr or '09080' in instr:
        is_interesting = True
        log_line += " [C-CHIP]"
    
    # Sound accesses
    if '80000' in instr:
        is_interesting = True
        log_line += " [SOUND]"
    
    # JSR to interesting addresses
    if target is not None:
        if target >= 0x3A00 and target < 0x4000:
            is_interesting = True
            log_line += " [GAME LOGIC]"
        if target >= 0x2D00 and target < 0x2F00:
            is_interesting = True
            log_line += " [SOUND/GFX]"
    
    # Frame counter writes
    if '300000' in instr or '400000' in instr or '600000' in instr:
        is_interesting = True
        log_line += " [FRAME]"
    
    if is_interesting and len(trace) < 200:
        trace.append(log_line)
    
    # Execute the instruction (simplified)
    if instr == "nop":
        pc += 2
    elif instr == "rts":
        sp_val = read_reg('sp')
        new_pc = read_long(sp_val)
        write_reg('sp', sp_val + 4)
        pc = new_pc
    elif instr == "rte":
        sp_val = read_reg('sp')
        new_pc = read_long(sp_val)
        write_reg('sp', sp_val + 4)
        pc = new_pc
    elif instr.startswith("bsr"):
        sp_val = read_reg('sp')
        write_long(sp_val - 4, pc + size)
        write_reg('sp', sp_val - 4)
        if target is not None:
            pc = target
        else:
            pc += size
    elif instr.startswith("bra"):
        if target is not None:
            pc = target
        else:
            pc += size
    elif instr.startswith("jsr"):
        sp_val = read_reg('sp')
        write_long(sp_val - 4, pc + size)
        write_reg('sp', sp_val - 4)
        if target is not None:
            pc = target
        else:
            pc += size
    elif instr.startswith("b."):
        # Branch instructions - for now, just follow the branch
        if target is not None:
            pc = target
        else:
            pc += size
    else:
        pc += size
    
    # Safety check
    if pc == 0 or pc >= 0x1000000:
        print(f"PC out of range: ${pc:08X}")
        break

print(f"Executed {i+1} instructions")
print(f"Final PC: ${pc:08X}")
print()

# Print trace
print("=" * 70)
print("INTERESTING INSTRUCTIONS TRACE")
print("=" * 70)
for line in trace[:100]:
    print(line)

# Print C-Chip commands
print(f"\n\nC-Chip commands: {len(cchip_commands)}")
for cmd in cchip_commands[:20]:
    print(f"  {cmd}")

# Print sound commands
print(f"\n\nSound commands: {len(sound_commands)}")
for cmd in sound_commands[:20]:
    print(f"  {cmd}")

def write_long(addr, val):
    addr &= 0xFFFFFF
    if addr + 3 < RAM_SIZE:
        ram[addr] = (val >> 24) & 0xFF
        ram[addr + 1] = (val >> 16) & 0xFF
        ram[addr + 2] = (val >> 8) & 0xFF
        ram[addr + 3] = val & 0xFF
