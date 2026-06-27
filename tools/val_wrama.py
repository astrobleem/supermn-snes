#!/usr/bin/env python3
# Generic escape validator on the wramA GAMEPLAY frame (Mesen slot6 + wramA inject — the
# stream_profile.py state, which exercises the in-game hot functions). Freezes at the target
# function entry to learn its return, then runs the game-tick ON ($071A=1, escape) vs OFF
# ($071A=0, interp), freezing both at the return; diffs the 68K reg file + $40 work RAM + $41
# video shadow. GREEN = bit-exact. Complements val_28d4.py (the b0-transplant frame): use this
# for functions the b0 frame doesn't call. Usage: val_wrama.py <hex-entry>
#
# CAVEAT: $40 diff==0 == bit-exact, BUT a SMALL $40 diff on a LONG-path function is a known
# false RED: the gate is global so ALL escapes fire in the ON run, and across a long path to
# the return the faster ON run accrues an $AC/scheduler timing skew (~tens of bytes) vs OFF.
# entry_ce4 ($000CE4) shows ~22 such bytes yet is MAME-validated good. Short-path leaf escapes
# (e.g. entry_28d4) are clean. For a long-path or video escape, compare the function's SPECIFIC
# output region (like val_fb8's $401C00-$402400), not the full $40, to avoid the artifact.
import sys, os
sys.path.insert(0,'tools'); sys.path.insert(0,'/home/chad/Mesen2/python')
os.environ.setdefault('DOTNET_ROOT','/home/chad/.dotnet8'); os.environ['PATH']='/home/chad/.dotnet8:'+os.environ.get('PATH','')
from mesen_mcp import McpSession
S=os.environ.get('SUPERMN_VALSTATE','/tmp/claude-1000/-home-chad-supermn-snes/bc5e5a48-495f-47e6-9724-405edc2118da/scratchpad')
TARGET=int(sys.argv[1],16) if len(sys.argv)>1 else 0x0CE4
wramA=open(S+'/wramA.bin','rb').read(); regs=open(S+'/regsA.bin','rb').read()
def be32(d,o): return (d[o]<<24)|(d[o+1]<<16)|(d[o+2]<<8)|d[o+3]
D=[be32(regs,i*4) for i in range(8)]; A=[be32(regs,(8+i)*4) for i in range(7)]+[be32(regs,15*4)]; USP=be32(regs,16*4)
def le32(v): return '%02x%02x%02x%02x'%(v&0xFF,(v>>8)&0xFF,(v>>16)&0xFF,(v>>24)&0xFF)
with McpSession(rom='/home/chad/supermn-snes/build/interp.sfc', mesen='/home/chad/Mesen2/bin/linux-x64/Release/Mesen', port=7464, boot_wait=3.0) as m:
    def r16(a,mt='Sa1Memory'): b=m.read_memory(mt,a,2); return b[0]|(b[1]<<8)
    def w16(a,v,mt='Sa1Memory'): m.write_u16(a,v,mt)
    def wh(a,hx,mt='Sa1Memory'): m.write_memory(mt,a,hx)
    def setup(hook, bp_lo, bp_bank):
        m.load_state_slot(6); w16(0x0700,1); w16(0x0702,0); w16(0x0704,0)
        for _ in range(20):
            m.run_frames(60)
            if r16(0x0702): break
        wh(0x00, ''.join(le32(D[i]) for i in range(8))+''.join(le32(A[i]) for i in range(8))); wh(0x40, le32(0x00003A92))
        w16(0x60,1); w16(0x6E,0); w16(0x70,0); w16(0x72,0); w16(0xA2,0)
        w16(0x7C,7); w16(0xA4,USP&0xFFFF); w16(0xA6,(USP>>16)&0xFFFF); w16(0xA8,1); w16(0xAA,0); w16(0xAC,0x2F60); w16(0x4A,0); w16(0x4C,0)
        wh(0x400000, wramA.hex(),'snesMemory'); w16(0x410000,0x0100,'snesMemory'); w16(0x410002,0x0100,'snesMemory')
        w16(0x071A,hook); w16(0x0718,0xFFF8); w16(0x0712,0); w16(0x0714,0); w16(0x0710,bp_lo); w16(0x0716,bp_bank)
        w16(0x0702,0); w16(0x0704,1)
    def runfz():
        for _ in range(80):
            m.run_frames(20)
            if r16(0x0712) or r16(0x0702): return
    setup(0, TARGET&0xFFFF, (TARGET>>16)&0xFFFF); runfz()
    if not r16(0x0712):
        print(">>> $%06X NOT reached in the wramA tick ($0712=0) — not exercised here either" % TARGET); sys.exit()
    a7=r16(0x3C)|(r16(0x3E)<<16); sb=m.read_memory('snesMemory',0x400000|(a7&0xFFFF),4)
    hi=sb[0]<<8|sb[1]; lo=sb[2]<<8|sb[3]
    print("frozen at $%06X: a7=$%06X return=$%04X:%04X" % (TARGET,a7,hi,lo), flush=True)
    def run_to_ret(hook):
        setup(hook, lo, hi); runfz()
        return r16(0x0712), bytes(m.read_memory('Sa1Memory',0x00,0x40)), bytes(m.read_memory('snesMemory',0x400000,0x8000)), bytes(m.read_memory('snesMemory',0x410000,0x8000))
    of,orf,o40,o41=run_to_ret(0); nf,nrf,n40,n41=run_to_ret(1)
    RN=['d0','d1','d2','d3','d4','d5','d6','d7','a0','a1','a2','a3','a4','a5','a6','a7']
    def rd(b,s): i=s*4; return b[i]|(b[i+1]<<8)|(b[i+2]<<16)|(b[i+3]<<24)
    rdiff=[RN[s] for s in range(16) if rd(orf,s)!=rd(nrf,s)]
    bd40=sum(1 for i in range(len(o40)) if o40[i]!=n40[i]); bd41=sum(1 for i in range(len(o41)) if o41[i]!=n41[i])
    print("OFF froze=%d | ON froze=%d ; reg diffs=%s ; $40 diff=%d ; $41 diff=%d (timing)" % (of,nf,rdiff or "NONE",bd40,bd41), flush=True)
    print(">>>", "GREEN — $%06X bit-exact ($40) on the wramA frame" % TARGET if (not rdiff and bd40==0 and nf and of) else "RED")
