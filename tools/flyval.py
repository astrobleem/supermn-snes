#!/usr/bin/env python3
# Settle whether entry_ce4's flying-stage divergence is a real bug or a lockstep artifact:
# inject the MAME flying-stage state A, run one tick with the escape hook ON (native) and OFF
# (interpreted), and compare EACH against the MAME reference wramB. If ON matches MAME as well as
# OFF does -> artifact (entry_ce4 is correct). If ON is much worse -> real entry_ce4 bug.
# Sweeps $AC to find the tick length where OFF best matches MAME. Usage: flyval.py <AC[,AC...]> [input_hex]
import sys, os
import os
sys.path.insert(0, 'tools'); sys.path.insert(0, '/home/chad/Mesen2/python')
os.environ.setdefault('DOTNET_ROOT', '/home/chad/.dotnet8'); os.environ['PATH'] = '/home/chad/.dotnet8:' + os.environ.get('PATH', '')
from mesen_mcp import McpSession
S = os.environ.get('SUPERMN_SCRATCH', '/tmp/supermn-scratch') + '/flytick'
regs = open(S + '/regsA.bin', 'rb').read(); wramA = open(S + '/wramA.bin', 'rb').read(); wramB = open(S + '/wramB.bin', 'rb').read()
def be32(d, o): return (d[o]<<24)|(d[o+1]<<16)|(d[o+2]<<8)|d[o+3]
D = [be32(regs, i*4) for i in range(8)]; A = [be32(regs, (8+i)*4) for i in range(7)] + [be32(regs, 15*4)]; USP = be32(regs, 16*4)
def le32(v): return '%02x%02x%02x%02x' % (v&0xFF, (v>>8)&0xFF, (v>>16)&0xFF, (v>>24)&0xFF)
ACS = [int(x, 16) for x in sys.argv[1].split(',')] if len(sys.argv) > 1 else [0xE000]
INP = int(sys.argv[2], 16) if len(sys.argv) > 2 else 0

def cmp_mame(w):  # exclude $3F00-$3F47 (MAME's extraction clobbers it to stash regs)
    return sum(1 for i in range(0x4000) if w[i] != wramB[i] and not (0x3F00 <= i < 0x3F48))

with McpSession(rom='/home/chad/supermn-snes/build/interp.sfc',
                mesen='/home/chad/Mesen2/bin/linux-x64/Release/Mesen', port=7349, boot_wait=3.0) as m:
    def r16(a, mt='Sa1Memory'): b = m.read_memory(mt, a, 2); return b[0]|(b[1]<<8)
    def w16(a, v, mt='Sa1Memory'): m.write_u16(a, v, mt)
    def wh(a, hx, mt='Sa1Memory'): m.write_memory(mt, a, hx)
    m.load_state_slot(6); w16(0x0700, 1); w16(0x0702, 0); w16(0x0704, 0)
    for _ in range(20):
        m.run_frames(60)
        if r16(0x0702): break
    print("B0 frozen, starting ticks", flush=True)

    def one_tick(hook, ac):
        wh(0x00, ''.join(le32(D[i]) for i in range(8)) + ''.join(le32(A[i]) for i in range(8))); wh(0x40, le32(0x00003A92))
        w16(0x60, 1); w16(0x6E, 0); w16(0x70, 0); w16(0x72, 0); w16(0xA2, 0)
        w16(0x7C, 7); w16(0xA4, USP&0xFFFF); w16(0xA6, (USP>>16)&0xFFFF); w16(0xA8, 1); w16(0xAA, 0); w16(0x4A, 0); w16(0x4C, 0); w16(0xAC, ac)
        w16(0x0718, 0xFFF8); wh(0x400000, wramA.hex(), 'snesMemory'); w16(0x410000, INP, 'snesMemory'); w16(0x410002, INP, 'snesMemory')
        w16(0x071A, hook); w16(0x0726, 0)
        w16(0x0702, 0); w16(0x0704, 1)
        for _ in range(200):
            m.run_frames(60)
            if r16(0x0702): break
        n = r16(0x4A) | (r16(0x4C) << 16); xfa = r16(0x0726)
        return n, xfa, bytes(m.read_memory('snesMemory', 0x400000, 0x4000))

    for ac in ACS:
        n_on, xfa_on, on = one_tick(1, ac)
        print("AC=%04X | ON  (native):      N=%d  off-screen-tiles=%d  ON-vs-MAME=%d" % (ac, n_on, xfa_on, cmp_mame(on)), flush=True)
        n_off, xfa_off, off = one_tick(0, ac)
        offs = [i for i in range(0x4000) if on[i] != off[i]]
        print("AC=%04X | OFF (interpreted): N=%d  OFF-vs-MAME=%d ; ON-vs-OFF=%d" % (ac, n_off, cmp_mame(off), len(offs)), flush=True)
        print("  ON-vs-OFF:", [("$%04X" % i, "ON=%02X/OFF=%02X" % (on[i], off[i])) for i in offs], flush=True)
