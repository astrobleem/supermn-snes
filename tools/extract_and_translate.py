#!/usr/bin/env python3
"""
Extract and translate key 68K functions to 5A22 PASM.
Focuses on MAIN_LOOP, PLAYER_CTRL, ENEMY_AI, and C-CHIP_CMD.
"""

import struct

ROM_PATH = "/home/chad/supermn-snes/data/superman_m68k.bin"
with open(ROM_PATH, "rb") as f:
    rom = f.read()

def rb(addr):
    addr &= 0xFFFFFF
    return rom[addr] if addr < len(rom) else 0

def rw(addr):
    return (rb(addr) << 8) | rb(addr + 1)

def rl(addr):
    return (rw(addr) << 16) | rw(addr + 2)

def sign_extend_8(val):
    val &= 0xFF
    return val - 256 if val >= 128 else val

def sign_extend_16(val):
    val &= 0xFFFF
    return val - 65536 if val >= 32768 else val

def decode_full(addr, max_instr=100):
    """Full 68K decoder with all common opcodes."""
    results = []
    pc = addr
    
    for _ in range(max_instr):
        if pc >= len(rom) - 1:
            break
        
        op = rw(pc)
        start_pc = pc
        asm = ""
        size = 2
        
        # === Control flow ===
        if op == 0x4E71: asm = "nop"; size = 2
        elif op == 0x4E75: asm = "rts"; size = 2
        elif op == 0x4E73: asm = "rte"; size = 2
        elif op == 0x4E70: asm = "reset"; size = 2
        elif op == 0x4E76: asm = "trapv"; size = 2
        elif op == 0x4E77: asm = "rtr"; size = 2
        
        # LINK An, #d16  (4E56 + reg)
        elif (op & 0xFFF8) == 0x4E56:
            an = op & 7
            offset = sign_extend_16(rw(pc + 2))
            asm = "link a%d, #%d" % (an, offset)
            size = 4
        
        # UNLK An  (4E5E + reg)
        elif (op & 0xFFF8) == 0x4E5E:
            an = op & 7
            asm = "unlk a%d" % an
            size = 2
        
        # MOVEM.L reglist, -(An)  (48E7 + reglist)
        elif (op & 0xFF00) == 0x4800 and (op & 0x00C0) == 0x00C0:
            reglist = rw(pc + 2)
            an = op & 7
            regs = []
            for i in range(16):
                if reglist & (1 << i):
                    regs.append("d%d" % i if i < 8 else "a%d" % (i - 8))
            asm = "movem.l %s, -(a%d)" % ("/".join(regs), an)
            size = 4
        
        # MOVEM.L (An)+, reglist  (4CDF + reglist)
        elif (op & 0xFF00) == 0x4C00 and (op & 0x00C0) == 0x00C0:
            reglist = rw(pc + 2)
            an = op & 7
            regs = []
            for i in range(15, -1, -1):
                if reglist & (1 << i):
                    regs.append("d%d" % i if i < 8 else "a%d" % (i - 8))
            asm = "movem.l (a%d)+, %s" % (an, "/".join(regs))
            size = 4
        
        # MOVE.W #imm, abs.l  (33FC)
        elif op == 0x33FC:
            imm = rw(pc + 2)
            target = rl(pc + 4)
            asm = "move.w #$%04X, $%06X" % (imm, target)
            size = 8
        
        # MOVE.L #imm, abs.l  (23FC)
        elif op == 0x23FC:
            imm = rl(pc + 2)
            target = rl(pc + 6)
            asm = "move.l #$%08X, $%06X" % (imm, target)
            size = 10
        
        # MOVE.B #imm, abs.l  (13FC)
        elif op == 0x13FC:
            imm = rb(pc + 2)
            target = rl(pc + 4)
            asm = "move.b #$%02X, $%06X" % (imm, target)
            size = 8
        
        # MOVE.L Dn, abs.l  (23C0 + reg)
        elif (op & 0xF1FF) == 0x23C0:
            dn = (op >> 9) & 7
            target = rl(pc + 2)
            asm = "move.l d%d, $%06X" % (dn, target)
            size = 6
        
        # MOVE.W Dn, abs.l  (33C0 + reg)
        elif (op & 0xF1FF) == 0x33C0:
            dn = (op >> 9) & 7
            target = rl(pc + 2)
            asm = "move.w d%d, $%06X" % (dn, target)
            size = 6
        
        # MOVE.B Dn, abs.l  (13C0 + reg)
        elif (op & 0xF1FF) == 0x13C0:
            dn = (op >> 9) & 7
            target = rl(pc + 2)
            asm = "move.b d%d, $%06X" % (dn, target)
            size = 6
        
        # MOVE.B abs.l, Dn  (1039 + reg)
        elif (op & 0xF1FF) == 0x1039:
            dn = (op >> 9) & 7
            target = rl(pc + 2)
            asm = "move.b $%06X, d%d" % (target, dn)
            size = 6
        
        # MOVE.W abs.l, Dn  (3039 + reg)
        elif (op & 0xF1FF) == 0x3039:
            dn = (op >> 9) & 7
            target = rl(pc + 2)
            asm = "move.w $%06X, d%d" % (target, dn)
            size = 6
        
        # MOVE.L abs.l, Dn  (2039 + reg)
        elif (op & 0xF1FF) == 0x2039:
            dn = (op >> 9) & 7
            target = rl(pc + 2)
            asm = "move.l $%06X, d%d" % (target, dn)
            size = 6
        
        # MOVE.L #imm, Dn  (203C + reg)
        elif (op & 0xF138) == 0x2038:
            dn = op & 7
            imm = rl(pc + 2)
            asm = "move.l #$%08X, d%d" % (imm, dn)
            size = 6
        
        # MOVE.W #imm, Dn  (303C + reg)
        elif (op & 0xF138) == 0x303C:
            dn = op & 7
            imm = rw(pc + 2)
            asm = "move.w #$%04X, d%d" % (imm, dn)
            size = 4
        
        # MOVE.B #imm, Dn  (103C + reg)
        elif (op & 0xF100) == 0x103C:
            dn = op & 7
            imm = rw(pc + 2) & 0xFF
            asm = "move.b #$%02X, d%d" % (imm, dn)
            size = 4
        
        # LEA abs.l, An  (41F9 + reg)
        elif (op & 0xF1C0) == 0x41F9:
            reg = (op >> 9) & 7
            target = rl(pc + 2)
            asm = "lea $%06X, a%d" % (target, reg)
            size = 6
        
        # LEA (d16, An), An  (41E8 + reg)
        elif (op & 0xF1F8) == 0x41E8:
            an = op & 7
            reg = (op >> 9) & 7
            offset = sign_extend_16(rw(pc + 2))
            asm = "lea %+d(a%d), a%d" % (offset, an, reg)
            size = 4
        
        # MOVE.B Dn, (An)  (1080 + reg)
        elif (op & 0xF1C0) == 0x1080:
            dn = (op >> 9) & 7
            an = op & 7
            asm = "move.b d%d, (a%d)" % (dn, an)
            size = 2
        
        # MOVE.B (An), Dm  (1010 + reg)
        elif (op & 0xF1F8) == 0x1010:
            an = op & 7
            dm = (op >> 9) & 7
            asm = "move.b (a%d), d%d" % (an, dm)
            size = 2
        
        # MOVE.B (An)+, Dm  (1018 + reg)
        elif (op & 0xF1F8) == 0x1018:
            an = op & 7
            dm = (op >> 9) & 7
            asm = "move.b (a%d)+, d%d" % (an, dm)
            size = 2
        
        # MOVE.B Dn, (d16, An)  (10B8 + reg)
        elif (op & 0xF1FF) == 0x10B8:
            dn = (op >> 9) & 7
            an = (op >> 3) & 7
            offset = rw(pc + 2)
            asm = "move.b d%d, $%04X(a%d)" % (dn, offset, an)
            size = 4
        
        # MOVE.B Dn, (d8, An, Xm)  (1030 + reg)
        elif (op & 0xF1C0) == 0x1030:
            dn = (op >> 9) & 7
            an = op & 7
            ext = rw(pc + 2)
            xreg = (ext >> 12) & 7
            xsize = "w" if (ext & 0x800) == 0 else "l"
            offset = sign_extend_8(ext & 0xFF)
            asm = "move.b d%d, %+d(a%d, d%d.%s)" % (dn, offset, an, xreg, xsize)
            size = 4
        
        # MOVE.W Dn, (d8, An, Xm)  (3030 + reg)
        elif (op & 0xF1C0) == 0x3030:
            dn = (op >> 9) & 7
            an = op & 7
            ext = rw(pc + 2)
            xreg = (ext >> 12) & 7
            xsize = "w" if (ext & 0x800) == 0 else "l"
            offset = sign_extend_8(ext & 0xFF)
            asm = "move.w d%d, %+d(a%d, d%d.%s)" % (dn, offset, an, xreg, xsize)
            size = 4
        
        # MOVE.L Dn, (d8, An, Xm)  (2030 + reg)
        elif (op & 0xF1C0) == 0x2030:
            dn = (op >> 9) & 7
            an = op & 7
            ext = rw(pc + 2)
            xreg = (ext >> 12) & 7
            xsize = "w" if (ext & 0x800) == 0 else "l"
            offset = sign_extend_8(ext & 0xFF)
            asm = "move.l d%d, %+d(a%d, d%d.%s)" % (dn, offset, an, xreg, xsize)
            size = 4
        
        # CLR.W Dn  (4240 + reg)
        elif (op & 0xFFF8) == 0x4240:
            dn = op & 7
            asm = "clr.w d%d" % dn
            size = 2
        
        # CLR.B Dn  (4200 + reg)
        elif (op & 0xFFF8) == 0x4200:
            dn = op & 7
            asm = "clr.b d%d" % dn
            size = 2
        
        # CLR.B (An)  (4210 + reg)
        elif (op & 0xFFF8) == 0x4210:
            an = op & 7
            asm = "clr.b (a%d)" % an
            size = 2
        
        # ORI.W #imm, SR  (007C)
        elif op == 0x007C:
            imm = rw(pc + 2)
            asm = "ori.w #$%04X, sr" % imm
            size = 4
        
        # ANDI.W #imm, SR  (027C)
        elif op == 0x027C:
            imm = rw(pc + 2)
            asm = "andi.w #$%04X, sr" % imm
            size = 4
        
        # BSR
        elif (op & 0xFF00) == 0x6100:
            offset = op & 0xFF
            if offset == 0:
                offset = sign_extend_16(rw(pc + 2))
                target = (pc + 2 + offset) & 0xFFFFFF
                asm = "bsr.w $%06X" % target
                size = 4
            else:
                offset = sign_extend_8(offset)
                target = (pc + 2 + offset) & 0xFFFFFF
                asm = "bsr.b $%06X" % target
                size = 2
        
        # BRA
        elif (op & 0xFF00) == 0x6000:
            offset = op & 0xFF
            if offset == 0:
                offset = sign_extend_16(rw(pc + 2))
                target = (pc + 2 + offset) & 0xFFFFFF
                asm = "bra.w $%06X" % target
                size = 4
            else:
                offset = sign_extend_8(offset)
                target = (pc + 2 + offset) & 0xFFFFFF
                asm = "bra.b $%06X" % target
                size = 2
        
        # BNE
        elif (op & 0xFF00) == 0x6600:
            offset = op & 0xFF
            if offset == 0:
                offset = sign_extend_16(rw(pc + 2))
                target = (pc + 2 + offset) & 0xFFFFFF
                asm = "bne.w $%06X" % target
                size = 4
            else:
                offset = sign_extend_8(offset)
                target = (pc + 2 + offset) & 0xFFFFFF
                asm = "bne.b $%06X" % target
                size = 2
        
        # BEQ
        elif (op & 0xFF00) == 0x6700:
            offset = op & 0xFF
            if offset == 0:
                offset = sign_extend_16(rw(pc + 2))
                target = (pc + 2 + offset) & 0xFFFFFF
                asm = "beq.w $%06X" % target
                size = 4
            else:
                offset = sign_extend_8(offset)
                target = (pc + 2 + offset) & 0xFFFFFF
                asm = "beq.b $%06X" % target
                size = 2
        
        # BGT
        elif (op & 0xFF00) == 0x6E00:
            offset = op & 0xFF
            if offset == 0:
                offset = sign_extend_16(rw(pc + 2))
                target = (pc + 2 + offset) & 0xFFFFFF
                asm = "bgt.w $%06X" % target
                size = 4
            else:
                offset = sign_extend_8(offset)
                target = (pc + 2 + offset) & 0xFFFFFF
                asm = "bgt.b $%06X" % target
                size = 2
        
        # BLT
        elif (op & 0xFF00) == 0x6C00:
            offset = op & 0xFF
            if offset == 0:
                offset = sign_extend_16(rw(pc + 2))
                target = (pc + 2 + offset) & 0xFFFFFF
                asm = "blt.w $%06X" % target
                size = 4
            else:
                offset = sign_extend_8(offset)
                target = (pc + 2 + offset) & 0xFFFFFF
                asm = "blt.b $%06X" % target
                size = 2
        
        # BGE
        elif (op & 0xFF00) == 0x6C00:
            offset = op & 0xFF
            if offset == 0:
                offset = sign_extend_16(rw(pc + 2))
                target = (pc + 2 + offset) & 0xFFFFFF
                asm = "bge.w $%06X" % target
                size = 4
            else:
                offset = sign_extend_8(offset)
                target = (pc + 2 + offset) & 0xFFFFFF
                asm = "bge.b $%06X" % target
                size = 2
        
        # BLE
        elif (op & 0xFF00) == 0x6F00:
            offset = op & 0xFF
            if offset == 0:
                offset = sign_extend_16(rw(pc + 2))
                target = (pc + 2 + offset) & 0xFFFFFF
                asm = "ble.w $%06X" % target
                size = 4
            else:
                offset = sign_extend_8(offset)
                target = (pc + 2 + offset) & 0xFFFFFF
                asm = "ble.b $%06X" % target
                size = 2
        
        # BTST #bit, abs.l  (0839)
        elif op == 0x0839:
            bit = rw(pc + 2)
            target = rl(pc + 4)
            asm = "btst #%d, $%06X" % (bit, target)
            size = 8
        
        # CMPI.B #imm, abs.l  (0C39)
        elif (op & 0xFFC0) == 0x0C39:
            imm = rw(pc + 2) & 0xFF
            target = rl(pc + 4)
            asm = "cmpi.b #$%02X, $%06X" % (imm, target)
            size = 8
        
        # CMPI.B #imm, Dn  (0C00 + reg)
        elif (op & 0xFFC0) == 0x0C00:
            imm = rw(pc + 2) & 0xFF
            dn = (op >> 9) & 7
            asm = "cmpi.b #$%02X, d%d" % (imm, dn)
            size = 4
        
        # CMPI.W #imm, Dn  (0C40 + reg)
        elif (op & 0xFFC0) == 0x0C40:
            imm = rw(pc + 2)
            dn = (op >> 9) & 7
            asm = "cmpi.w #$%04X, d%d" % (imm, dn)
            size = 4
        
        # CMPI.L #imm, Dn  (0C80 + reg)
        elif (op & 0xFFC0) == 0x0C80:
            imm = rl(pc + 2)
            dn = (op >> 9) & 7
            asm = "cmpi.l #$%08X, d%d" % (imm, dn)
            size = 6
        
        # ADDA.L #imm, SP  (DFFC)
        elif op == 0xDFFC:
            imm = rl(pc + 2)
            asm = "adda.l #$%08X, sp" % imm
            size = 6
        
        # ADDQ.B #imm, Dn  (5000 + reg)
        elif (op & 0xF1F8) == 0x5000:
            imm = (op >> 9) & 7
            if imm == 0: imm = 8
            dn = op & 7
            asm = "addq.b #%d, d%d" % (imm, dn)
            size = 2
        
        # SUBQ.B #imm, Dn  (5100 + reg)
        elif (op & 0xF1F8) == 0x5100:
            imm = (op >> 9) & 7
            if imm == 0: imm = 8
            dn = op & 7
            asm = "subq.b #%d, d%d" % (imm, dn)
            size = 2
        
        # ADDQ.W #imm, Dn  (5040 + reg)
        elif (op & 0xF1F8) == 0x5040:
            imm = (op >> 9) & 7
            if imm == 0: imm = 8
            dn = op & 7
            asm = "addq.w #%d, d%d" % (imm, dn)
            size = 2
        
        # SUBQ.W #imm, Dn  (5140 + reg)
        elif (op & 0xF1F8) == 0x5140:
            imm = (op >> 9) & 7
            if imm == 0: imm = 8
            dn = op & 7
            asm = "subq.w #%d, d%d" % (imm, dn)
            size = 2
        
        # DBRA Dn, target  (51C8 + reg)
        elif (op & 0xFFF8) == 0x51C8:
            dn = op & 7
            offset = sign_extend_16(rw(pc + 2))
            target = (pc + 2 + offset) & 0xFFFFFF
            asm = "dbra d%d, $%06X" % (dn, target)
            size = 4
        
        # JSR (d16, PC)  (4EBA)
        elif op == 0x4EBA:
            offset = sign_extend_16(rw(pc + 2))
            target = (pc + 2 + offset) & 0xFFFFFF
            asm = "jsr $%06X" % target
            size = 4
        
        # JSR abs.l  (4EB9)
        elif op == 0x4EB9:
            target = rl(pc + 2)
            asm = "jsr $%06X" % target
            size = 6
        
        # JSR (An)  (4E90 + reg)
        elif (op & 0xFFC0) == 0x4E90:
            an = op & 7
            asm = "jsr (a%d)" % an
            size = 2
        
        # AND.L Dn, Dm  (C080 + reg)
        elif (op & 0xF1F8) == 0xC080:
            dn = (op >> 9) & 7
            dm = op & 7
            asm = "and.l d%d, d%d" % (dn, dm)
            size = 2
        
        # OR.L Dn, Dm  (8080 + reg)
        elif (op & 0xF1F8) == 0x8080:
            dn = (op >> 9) & 7
            dm = op & 7
            asm = "or.l d%d, d%d" % (dn, dm)
            size = 2
        
        # EOR.L Dn, Dm  (B180 + reg)
        elif (op & 0xF1F8) == 0xB180:
            dn = (op >> 9) & 7
            dm = op & 7
            asm = "eor.l d%d, d%d" % (dn, dm)
            size = 2
        
        # MULS.W Dn, Dm  (C1C0 + reg)
        elif (op & 0xF1F8) == 0xC1C0:
            dn = (op >> 9) & 7
            dm = op & 7
            asm = "muls.w d%d, d%d" % (dn, dm)
            size = 2
        
        # MULU.W Dn, Dm  (C0C0 + reg)
        elif (op & 0xF1F8) == 0xC0C0:
            dn = (op >> 9) & 7
            dm = op & 7
            asm = "mulu.w d%d, d%d" % (dn, dm)
            size = 2
        
        # DIVS.W Dn, Dm  (81C0 + reg)
        elif (op & 0xF1F8) == 0x81C0:
            dn = (op >> 9) & 7
            dm = op & 7
            asm = "divs.w d%d, d%d" % (dn, dm)
            size = 2
        
        # DIVU.W Dn, Dm  (80C0 + reg)
        elif (op & 0xF1F8) == 0x80C0:
            dn = (op >> 9) & 7
            dm = op & 7
            asm = "divu.w d%d, d%d" % (dn, dm)
            size = 2
        
        # ASL/ASR
        elif (op & 0xF1F8) == 0xE100:  # asl.b #1, dn
            dn = op & 7
            asm = "asl.b #1, d%d" % dn
            size = 2
        elif (op & 0xF1F8) == 0xE000:  # asr.b #1, dn
            dn = op & 7
            asm = "asr.b #1, d%d" % dn
            size = 2
        elif (op & 0xF1F8) == 0xE140:  # asl.w #1, dn
            dn = op & 7
            asm = "asl.w #1, d%d" % dn
            size = 2
        elif (op & 0xF1F8) == 0xE040:  # asr.w #1, dn
            dn = op & 7
            asm = "asr.w #1, d%d" % dn
            size = 2
        
        # LSL/LSR
        elif (op & 0xF1F8) == 0xE108:  # lsl.b #1, dn
            dn = op & 7
            asm = "lsl.b #1, d%d" % dn
            size = 2
        elif (op & 0xF1F8) == 0xE008:  # lsr.b #1, dn
            dn = op & 7
            asm = "lsr.b #1, d%d" % dn
            size = 2
        
        # ROL/ROR
        elif (op & 0xF1F8) == 0xE118:  # rol.b #1, dn
            dn = op & 7
            asm = "rol.b #1, d%d" % dn
            size = 2
        elif (op & 0xF1F8) == 0xE018:  # ror.b #1, dn
            dn = op & 7
            asm = "ror.b #1, d%d" % dn
            size = 2
        
        # BSET/BCLR/BCHG
        elif (op & 0xF1F8) == 0x01C0:  # btst dn, dm
            dn = (op >> 9) & 7
            dm = op & 7
            asm = "btst d%d, d%d" % (dn, dm)
            size = 2
        elif (op & 0xF1F8) == 0x01D0:  # bset dn, (an)
            dn = (op >> 9) & 7
            an = op & 7
            asm = "bset d%d, (a%d)" % (dn, an)
            size = 2
        elif (op & 0xF1F8) == 0x0190:  # bclr dn, (an)
            dn = (op >> 9) & 7
            an = op & 7
            asm = "bclr d%d, (a%d)" % (dn, an)
            size = 2
        elif (op & 0xF1F8) == 0x0110:  # bchg dn, (an)
            dn = (op >> 9) & 7
            an = op & 7
            asm = "bchg d%d, (a%d)" % (dn, an)
            size = 2
        
        # TST
        elif (op & 0xFFC0) == 0x4A00:  # tst.b (an)
            an = op & 7
            asm = "tst.b (a%d)" % an
            size = 2
        elif (op & 0xFFC0) == 0x4A40:  # tst.w (an)
            an = op & 7
            asm = "tst.w (a%d)" % an
            size = 2
        elif (op & 0xFFC0) == 0x4A80:  # tst.l (an)
            an = op & 7
            asm = "tst.l (a%d)" % an
            size = 2
        elif (op & 0xFFF8) == 0x4A00:  # tst.b dn
            dn = op & 7
            asm = "tst.b d%d" % dn
            size = 2
        elif (op & 0xFFF8) == 0x4A40:  # tst.w dn
            dn = op & 7
            asm = "tst.w d%d" % dn
            size = 2
        
        # MOVE to SR  (46C0 + reg)
        elif (op & 0xFFC0) == 0x46C0:
            an = op & 7
            asm = "move (a%d), sr" % an
            size = 2
        
        # STOP
        elif op == 0x4E72:
            imm = rw(pc + 2)
            asm = "stop #$%04X" % imm
            size = 4
        
        else:
            asm = "??? ($%04X)" % op
            size = 2
        
        raw = " ".join("%02X" % rb(pc + j) for j in range(min(size, 8)))
        results.append((start_pc, asm, raw, size))
        pc += size
        
        if asm in ("rts", "rte"):
            break
    
    return results

