#!/usr/bin/env python3
# FAITHFUL single-yield differential. Avoids capture_at_pc's prefetch skew (and the un-reproduced
# interp state of phase 2) by capturing S0 from the INTERP'S OWN run: inject ce4trip64 at $3A92
# (lockstep-clean), catch the first $0532 via the $0710 trap, and dump the COMPLETE interp state
# (IRAM $0000-$06FF = reg file+PC+opcode+$AC+scratch, EXCL harness control $0700+; + work RAM 64KB).
# Then inject that exact state into BOTH the escape and committed builds, run ONE switch-out, bracket
# at lh_sched ($00F9B2 bank-0 SA-1 hook), and diff the full interp state -> the divergent byte.
import sys, os
sys.path.insert(0,'tools'); sys.path.insert(0,'/home/chad/Mesen2/python')
os.environ['DOTNET_ROOT']='/home/chad/.dotnet10'; os.environ['PATH']='/home/chad/.dotnet10:'+os.environ.get('PATH','')
import mesen_mcp.session as _sess; _sess.validate_mesen_build=lambda *a,**k: None
from mesen_mcp import McpSession
TD='/tmp/supermn-scratch/ce4trip64'
regs=open(TD+'/regsA.bin','rb').read(); wramA=open(TD+'/wramA.bin','rb').read()
def be32(d,o): return (d[o]<<24)|(d[o+1]<<16)|(d[o+2]<<8)|d[o+3]
D=[be32(regs,i*4) for i in range(8)]; A=[be32(regs,(8+i)*4) for i in range(7)]
SP=be32(regs,15*4); USP=be32(regs,16*4); SR=be32(regs,17*4)&0xFFFF
Z=(SR>>2)&1;C=SR&1;Nf=(SR>>3)&1;V=(SR>>1)&1;X=(SR>>4)&1
def le32(v): return '%02x%02x%02x%02x'%(v&0xFF,(v>>8)&0xFF,(v>>16)&0xFF,(v>>24)&0xFF)
WN=len(wramA); NEXEN='/home/chad/Nexen/bin/linux-x64/Release/linux-x64/publish/Nexen'; NAT='/tmp/b0_native.mss'; LH=0x00F9B2
ESC='/home/chad/supermn-snes/build/interp.sfc'; COM='/home/chad/supermn-snes/build/interp_committed.sfc'

def sess(rom,port):
    return McpSession(rom=rom,mesen=NEXEN,port=port,boot_wait=6.0,socket_timeout=300.0)
def helpers(m):
    def r16(a): b=m.read_memory('Sa1Memory',a,2); return b[0]|(b[1]<<8)
    def w16(a,v): m.write_u16(a,v,'Sa1Memory')
    def wh(a,hx,mt='Sa1Memory'): m.write_memory(mt,a,hx)
    def runf(n,c=300):
        d=0
        while d<n: x=min(c,n-d); m.run_frames(x); d+=x
    return r16,w16,wh,runf
def to_3a92(m):
    r16,w16,wh,runf=helpers(m)
    m.load_state(NAT); runf(120)
    w16(0x0700,0); w16(0x0738,0); w16(0x071A,1); w16(0x0712,0); w16(0x0716,0); w16(0x0710,0x0708); w16(0x0704,1)
    for _ in range(240):
        runf(5)
        if r16(0x0712): break
        w16(0x0710,0x0708); w16(0x0716,0)
    w16(0x0712,0); w16(0x0710,0); w16(0x0714,1); runf(1); w16(0x0714,0)
    for _ in range(60):
        w16(0x0710,0x3A92); w16(0x0716,0); runf(4)
        if r16(0x0712): break
def inject_ce4(m):
    r16,w16,wh,runf=helpers(m)
    wh(0x00, ''.join(le32(D[i]) for i in range(8)) + ''.join(le32(A[i]) for i in range(7)))
    wh(0x40, le32(0x00003A92)); w16(0x3C, SP&0xFFFF); w16(0x3E,(SP>>16)&0xFF)
    w16(0x60,Z);w16(0x6E,C);w16(0x70,Nf);w16(0x72,V);w16(0xA2,X);w16(0x7C,SR&7 or 7)
    w16(0xA4,USP&0xFFFF);w16(0xA6,(USP>>16)&0xFFFF);w16(0xA8,1);w16(0xAA,0);w16(0x4A,0);w16(0x4C,0)
    w16(0xAC,0x2F60); w16(0x0718,0xFFF8)
    for o in range(0,WN,0x2000): wh(0x400000+o, wramA[o:o+0x2000].hex(),'snesMemory')
    m.write_u16(0x410000,0,'snesMemory'); m.write_u16(0x410002,0,'snesMemory')

