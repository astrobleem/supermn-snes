#!/usr/bin/env python3
"""
Enhanced trace of Superman game logic.
Focuses on the key functions identified by JSR frequency analysis.
"""

import struct

ROM_PATH = "/home/chad/supermn-snes/data/superman_m68k.bin"
with open(ROM_PATH, "rb") as f:
    rom = f.read()

def rb(addr): return rom[addr & 0xFFFFFF] if (addr & 0xFFFFFF) < len(rom) else 0
def rw(addr): return (rb(addr) << 8) | rb(addr + 1)
def rl(addr): return (rw(addr) << 16) | rw(addr + 2)

def decode(addr):
    """Enhanced 68K decoder."""
    op = rw(addr)
    
    # Common patterns
    if op == 0x4E71: return "nop", 2
    if op == 0x4E75: return "rts", 2
    if op == 0x4E73: return "rte", 2
    if op == 0x4E70: return "reset", 2
    
    # MOVE.W #imm, abs.l  (33FC)
    if op == 0x33FC:
        imm = rw(addr + 2)
        target = rl(addr + 4)
        return "move.w #$%04X, $%06X" % (imm, target), 8
    
    # MOVE.L #imm, abs.l  (23FC)
    if op == 0x23FC:
        imm = rl(addr + 2)
        target = rl(addr + 6)
        return "move.l #$%08X, $%06X" % (imm, target), 10
    
    # MOVE.L Dn, abs.l  (23C0 + reg)
    if (op & 0xF1FF) == 0x23C0:
        dn = (op >> 9) & 7
        target = rl(addr + 2)
        return "move.l d%d, $%06X" % (dn, target), 6
    
    # MOVE.B #imm, abs.l  (13FC)
    if op == 0x13FC:
        imm = rb(addr + 2)
        target = rl(addr + 4)
        return "move.b #$%02X, $%06X" % (imm, target), 8
    
    # LEA abs.l, An  (41F9 + reg)
    if (op & 0xF1C0) == 0x41F9:
        reg = (op >> 9) & 7
        target = rl(addr + 2)
        return "lea $%06X, a%d" % (target, reg), 6
    
    # MOVE.B abs.l, Dn  (1039 + reg)
    if (op & 0xF1FF) == 0x1039:
        dn = (op >> 9) & 7
        target = rl(addr + 2)
        return "move.b $%06X, d%d" % (target, dn), 6
    
    # MOVE.L abs.l, Dn  (2039 + reg)
    if (op & 0xF1FF) == 0x2039:
        dn = (op >> 9) & 7
        target = rl(addr + 2)
        return "move.l $%06X, d%d" % (target, dn), 6
    
    # MOVE.L #imm, Dn  (203C + reg)
    if (op & 0xF138) == 0x2038:
        dn = op & 7
        imm = rl(addr + 2)
        return "move.l #$%08X, d%d" % (imm, dn), 6
    
    # MOVE.W #imm, Dn  (303C + reg)
    if (op & 0xF138) == 0x303C:
        dn = op & 7
        imm = rw(addr + 2)
        return "move.w #$%04X, d%d" % (imm, dn), 4
    
    # MOVE.B #imm, Dn  (103C + reg)
    if (op & 0xF100) == 0x103C:
        dn = op & 7
        imm = rw(addr + 2) & 0xFF
        return "move.b #$%02X, d%d" % (imm, dn), 4
    
    # MOVEM.L reglist, -(An)  (48E7 + reglist)
    if (op & 0xFF00) == 0x4800 and (op & 0x00C0) == 0x00C0:
        reglist = rw(addr + 2)
        regs = []
        for i in range(16):
            if reglist & (1 << i):
                if i < 8:
                    regs.append("d%d" % i)
                else:
                    regs.append("a%d" % (i - 8))
        an = op & 7
        return "movem.l %s, -(a%d)" % ("/".join(regs), an), 4
    
    # MOVEM.L (An)+, reglist  (4CDF + reglist)
    if (op & 0xFF00) == 0x4C00 and (op & 0x00C0) == 0x00C0:
        reglist = rw(addr + 2)
        regs = []
        for i in range(15, -1, -1):
            if reglist & (1 << i):
                if i < 8:
                    regs.append("d%d" % i)
                else:
                    regs.append("a%d" % (i - 8))
        an = op & 7
        return "movem.l (a%d)+, %s" % (an, "/".join(regs)), 4
    
    # ORI.W #imm, SR  (007C)
    if op == 0x007C:
        imm = rw(addr + 2)
        return "ori.w #$%04X, sr" % imm, 4
    
    # ANDI.W #imm, SR  (027C)
    if op == 0x027C:
        imm = rw(addr + 2)
        return "andi.w #$%04X, sr" % imm, 4
    
    # BSR
    if (op & 0xFF00) == 0x6100:
        offset = op & 0xFF
        if offset == 0:
            offset = rw(addr + 2)
            if offset >= 0x8000: offset -= 0x10000
            return "bsr.w $%06X" % ((addr + 2 + offset) & 0xFFFFFF), 4
        else:
            if offset >= 128: offset -= 256
            return "bsr.b $%06X" % ((addr + 2 + offset) & 0xFFFFFF), 2
    
    # BRA
    if (op & 0xFF00) == 0x6000:
        offset = op & 0xFF
        if offset == 0:
            offset = rw(addr + 2)
            if offset >= 0x8000: offset -= 0x10000
            return "bra.w $%06X" % ((addr + 2 + offset) & 0xFFFFFF), 4
        else:
            if offset >= 128: offset -= 256
            return "bra.b $%06X" % ((addr + 2 + offset) & 0xFFFFFF), 2
    
    # BNE
    if (op & 0xFF00) == 0x6600:
        offset = op & 0xFF
        if offset == 0:
            offset = rw(addr + 2)
            if offset >= 0x8000: offset -= 0x10000
            return "bne.w $%06X" % ((addr + 2 + offset) & 0xFFFFFF), 4
        else:
            if offset >= 128: offset -= 256
            return "bne.b $%06X" % ((addr + 2 + offset) & 0xFFFFFF), 2
    
    # BEQ
    if (op & 0xFF00) == 0x6700:
        offset = op & 0xFF
        if offset == 0:
            offset = rw(addr + 2)
            if offset >= 0x8000: offset -= 0x10000
            return "beq.w $%06X" % ((addr + 2 + offset) & 0xFFFFFF), 4
        else:
            if offset >= 128: offset -= 256
            return "beq.b $%06X" % ((addr + 2 + offset) & 0xFFFFFF), 2
    
    # BTST #bit, abs.l  (0839)
    if op == 0x0839:
        bit = rw(addr + 2)
        target = rl(addr + 4)
        return "btst #%d, $%06X" % (bit, target), 8
    
    # CMPI.B #imm, abs.l  (0C39)
    if (op & 0xFFC0) == 0x0C39:
        imm = rw(addr + 2) & 0xFF
        target = rl(addr + 4)
        return "cmpi.b #$%02X, $%06X" % (imm, target), 8
    
    # CMPI.B #imm, Dn  (0C00 + reg)
    if (op & 0xFFC0) == 0x0C00:
        imm = rw(addr + 2) & 0xFF
        dn = (op >> 9) & 7
        return "cmpi.b #$%02X, d%d" % (imm, dn), 4
    
    # CMPI.W #imm, Dn  (0C40 + reg)
    if (op & 0xFFC0) == 0x0C40:
        imm = rw(addr + 2)
        dn = (op >> 9) & 7
        return "cmpi.w #$%04X, d%d" % (imm, dn), 4
    
    # ADDA.L #imm, SP  (DFFC)
    if op == 0xDFFC:
        imm = rl(addr + 2)
        return "adda.l #$%08X, sp" % imm, 6
    
    # CLR.W Dn  (4240 + reg)
    if (op & 0xFFF8) == 0x4240:
        dn = op & 7
        return "clr.w d%d" % dn, 2
    
    # CLR.B (An)  (4210 + reg)
    if (op & 0xFFF8) == 0x4210:
        an = op & 7
        return "clr.b (a%d)" % an, 2
    
    # MOVE.B Dn, (An)  (1080 + reg)
    if (op & 0xF1C0) == 0x1080:
        dn = (op >> 9) & 7
        an = op & 7
        return "move.b d%d, (a%d)" % (dn, an), 2
    
    # MOVE.B (An)+, Dm  (1018 + reg)
    if (op & 0xF1F8) == 0x1018:
        an = op & 7
        dm = (op >> 9) & 7
        return "move.b (a%d)+, d%d" % (an, dm), 2
    
    # MOVE.B Dn, (d16, An)  (10B8 + reg)
    if (op & 0xF1FF) == 0x10B8:
        dn = (op >> 9) & 7
        an = (op >> 3) & 7
        offset = rw(addr + 2)
        return "move.b d%d, $%04X(a%d)" % (dn, offset, an), 4
    
    # MOVE.B Dn, (d8, An, Xm)  (1030 + reg)
    if (op & 0xF1C0) == 0x1030:
        dn = (op >> 9) & 7
        an = op & 7
        ext = rw(addr + 2)
        xreg = (ext >> 12) & 7
        xsize = "w" if (ext & 0x800) == 0 else "l"
        offset = ext & 0xFF
        if offset >= 128: offset -= 256
        return "move.b d%d, %+d(a%d, d%d.%s)" % (dn, offset, an, xreg, xsize), 4
    
    # JSR (d16, PC)  (4EBA)
    if op == 0x4EBA:
        offset = rw(addr + 2)
        if offset >= 0x8000: offset -= 0x10000
        target = (addr + 2 + offset) & 0xFFFFFF
        return "jsr $%06X" % target, 4
    
    # JSR abs.l  (4EB9)
    if op == 0x4EB9:
        target = rl(addr + 2)
        return "jsr $%06X" % target, 6
    
    # JSR (An)  (4E90 + reg)
    if (op & 0xFFC0) == 0x4E90:
        an = op & 7
        return "jsr (a%d)" % an, 2
    
    # ADDQ.B #imm, Dn  (5000 + reg)
    if (op & 0xF1F8) == 0x5000:
        imm = (op >> 9) & 7
        if imm == 0: imm = 8
        dn = op & 7
        return "addq.b #%d, d%d" % (imm, dn), 2
    
    # SUBQ.B #imm, Dn  (5100 + reg)
    if (op & 0xF1F8) == 0x5100:
        imm = (op >> 9) & 7
        if imm == 0: imm = 8
        dn = op & 7
        return "subq.b #%d, d%d" % (imm, dn), 2
    
    # DBRA Dn, target  (51C8 + reg)
    if (op & 0xFFF8) == 0x51C8:
        dn = op & 7
        offset = rw(addr + 2)
        if offset >= 0x8000: offset -= 0x10000
        return "dbra d%d, $%06X" % (dn, (addr + 2 + offset) & 0xFFFFFF), 4
    
    # MOVE.B (An), Dm  (1010 + reg)
    if (op & 0xF1F8) == 0x1010:
        an = op & 7
        dm = (op >> 9) & 7
        return "move.b (a%d), d%d" % (an, dm), 2
    
    return "??? ($%04X)" % op, 2

