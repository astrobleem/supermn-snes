#!/usr/bin/env python3
# Freeze at the first $00CB9E call (hook OFF) and dump its inputs, then compute the
# expected outputs by the 68K semantics -- to find the entry_cb9e transpile bug.
import sys, os
sys.path.insert(0, 'tools'); sys.path.insert(0, '/home/chad/Mesen2/python')
os.environ.setdefault('DOTNET_ROOT', '/home/chad/.dotnet8')
os.environ['PATH'] = '/home/chad/.dotnet8:' + os.environ.get('PATH', '')
from mesen_mcp import McpSession

S = '/tmp/claude-1000/-home-chad-supermn-snes/bc5e5a48-495f-47e6-9724-405edc2118da/scratchpad'
wramA = open(S + '/wramA.bin', 'rb').read()
regs = open(S + '/regsA.bin', 'rb').read()
def be32(d, o): return (d[o] << 24) | (d[o+1] << 16) | (d[o+2] << 8) | d[o+3]
D = [be32(regs, i*4) for i in range(8)]
A = [be32(regs, (8+i)*4) for i in range(7)] + [be32(regs, 15*4)]
USP = be32(regs, 16*4)
def le32(v): return ''.join('%02x' % ((v >> (8*i)) & 0xFF) for i in range(4))

with McpSession(rom='/home/chad/supermn-snes/build/interp.sfc',
                mesen='/home/chad/Mesen2/bin/linux-x64/Release/Mesen', port=7346, boot_wait=3.0) as m:
    def r16(a): b = m.read_memory('Sa1Memory', a, 2); return b[0] | (b[1] << 8)
    def r32dp(a): return r16(a) | (r16(a+2) << 16)
    def w16(a, v): m.write_u16(a, v, 'Sa1Memory')
    def wh(a, hx, mt='Sa1Memory'): m.write_memory(mt, a, hx)
    # 68K work-RAM accessors (big-endian, 16KB)
    def rdw(ad): o = (ad - 0xF00000) & 0x3FFF; b = m.read_memory('snesMemory', 0x400000+o, 2); return (b[0] << 8) | b[1]
    def rdb(ad): o = (ad - 0xF00000) & 0x3FFF; return m.read_memory('snesMemory', 0x400000+o, 1)[0]
    def rdl(ad): o = (ad - 0xF00000) & 0x3FFF; b = m.read_memory('snesMemory', 0x400000+o, 4); return (b[0] << 24)|(b[1] << 16)|(b[2] << 8)|b[3]

    m.load_state_slot(6)
    w16(0x0700, 1); w16(0x0702, 0); w16(0x0704, 0)
    for _ in range(20):
        m.run_frames(60)
        if r16(0x0702): break
    regblk = ''.join(le32(D[i]) for i in range(8)) + ''.join(le32(A[i]) for i in range(8))
    wh(0x00, regblk); wh(0x40, le32(0x00003A92))
    w16(0x60, 1); w16(0x6E, 0); w16(0x70, 0); w16(0x72, 0); w16(0xA2, 0)
    w16(0x7C, 7); w16(0xA4, USP & 0xFFFF); w16(0xA6, (USP >> 16) & 0xFFFF)
    w16(0xA8, 1); w16(0xAA, 0); w16(0xAC, 0x2F60); w16(0x4A, 0); w16(0x4C, 0)
    wh(0x400000, wramA.hex(), 'snesMemory')
    m.write_u16(0x410000, 0x0100, 'snesMemory'); m.write_u16(0x410002, 0x0100, 'snesMemory')
    w16(0x071A, 0)                       # hook OFF -> $CB9E runs, dbg_fetch freezes at it
    w16(0x0710, 0xCB9E); w16(0x0716, 0x0000)
    w16(0x0712, 0); w16(0x0714, 0)
    w16(0x0702, 0); w16(0x0704, 1)
    hit = False
    for _ in range(120):
        m.run_frames(20)
        if r16(0x0712): hit = True; break
    if not hit:
        print('did not reach $CB9E'); sys.exit(0)

    a0 = r32dp(0x20) & 0xFFFFFF; a1 = r32dp(0x24) & 0xFFFFFF; a6 = r32dp(0x38) & 0xFFFFFF
    d2 = r32dp(0x08)
    print('FROZEN at $%04X ; a0=%06X a1=%06X a6=%06X d2=%08X' % (r16(0x40), a0, a1, a6, d2))
    test = rdw(a1 + 0)
    m22 = rdw((a6 - 0x22) & 0xFFFFFF); m1e = rdw((a6 - 0x1e) & 0xFFFFFF)
    m24 = rdb((a6 - 0x24) & 0xFFFFFF); a2 = rdl((a6 - 0x54) & 0xFFFFFF)
    a0_2, a0_4, a0_6, a0_8 = rdw(a0+2), rdw(a0+4), rdw(a0+6), rdw(a0+8); a0_c = rdb(a0+0xc)
    print('  (a1)=%04X  ble-early=%s' % (test, (test == 0 or test & 0x8000)))
    print('  [a6-22]=%04X [a6-1e]=%04X [a6-24].b=%02X (bit7=%d) [a6-54]=a2=%06X'
          % (m22, m1e, m24, (m24 >> 7) & 1, a2 & 0xFFFFFF))
    print('  [a0+2]=%04X [a0+4]=%04X [a0+6]=%04X [a0+8]=%04X [a0+c].b=%02X' % (a0_2, a0_4, a0_6, a0_8, a0_c))
    if not (test == 0 or test & 0x8000):
        bit = (m24 >> 7) & 1
        if bit:
            d0 = (-a0_4) & 0xFFFF; d1 = (-a0_2) & 0xFFFF
        else:
            d0 = a0_2; d1 = a0_4
        print('  EXPECTED: [a1+6]=%04X [a1+8]=%04X [a1+2]=%04X [a1+4]=%04X (d0=%04X d1=%04X)'
              % ((m22+a0_6) & 0xFFFF, (m22+a0_8) & 0xFFFF, (m1e+d0) & 0xFFFF, (m1e+d1) & 0xFFFF, d0, d1))
