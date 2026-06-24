#!/usr/bin/env python3
# Mid-frame register capture: inject MAME's frame-N state, then run with the
# dbg_fetch debug-freeze armed at a target 68K PC (default $1E7CC, task-7 loop).
# When the interp's PC hits the target, dbg_fetch freezes; we read the interp
# register file + the list it is about to walk, to compare vs MAME.
import sys, os
sys.path.insert(0, 'tools'); sys.path.insert(0, '/home/chad/Mesen2/python')
os.environ.setdefault('DOTNET_ROOT', '/home/chad/.dotnet8')
os.environ['PATH'] = '/home/chad/.dotnet8:' + os.environ.get('PATH', '')
from mesen_mcp import McpSession

S = '/tmp/claude-1000/-home-chad-supermn-snes/bc5e5a48-495f-47e6-9724-405edc2118da/scratchpad'
wramA = open(S + '/wramA.bin', 'rb').read()
regs = open(S + '/regsA.bin', 'rb').read()
TARGET = int(sys.argv[1], 0) if len(sys.argv) > 1 else 0x1E7CC
def be32(d, o): return (d[o] << 24) | (d[o+1] << 16) | (d[o+2] << 8) | d[o+3]
D = [be32(regs, i*4) for i in range(8)]
A = [be32(regs, (8+i)*4) for i in range(7)] + [be32(regs, 15*4)]
USP = be32(regs, 16*4)
def le16(v): return '%02x%02x' % (v & 0xFF, (v >> 8) & 0xFF)
def le32(v): return ''.join('%02x' % ((v >> (8*i)) & 0xFF) for i in range(4))

with McpSession(rom='/home/chad/supermn-snes/build/interp.sfc',
                mesen='/home/chad/Mesen2/bin/linux-x64/Release/Mesen', port=7346, boot_wait=3.0) as m:
    def r16(a, mt='Sa1Memory'): b = m.read_memory(mt, a, 2); return b[0] | (b[1] << 8)
    def r32dp(a): return r16(a) | (r16(a+2) << 16)   # interp reg: low16@a, high16@a+2
    def w16(a, v, mt='Sa1Memory'): m.write_u16(a, v, mt)
    def wh(a, hx, mt='Sa1Memory'): m.write_memory(mt, a, hx)

    m.load_state_slot(6)
    w16(0x0700, 1); w16(0x0702, 0); w16(0x0704, 0)
    for _ in range(20):
        m.run_frames(60)
        if r16(0x0702): break
    print('B0 frozen; injecting frame-450 state, debug-freeze target=$%05X' % TARGET)

    regblk = ''.join(le32(D[i]) for i in range(8)) + ''.join(le32(A[i]) for i in range(8))
    wh(0x00, regblk)
    wh(0x40, le32(0x00003A92))
    w16(0x60, 1); w16(0x6E, 0); w16(0x70, 0); w16(0x72, 0); w16(0xA2, 0)
    w16(0x7C, 7); w16(0xA4, USP & 0xFFFF); w16(0xA6, (USP >> 16) & 0xFFFF)
    w16(0xA8, 1); w16(0xAA, 0); w16(0xAC, 0x7000); w16(0x4A, 0); w16(0x4C, 0)
    wh(0x400000, wramA.hex(), 'snesMemory')
    w16(0x410000, 0, 'snesMemory'); w16(0x410002, 0, 'snesMemory')

    # arm the debug-PC freeze, release the $3A92 hook
    w16(0x0710, TARGET & 0xFFFF)        # dbg_fetch target low16
    w16(0x0716, (TARGET >> 16) & 0xFFFF)  # dbg_fetch target bank
    w16(0x0712, 0); w16(0x0714, 0)
    w16(0x0702, 0); w16(0x0704, 1)
    hit = False
    for _ in range(40):
        m.run_frames(30)
        if r16(0x0712): hit = True; break
    if not hit:
        print('debug-freeze target $%05X NOT hit this frame' % TARGET); sys.exit(0)

    a6 = r32dp(0x38); a1 = r32dp(0x24); a0 = r32dp(0x20)
    d5 = r32dp(0x14); d7 = r32dp(0x1C); d1 = r32dp(0x04); d2 = r32dp(0x08)
    pc = r16(0x40)
    print('FROZEN at 68K PC=$%05X' % pc)
    print('  D1=%08X D2=%08X D5=%08X D7=%08X' % (d1, d2, d5, d7))
    print('  A0=%06X A1=%06X A6=%06X' % (a0 & 0xFFFFFF, a1 & 0xFFFFFF, a6 & 0xFFFFFF))
    # the list a1 walks (8 longs from a1), read from BW-RAM $40
    base = (a1 & 0xFFFFFF) - 0xF00000
    if 0 <= base < 0x4000 - 32:
        lst = m.read_memory('snesMemory', 0x400000 + base, 32)
        vals = [(lst[i*4] << 24) | (lst[i*4+1] << 16) | (lst[i*4+2] << 8) | lst[i*4+3] for i in range(8)]
        print('  list @ a1=$%06X:' % (a1 & 0xFFFFFF), ' '.join('%08X' % v for v in vals))