# Key functions to trace (from JSR frequency analysis)
key_functions = {
    0x0008FA: "MAIN_LOOP (34 refs)",      # Most referenced - main game loop
    0x002D8A: "SOUND_DRIVER (29 refs)",    # Sound driver
    0x0571EE: "GFX_RENDER (10 refs)",      # Graphics rendering
    0x0249C2: "GAME_UPDATE (7 refs)",      # Game state update
    0x00C9F8: "LEVEL_LOAD (6 refs)",       # Level loading
    0x005BE4: "SPRITE_DRAW (6 refs)",      # Sprite drawing
    0x004A9E: "PLAYER_CTRL (6 refs)",      # Player control
    0x024AA8: "ENEMY_AI (5 refs)",         # Enemy AI
    0x028F92: "COLLISION (5 refs)",        # Collision detection
    0x024588: "PHYSICS (5 refs)",          # Physics update
    0x028D70: "INPUT_READ (5 refs)",       # Input reading
    0x005C5E: "SCROLL (5 refs)",           # Screen scrolling
    0x00C8E0: "MUSIC (4 refs)",            # Music control
    0x00091E: "INIT (4 refs)",             # Initialization
    0x000C1C: "VBLANK (4 refs)",           # VBlank handler
    0x024920: "WEAPON (4 refs)",           # Weapon handling
    0x02498C: "POWERUP (4 refs)",          # Power-up handling
    0x00DE82: "SCORE (4 refs)",            # Score handling
    0x000B40: "TITLE (3 refs)",            # Title screen
    0x000A90: "PAUSE (3 refs)",            # Pause handling
    0x00C9A6: "BOSS (3 refs)",             # Boss logic
    0x00AE8E: "DIALOG (3 refs)",           # Dialog/text
    0x024956: "PROJECTILE (3 refs)",       # Projectile handling
    0x003A92: "GAME_TICK (2 refs)",        # Game tick (called from IRQ)
    0x003E0E: "CCHIP_CMD (2 refs)",        # C-Chip command
    0x01F67E: "ANIMATE (2 refs)",          # Animation
    0x01242E: "DEATH (2 refs)",            # Player death
    0x000CC0: "GAME_OVER (2 refs)",        # Game over
}

