#!/usr/bin/env python3
# Gameplay hot-function profile via the interp's FULL per-frame PC stream. Inject the frame-900
# gameplay state, ENABLE PC streaming ($0718=0; lockstep disables it for speed), run ONE game-tick
# (freeze at next $3A92), read the streamed PCs ($40:8000+, $0718=byte count) and histogram them
# by function. The interp runs gameplay reliably (unlike MAME under -debug), so this is the
# in-game instruction profile the attract f450 trace can't give.
import sys, os, collections
sys.path.insert(0, 'tools'); sys.path.insert(0, '/home/chad/Mesen2/python')
os.environ.setdefault('DOTNET_ROOT', '/home/chad/.dotnet8'); os.environ['PATH'] = '/home/chad/.dotnet8:' + os.environ.get('PATH', '')
from mesen_mcp import McpSession
S = '/tmp/claude-1000/-home-chad-supermn-snes/bc5e5a48-495f-47e6-9724-405edc2118da/scratchpad'
wramA = open(S + '/wramA.bin', 'rb').read(); regs = open(S + '/regsA.bin', 'rb').read()
def be32(d, o): return (d[o]<<24)|(d[o+1]<<16)|(d[o+2]<<8)|d[o+3]
D=[be32(regs,i*4) for i in range(8)]; A=[be32(regs,(8+i)*4) for i in range(7)]+[be32(regs,15*4)]; USP=be32(regs,16*4)
def le32(v): return '%02x%02x%02x%02x'%(v&0xFF,(v>>8)&0xFF,(v>>16)&0xFF,(v>>24)&0xFF)
with McpSession(rom='/home/chad/supermn-snes/build/interp.sfc',
                mesen='/home/chad/Mesen2/bin/linux-x64/Release/Mesen', port=7346, boot_wait=3.0) as m:
    def r16(a,mt='Sa1Memory'): b=m.read_memory(mt,a,2); return b[0]|(b[1]<<8)
    def w16(a,v,mt='Sa1Memory'): m.write_u16(a,v,mt)
    def wh(a,hx,mt='Sa1Memory'): m.write_memory(mt,a,hx)
    m.load_state_slot(6); w16(0x0700,1); w16(0x0702,0); w16(0x0704,0)
    for _ in range(20):
        m.run_frames(60)
        if r16(0x0702): break
    wh(0x00, ''.join(le32(D[i]) for i in range(8))+''.join(le32(A[i]) for i in range(8))); wh(0x40, le32(0x00003A92))
    w16(0x60,1); w16(0x6E,0); w16(0x70,0); w16(0x72,0); w16(0xA2,0)
    w16(0x7C,7); w16(0xA4,USP&0xFFFF); w16(0xA6,(USP>>16)&0xFFFF); w16(0xA8,1); w16(0xAA,0); w16(0xAC,0x2F60); w16(0x4A,0); w16(0x4C,0)
    w16(0x071A,0); wh(0x400000, wramA.hex(),'snesMemory'); w16(0x410000,0x0100,'snesMemory'); w16(0x410002,0x0100,'snesMemory')
    w16(0x0718, 0)                 # ENABLE PC streaming (NOT 0xFFF8)
    w16(0x0702,0); w16(0x0704,1)
    for _ in range(150):
        m.run_frames(60)
        if r16(0x0702): break
    nbytes = r16(0x0718); stream = m.read_memory('snesMemory', 0x408000, min(nbytes, 0xFFF8))
    pcs = [((stream[i+2]|(stream[i+3]<<8))<<16)|(stream[i]|(stream[i+1]<<8)) for i in range(0, len(stream)-3, 4)]
    print('streamed %d gameplay PCs (%d bytes)' % (len(pcs), nbytes))
    spin = {0x818,0x6C4,0x6C8,0x6CE,0x6FE,0x704,0x708,0x6F0,0x6F2,0x6FA}
    valid = [p for p in pcs if 0x800 <= p < 0x40000 and p not in spin]
    b = collections.Counter(p & ~0x3F for p in valid)
    print('valid game-code PCs: %d ; spin: %d' % (len(valid), sum(1 for p in pcs if p in spin)))
    print('top 25 hot 68K function-regions (64-byte buckets):')
    for region, c in b.most_common(25):
        print('  $%06X  %5d  (%4.1f%%)' % (region, c, 100*c/max(len(valid),1)))
