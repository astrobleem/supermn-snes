#!/usr/bin/env python3
# Accumulation test: inject MAME's frame-N state ONCE, then run the interpreter
# freely through several frames (re-releasing the $0708 hook each frame), diffing
# vs MAME's frames N+1, N+2, N+3.  Growing residual => real divergence; bounded =>
# single-injection phase artifact.
import sys, os
sys.path.insert(0, 'tools'); sys.path.insert(0, '/home/chad/Mesen2/python')
os.environ.setdefault('DOTNET_ROOT', '/home/chad/.dotnet8')
os.environ['PATH'] = '/home/chad/.dotnet8:' + os.environ.get('PATH', '')
from mesen_mcp import McpSession

S = '/tmp/claude-1000/-home-chad-supermn-snes/bc5e5a48-495f-47e6-9724-405edc2118da/scratchpad'
wc = [open('%s/wc%d.bin' % (S, k), 'rb').read() for k in range(4)]   # MAME frames 300..303 (clean)
regs = open(S + '/regsC.bin', 'rb').read()
def be32(d, o): return (d[o] << 24) | (d[o+1] << 16) | (d[o+2] << 8) | d[o+3]
D = [be32(regs, i*4) for i in range(8)]
A = [be32(regs, (8+i)*4) for i in range(7)] + [be32(regs, 15*4)]
USP = be32(regs, 16*4); SR = be32(regs, 17*4)
def le32(v): return ''.join('%02x' % ((v >> (8*i)) & 0xFF) for i in range(4))

with McpSession(rom='/home/chad/supermn-snes/build/interp.sfc',
                mesen='/home/chad/Mesen2/bin/linux-x64/Release/Mesen', port=7346, boot_wait=3.0) as m:
    def r16(a): b = m.read_memory('Sa1Memory', a, 2); return b[0] | (b[1] << 8)
    def w16(a, v, mt='Sa1Memory'): m.write_u16(a, v, mt)
    def wh(a, hx, mt='Sa1Memory'): m.write_memory(mt, a, hx)
    def wait_freeze():
        for _ in range(40):
            m.run_frames(60)
            if r16(0x0502): return True
        return False

    m.load_state_slot(6)
    w16(0x0500, 1); w16(0x0502, 0); w16(0x0504, 0)
    wait_freeze()                                   # B0
    # inject MAME frame 300
    wh(0x00, ''.join(le32(D[i]) for i in range(8)) + ''.join(le32(A[i]) for i in range(8)))
    wh(0x40, le32(0x00003A92))
    w16(0x60, 1); w16(0x6E, 0); w16(0x70, 0); w16(0x72, 0); w16(0xA2, 0)
    w16(0x7C, 7); w16(0xA4, USP & 0xFFFF); w16(0xA6, (USP >> 16) & 0xFFFF)
    w16(0xA8, 1); w16(0xAA, 0); w16(0xAC, 0x7000); w16(0x4A, 0); w16(0x4C, 0)
    wh(0x400000, wc[0].hex(), 'snesMemory')
    w16(0x410000, 0, 'snesMemory'); w16(0x410002, 0, 'snesMemory')

    for k in range(1, 4):
        w16(0x0502, 0); w16(0x0504, 1)              # release -> run one frame -> freeze
        if not wait_freeze():
            print('frame %d: never froze' % k); break
        out = m.read_memory('snesMemory', 0x400000, 0x4000)
        diff = sum(1 for i in range(0x4000) if out[i] != wc[k][i])
        print('after %d injected-free frame(s): interp vs MAME frame %d = %d / 16384 bytes' % (k, 300 + k, diff))
