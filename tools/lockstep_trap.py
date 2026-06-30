#!/usr/bin/env python3
# Full-tick lockstep using the $0710/$0712 PC-TRAP (fires at instruction fetch -> ESCAPE-COMPATIBLE,
# unlike the $0700/$0702 jsr-hook freeze which is bypassed when the GAME_TICK path itself is escaped).
# Trap at $0710=$3A92 (the GAME_TICK boundary wramB is captured at). Inject MAME frame-N, run one tick
# with escapes=ESC, diff vs wramB. Usage: lockstep_trap.py <triple-dir> [AC_hex] [ESC]
# WIP: B0 trap acquisition not yet firing (B0 stage1(0708)=False). profile_real uses the SAME $0710=
# $0708 trap successfully -- replicate its exact sequence: `runf(150); m.load_state(NAT); <set flags
# incl w16(0x0704,1)>; w16(0x0710,0x0708); for: runf(5); if $0712: break` (boot Nexen BEFORE load_state,
# set $0704=1, arm $0710 once). Then 2-stage to $3A92 for the wramB phase. See mame-capture-precision.
import sys, os
sys.path.insert(0,'tools'); sys.path.insert(0,'/home/chad/Mesen2/python')
os.environ['DOTNET_ROOT']='/home/chad/.dotnet10'; os.environ['PATH']='/home/chad/.dotnet10:'+os.environ.get('PATH','')
import mesen_mcp.session as _sess; _sess.validate_mesen_build=lambda *a,**k: None
from mesen_mcp import McpSession
TD=sys.argv[1]; AC=int(sys.argv[2],16) if len(sys.argv)>2 else 0x2F60; ESC=int(sys.argv[3]) if len(sys.argv)>3 else 0
wramA=open(TD+'/wramA.bin','rb').read(); wramB=open(TD+'/wramB.bin','rb').read(); regs=open(TD+'/regsA.bin','rb').read()
def be32(d,o): return (d[o]<<24)|(d[o+1]<<16)|(d[o+2]<<8)|d[o+3]
D=[be32(regs,i*4) for i in range(8)]; A=[be32(regs,(8+i)*4) for i in range(7)]
SP=be32(regs,15*4); USP=be32(regs,16*4); SR=be32(regs,17*4)&0xFFFF
Z=(SR>>2)&1;C=SR&1;N=(SR>>3)&1;V=(SR>>1)&1;X=(SR>>4)&1
def le32(v): return '%02x%02x%02x%02x'%(v&0xFF,(v>>8)&0xFF,(v>>16)&0xFF,(v>>24)&0xFF)
NEXEN='/home/chad/Nexen/bin/linux-x64/Release/linux-x64/publish/Nexen'; NAT='/tmp/b0_native.mss'
WN=len(wramA)
print("triple %s AC=%04X ESC=%d WN=%d SP=%06X"%(TD,AC,ESC,WN,SP&0xFFFFFF),flush=True)
with McpSession(rom='/home/chad/supermn-snes/build/interp.sfc',mesen=NEXEN,port=7526,boot_wait=6.0,socket_timeout=300.0) as m:
    def r16(a): b=m.read_memory('Sa1Memory',a,2); return b[0]|(b[1]<<8)
    def w16(a,v,mt='Sa1Memory'): m.write_u16(a,v,mt)
    def wh(a,hx,mt='Sa1Memory'): m.write_memory(mt,a,hx)
    def runf(n,c=300):
        d=0
        while d<n: x=min(c,n-d); m.run_frames(x); d+=x
    m.load_state(NAT); runf(120)
    # CRITICAL: NAT is saved FROZEN at jh_spin via $0700/$0702/$0704 -> set $0704=1 to RELEASE it,
    # else the interp never runs (instr=0) and no trap fires.
    w16(0x0700,0); w16(0x071A,0); w16(0x0712,0); w16(0x0716,0); w16(0x0710,0x0708); w16(0x0704,1)
    # B0 stage 1: reach gameplay via the $0708 IRQ (a direct $3A92 trap from NAT never fires)
    s1=False
    for _ in range(240):
        runf(5)
        if r16(0x0712): s1=True; break
        w16(0x0710,0x0708); w16(0x0716,0)   # re-arm (one-shot clears on release)
    # release one step, then stage 2: trap the GAME_TICK $3A92 (the wramB phase)
    w16(0x0712,0); w16(0x0710,0); w16(0x0714,1); runf(1); w16(0x0714,0)
    b0=False
    for _ in range(60):
        w16(0x0710,0x3A92); w16(0x0716,0); runf(4)
        if r16(0x0712): b0=True; break
    print("B0 stage1(0708)=%s stage2(3A92)=%s"%(s1,b0),flush=True)
    # inject MAME frame-N over the trapped interp
    wh(0x00, ''.join(le32(D[i]) for i in range(8)) + ''.join(le32(A[i]) for i in range(7)))
    wh(0x40, le32(0x00003A92)); w16(0x3C, SP&0xFFFF); w16(0x3E,(SP>>16)&0xFF)
    w16(0x60,Z);w16(0x6E,C);w16(0x70,N);w16(0x72,V);w16(0xA2,X);w16(0x7C,SR&7 or 7)
    w16(0xA4,USP&0xFFFF);w16(0xA6,(USP>>16)&0xFFFF);w16(0xA8,1);w16(0xAA,0);w16(0x4A,0);w16(0x4C,0)
    w16(0xAC,AC); w16(0x0718,0xFFF8); w16(0x0724,0); w16(0x0730,0); w16(0x0734,0); w16(0x071A,ESC)
    for o in range(0,WN,0x2000): wh(0x400000+o, wramA[o:o+0x2000].hex(),'snesMemory')
    w16(0x410000,0,'snesMemory'); w16(0x410002,0,'snesMemory')
    # release one step past B0, then trap at the next $0708 IRQ entry (B1). NOTE: with escapes ON the
    # GAME_TICK $3A92 is itself a native escape (entry_3a92) so the interp never FETCHES $3A92 -> can't
    # trap there; $0708 (IRQ entry, before entry_3a92 runs) is escape-safe. Small phase offset vs wramB
    # (the $0708->$3A92 IRQ prologue).
    B1PC=int(os.environ.get('B1PC','0708'),16)
    w16(0x0712,0); w16(0x0710,0); w16(0x0714,1); runf(1); w16(0x0714,0)
    b1=False
    for _ in range(400):
        w16(0x0710,B1PC); w16(0x0716,0); runf(4)
        if r16(0x0712): b1=True; break
    instr=r16(0x4A)|(r16(0x4C)<<16)
    print("B1 trap=%s instr=%d ce4=%d 13be=%d ceb6=%d esc=%d"%(b1,instr,r16(0x0724),r16(0x0730),r16(0x0734),ESC),flush=True)
    if os.environ.get('REGDUMP'):
        rf=bytes(m.read_memory('Sa1Memory',0x00,0x40))
        nm=['d0','d1','d2','d3','d4','d5','d6','d7','a0','a1','a2','a3','a4','a5','a6','a7']
        print("=== reg file @ B1 (PC=$%04X) ==="%B1PC,flush=True)
        print("  \$AC=$%04X  \$4A/4C(instr)=%d  \$AA(vbl)=$%04X  \$A8=$%04X"%(r16(0xAC),r16(0x4A)|(r16(0x4C)<<16),r16(0xAA),r16(0xA8)),flush=True)
        for i in range(16):
            lo=rf[i*4]|(rf[i*4+1]<<8); hi=rf[i*4+2]|(rf[i*4+3]<<8)
            print("  %s=$%04X%04X"%(nm[i],hi,lo),flush=True)
        md=os.environ.get("MEMDUMP")
        if md:
            for rng in md.split(","):
                a=int(rng,16); b=bytes(m.read_memory("snesMemory",0x400000+a,16))
                print("  $F0%04X: %s"%(a," ".join("%02X"%x for x in b)),flush=True)
    out=bytes(m.read_memory('snesMemory',0x400000,WN))
    excl=set(range(0x170A-0x80,0x170A+0x80))
    diff=[i for i in range(WN) if out[i]!=wramB[i] and i not in excl]
    print(">>> $40 diff vs MAME wramB = %d bytes (stack-excl)"%len(diff),flush=True)
    lim=len(diff) if os.environ.get('FULLDIFF') else 20
    for i in diff[:lim]: print("   $F0%04X: interp=%02X mame=%02X (A=%02X)"%(i,out[i],wramB[i],wramA[i]),flush=True)
    print(">>>", "GREEN" if len(diff)<=8 else "DIFF=%d"%len(diff),flush=True)
