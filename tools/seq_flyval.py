#!/usr/bin/env python3
# For each adjacent tick in the flyseq, inject it, run ONE tick with native entry_ce4 (hook ON),
# and compare directly to the NEXT tick's MAME state (the true wramB). Reports off-screen-tile count
# per frame, so we can read ON-vs-MAME exactly on the ticks that exercise the off-screen clamp.
import sys, os, glob, re
import os
sys.path.insert(0, '/home/chad/Mesen2/python')
os.environ.setdefault('DOTNET_ROOT', '/home/chad/.dotnet8'); os.environ['PATH'] = '/home/chad/.dotnet8:' + os.environ.get('PATH', '')
from mesen_mcp import McpSession
SD = os.environ.get('SUPERMN_SCRATCH', '/tmp/supermn-scratch') + '/flyseq'
N = len(glob.glob(SD + '/s*.regs.bin'))
ticks = [(open('%s/s%02d.regs.bin' % (SD, i), 'rb').read(), open('%s/s%02d.wram.bin' % (SD, i), 'rb').read()) for i in range(N)]
def be32(d, o): return (d[o]<<24)|(d[o+1]<<16)|(d[o+2]<<8)|d[o+3]
def le32(v): return '%02x%02x%02x%02x' % (v&0xFF, (v>>8)&0xFF, (v>>16)&0xFF, (v>>24)&0xFF)
AC = int(sys.argv[1], 16) if len(sys.argv) > 1 else 0x8000
START = int(sys.argv[2]) if len(sys.argv) > 2 else 0
with McpSession(rom='/home/chad/supermn-snes/build/interp.sfc',
                mesen='/home/chad/Mesen2/bin/linux-x64/Release/Mesen', port=7360, boot_wait=3.0) as m:
    def r16(a, mt='Sa1Memory'): b = m.read_memory(mt, a, 2); return b[0]|(b[1]<<8)
    def w16(a, v, mt='Sa1Memory'): m.write_u16(a, v, mt)
    def wh(a, hx, mt='Sa1Memory'): m.write_memory(mt, a, hx)
    m.load_state_slot(6); w16(0x0700, 1); w16(0x0702, 0); w16(0x0704, 0)
    for _ in range(20):
        m.run_frames(60)
        if r16(0x0702): break
    print("B0 frozen", flush=True)
    for i in range(START, N - 1):
        regs, wramA = ticks[i]; wramB = ticks[i+1][1]
        D = [be32(regs, k*4) for k in range(8)]; A = [be32(regs, (8+k)*4) for k in range(7)] + [be32(regs, 15*4)]; USP = be32(regs, 16*4)
        wh(0x00, ''.join(le32(D[k]) for k in range(8)) + ''.join(le32(A[k]) for k in range(8))); wh(0x40, le32(0x00003A92))
        w16(0x60, 1); w16(0x6E, 0); w16(0x70, 0); w16(0x72, 0); w16(0xA2, 0)
        w16(0x7C, 7); w16(0xA4, USP&0xFFFF); w16(0xA6, (USP>>16)&0xFFFF); w16(0xA8, 1); w16(0xAA, 0); w16(0x4A, 0); w16(0x4C, 0); w16(0xAC, AC)
        w16(0x0718, 0xFFF8); wh(0x400000, wramA.hex(), 'snesMemory'); w16(0x410000, 0, 'snesMemory'); w16(0x410002, 0, 'snesMemory')
        w16(0x071A, 1); w16(0x0726, 0)
        w16(0x0702, 0); w16(0x0704, 1)
        for _ in range(200):
            m.run_frames(60)
            if r16(0x0702): break
        xfa = r16(0x0726)
        on = bytes(m.read_memory('snesMemory', 0x400000, 0x4000))
        diff = sum(1 for k in range(0x4000) if on[k] != wramB[k] and not (0x3F00 <= k < 0x3F48))
        flag = "  <== OFF-SCREEN" if xfa > 0 else ""
        print("tick s%02d: off-screen-tiles=%2d  ON-vs-MAME=%d%s" % (i, xfa, diff, flag), flush=True)