# Extract key functions
functions = {
    0x0008FA: "MAIN_LOOP",
    0x002D8A: "SOUND_DRIVER",
    0x003A92: "GAME_TICK",
    0x003E0E: "CCHIP_CMD",
    0x004A9E: "PLAYER_CTRL",
    0x024AA8: "ENEMY_AI",
    0x028F92: "COLLISION",
    0x024588: "PHYSICS",
    0x028D70: "INPUT_READ",
    0x005C5E: "SCROLL",
    0x005BE4: "SPRITE_DRAW",
    0x00091E: "INIT",
    0x000C1C: "VBLANK",
    0x000B40: "TITLE",
    0x000A90: "PAUSE",
    0x00C9F8: "LEVEL_LOAD",
    0x00DE82: "SCORE",
    0x024920: "WEAPON",
    0x02498C: "POWERUP",
    0x01242E: "DEATH",
    0x000CC0: "GAME_OVER",
    0x00C8E0: "MUSIC",
    0x00C9A6: "BOSS",
    0x00AE8E: "DIALOG",
    0x024956: "PROJECTILE",
    0x01F67E: "ANIMATE",
    0x0571EE: "GFX_RENDER",
}

print("=" * 70)
print("SUPERMAN 68K → 5A22 TRANSLATION")
print("=" * 70)

for addr, name in sorted(functions.items()):
    print(f"\n{'=' * 60}")
    print(f"; ${addr:06X}: {name}")
    print(f"{'=' * 60}")
    
    decoded = decode_full(addr, max_instr=40)
    for pc, asm, raw, size in decoded:
        # Add comments for interesting addresses
        comment = ""
        if "09000" in asm: comment = "  ; C-Chip access"
        elif "80000" in asm: comment = "  ; Sound access"
        elif "0E000" in asm: comment = "  ; Sprite RAM"
        elif "0B000" in asm: comment = "  ; Palette RAM"
        elif "0D000" in asm: comment = "  ; Video regs"
        elif "0F" in asm and "$0" in asm: comment = "  ; Work RAM"
        elif "jsr" in asm.lower() and "$" in asm and "???" not in asm:
            # Extract target
            import re
            m = re.search(r'\$([0-9A-Fa-f]{6})', asm)
            if m:
                target = int(m.group(1), 16)
                if target in functions:
                    comment = "  ; → %s" % functions[target]
        
        print(f"  ${pc:06X}: {asm:45s} {raw:24s}{comment}")
    
    print()