print("=" * 70)
print("SUPERMAN GAME LOGIC — Key Function Analysis")
print("=" * 70)

for addr, desc in sorted(key_functions.items()):
    print(f"\n{'=' * 60}")
    print(f"${addr:06X}: {desc}")
    print(f"{'=' * 60}")
    
    pc = addr
    for i in range(30):
        if pc >= len(rom) - 1:
            break
        instr, size = decode(pc)
        
        # Highlight interesting patterns
        marker = ""
        if "09000" in instr: marker = " ← C-CHIP"
        elif "80000" in instr: marker = " ← SOUND"
        elif "0E000" in instr: marker = " ← SPRITE"
        elif "0B000" in instr: marker = " ← PALETTE"
        elif "0D000" in instr: marker = " ← VIDEO"
        elif "0F000" in instr: marker = " ← WRAM"
        elif "jsr" in instr.lower() and "???" not in instr: marker = " ← CALL"
        elif "bsr" in instr.lower() and "???" not in instr: marker = " ← CALL"
        elif instr in ("rts", "rte"): marker = " ← RETURN"
        elif "movem" in instr.lower(): marker = " ← SAVE/RESTORE"
        
        raw = " ".join("%02X" % rb(pc + j) for j in range(min(size, 6)))
        print(f"  ${pc:06X}: {instr:45s} {raw:18s}{marker}")
        pc += size
        
        # Stop at RTS/RTE
        if instr in ("rts", "rte"):
            break