# ---- PHASE A: capture FAITHFUL S0 (committed build) ----
with sess(COM,7551) as m:
    r16,w16,wh,runf=helpers(m)
    to_3a92(m); inject_ce4(m)
    w16(0x0712,0); w16(0x0710,0); w16(0x0714,1); runf(1); w16(0x0714,0)   # step into the tick
    got=False
    for _ in range(80):
        w16(0x0710,0x0532); w16(0x0716,0); runf(1)
        if r16(0x0712): got=True; break
    if not got: print(">>> no $0532 reached in committed run"); sys.exit()
    a5=r16(0x34)|(r16(0x36)<<16); a7=r16(0x3C)|(r16(0x3E)<<16)
    print(">>> FAITHFUL S0 at $0532: a5=%06X a7=%06X $40=%04X $44=%04X $AC=%04X"%(a5&0xFFFFFF,a7&0xFFFFFF,r16(0x40),r16(0x44),r16(0xAC)))
    iram=bytes(m.read_memory('Sa1Memory',0x0000,0x0700))        # $0000-$06FF (excl harness $0700+)
    wram=bytes(m.read_memory('snesMemory',0x400000,0x10000))

# descriptor address (switch-out's LAST write) = *(a5+$4a) -- a build-independent bracket point
DESC=((wram[0x4a]<<24)|(wram[0x4b]<<16)|(wram[0x4c]<<8)|wram[0x4d])&0xFFFF
print(">>> bracket: write-hook on descriptor $F0%04X ($400000+%04X)"%(DESC,DESC))
# ---- PHASE B: inject S0 into a build, run ONE switch-out, capture when it writes the descriptor ----
def run_switchout(rom,port):
    with sess(rom,port) as m:
        r16,w16,wh,runf=helpers(m)
        to_3a92(m)
        for o in range(0,0x0700,0x100): wh(o, iram[o:o+0x100].hex())   # inject faithful IRAM
        for o in range(0,0x10000,0x2000): wh(0x400000+o, wram[o:o+0x2000].hex(),'snesMemory')
        m.write_u16(0x410000,0,'snesMemory'); m.write_u16(0x410002,0,'snesMemory')
        w16(0x072E,1)
        H=m.add_write_hook(0x400000+DESC, cpu_type='Sa1')          # fires when the switch-out writes (a4)
        w16(0x0712,0); w16(0x0710,0); w16(0x0714,1)                # release ($44 already = $0532 opcode)
        r=m.run_until(max_frames=20, hook_handle=H)
        if r.get('reason')!='hookFired':
            print("  %s: descriptor write NOT seen ($40=%04X $42=%04X)"%(os.path.basename(rom),r16(0x40),r16(0x42))); return None,None
        dp=bytes(m.read_memory('Sa1Memory',0x00,0x100)); wr=bytes(m.read_memory('snesMemory',0x400000,0x10000))
        return dp,wr
dpC,wrC=run_switchout(COM,7552)
dpE,wrE=run_switchout(ESC,7553)
if dpC and dpE:
    BEN={0x44,0x45,0x46,0x47,0x56,0x57,0x58,0x59}
    dpd=[(i,dpC[i],dpE[i]) for i in range(0x100) if dpC[i]!=dpE[i]]
    print(">>> DP ($00-$FF) committed-vs-escape: %d diffs"%len(dpd))
    for i,c,e in dpd: print("    $%02X: committed=%02X escape=%02X%s"%(i,c,e,'  (benign fetch)' if i in BEN else '  <==='))
    wrd=[(i,wrC[i],wrE[i]) for i in range(0x10000) if wrC[i]!=wrE[i]]
    print(">>> work-RAM committed-vs-escape: %d diffs"%len(wrd))
    for i,c,e in wrd[:30]: print("    $F0%04X: committed=%02X escape=%02X"%(i,c,e))

# RESULT: PHASE A (faithful capture from the interp's OWN run -> no MAME prefetch skew) WORKS. PHASE B
# (inject that state into a fresh interp + run the switch-out) does NOT: even the interp's own mid-tick
# state, re-injected as IRAM $0000-$06FF + work RAM, does not reproduce execution (committed build goes
# to a corrupt $5E:0036; escape stays at $0532). Mid-tick interp state is NOT fully captured by
# DP+workRAM -- the SA-1 NATIVE STACK, the $41 video shadow, $0700+ interp/loop_hook control, and SA-1
# hardware/cycle state also matter and aren't reproduced by a fresh navigate-to-$3A92.
# CONCLUSION: a single-yield differential via INJECTION is a dead end for this mid-tick handler. The
# real path is INTERP-SIDE INSTRUMENTATION: a debug build whose $0710 freeze RE-FIRES (single-step on
# release) so escape-vs-committed can be diffed in-place across consecutive $0532 of ONE faithful tick,
# with no injection. That needs a small (zero-shift) df_gap change -- invasive but the only clean route.