# Also trace the reset handler more carefully
print(f"\n\n{'=' * 70}")
print("RESET HANDLER ($3EF0) — Full Trace")
print(f"{'=' * 70}")

pc = 0x3EF0
for i in range(80):
    if pc >= len(rom) - 1:
        break
    instr, size = decode(pc)
    
    marker = ""
    if "09000" in instr: marker = " ← C-CHIP"
    elif "700000" in instr: marker = " ← C-CHIP CMD"
    elif "300000" in instr or "400000" in instr or "600000" in instr: marker = " ← FRAME REG"
    elif "0D000" in instr: marker = " ← VIDEO REG"
    elif "jsr" in instr.lower() and "???" not in instr: marker = " ← CALL"
    elif "bsr" in instr.lower() and "???" not in instr: marker = " ← CALL"
    elif instr in ("rts", "rte"): marker = " ← RETURN"
    elif "movem" in instr.lower(): marker = " ← SAVE/RESTORE"
    elif "bra" in instr.lower(): marker = " ← BRANCH"
    
    raw = " ".join("%02X" % rb(pc + j) for j in range(min(size, 8)))
    print(f"  ${pc:06X}: {instr:45s} {raw:24s}{marker}")
    pc += size
    
    if instr in ("rts", "rte"):
        print(f"  --- End of reset handler ---")
        break
