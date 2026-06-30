#!/usr/bin/env python3
# yield_diff PHASE 2 — full-interp-state single-yield differential. Injects the MAME-captured S0 (at
# $0532) into BOTH the escape build (build/interp.sfc) and the committed build
# (build/interp_committed.sfc), runs ONE switch-out, brackets the exit at lh_sched ($00F9B2, a bank-$00
# SA-1 exec-hook -> fires reliably, unlike bank-$92), and diffs the FULL interp DP state ($00-$1FF =
# reg file + flags + scratch) + work RAM. The divergent byte IS what entry_swo fails to replicate.
# Prereq: run yield_diff.py first (writes /tmp/supermn-scratch/yield/s0.bin + s0_regs.txt).
import sys, os, ast
sys.path.insert(0,'tools'); sys.path.insert(0,'/home/chad/Mesen2/python')
os.environ['DOTNET_ROOT']='/home/chad/.dotnet10'; os.environ['PATH']='/home/chad/.dotnet10:'+os.environ.get('PATH','')
import mesen_mcp.session as _sess; _sess.validate_mesen_build=lambda *a,**k: None
from mesen_mcp import McpSession
OUT='/tmp/supermn-scratch/yield'
s0=open(OUT+'/s0.bin','rb').read()
regs={k:int(v,16) for k,v in ast.literal_eval(open(OUT+'/s0_regs.txt').read()).items()}
D=[regs.get('D%d'%i,0)&0xFFFFFFFF for i in range(8)]
A=[regs.get('A%d'%i,0)&0xFFFFFFFF for i in range(7)]
SP=regs.get('SP',0)&0xFFFFFFFF; USP=regs.get('USP',0)&0xFFFFFFFF; SR=regs.get('SR',0)&0xFFFF
Z=(SR>>2)&1;C=SR&1;Nf=(SR>>3)&1;V=(SR>>1)&1;X=(SR>>4)&1;MASK=(SR>>8)&7
def le32(v): return '%02x%02x%02x%02x'%(v&0xFF,(v>>8)&0xFF,(v>>16)&0xFF,(v>>24)&0xFF)
NEXEN='/home/chad/Nexen/bin/linux-x64/Release/linux-x64/publish/Nexen'; NAT='/tmp/b0_native.mss'; LH=0x00F9B2
def run(rom, port):
    with McpSession(rom=rom,mesen=NEXEN,port=port,boot_wait=6.0,socket_timeout=300.0) as m:
        def r16(a): b=m.read_memory('Sa1Memory',a,2); return b[0]|(b[1]<<8)
        def w16(a,v): m.write_u16(a,v,'Sa1Memory')
        def wh(a,hx,mt='Sa1Memory'): m.write_memory(mt,a,hx)
        def runf(n,c=300):
            d=0
            while d<n: x=min(c,n-d); m.run_frames(x); d+=x
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
        # inject S0 + PC=$0532
        wh(0x00, ''.join(le32(D[i]) for i in range(8)) + ''.join(le32(A[i]) for i in range(7)))
        w16(0x40,0x0532); w16(0x42,0x0000); w16(0x3C,SP&0xFFFF); w16(0x3E,(SP>>16)&0xFFFF)
        w16(0x60,Z); w16(0x6E,C); w16(0x70,Nf); w16(0x72,V); w16(0xA2,X); w16(0x7C,MASK or 7)
        w16(0xA4,USP&0xFFFF); w16(0xA6,(USP>>16)&0xFFFF); w16(0xA8,1); w16(0xAA,0); w16(0x4A,0); w16(0x4C,0)
        w16(0xAC,0x2F60); w16(0x0718,0xFFF8)                      # IRQ countdown + PC-stream OFF
        for o in range(0,0x10000,0x2000): wh(0x400000+o, s0[o:o+0x2000].hex(),'snesMemory')
        m.write_u16(0x410000,0,'snesMemory'); m.write_u16(0x410002,0,'snesMemory')
        # release with the $0738=$A5A5 REDIRECT so df_gap re-fetches $40=$0532 (else the stale $3A92
        # opcode in $44 executes). $072E=1 keeps loop_hook on (trampoline + lh_sched). Run to lh_sched.
        w16(0x072E,1)
        Hc=m.add_exec_hook(0x00D128, cpu_type="Sa1")
        H=m.add_exec_hook(LH, cpu_type="Sa1")
        w16(0x0738,0xA5A5); w16(0x0712,0); w16(0x0710,0); w16(0x0714,1)
        rc=m.run_until(max_frames=5, hook_handle=Hc)
        print("  %s: inext(control) reason=%s $40=%04X $42=%04X (interp running?)"%(os.path.basename(rom),rc.get("reason"),r16(0x40),r16(0x42)))
        r=m.run_until(max_frames=60, hook_handle=H)
        if r.get('reason')!='hookFired':
            print("  %s: lh_sched NOT reached (%s) $40=%04X $42=%04X $0712=%d"%(
                  os.path.basename(rom),r.get('reason'),r16(0x40),r16(0x42),r16(0x0712))); return None,None
        dp=bytes(m.read_memory('Sa1Memory',0x00,0x200))          # interp DP state
        wr=bytes(m.read_memory('snesMemory',0x400000,0x10000))   # work RAM
        return dp,wr
print(">>> S0: a5=%06X a7=%06X SR=%04X"%(regs.get('A5',0)&0xFFFFFF,SP&0xFFFFFF,SR))
dpE,wrE=run('/home/chad/supermn-snes/build/interp.sfc',7546)
dpC,wrC=run('/home/chad/supermn-snes/build/interp_committed.sfc',7547)
if dpE and dpC:
    BENIGN={0x44,0x45,0x46,0x47,0x56,0x57,0x58,0x59}  # opcode/PC-delta/fetch-ptr (refetched, harmless)
    dpd=[(i,dpC[i],dpE[i]) for i in range(0x200) if dpC[i]!=dpE[i]]
    print(">>> DP state ($00-$1FF) diffs committed-vs-escape: %d (benign fetch-ptr filtered shown *)"%len(dpd))
    for i,c,e in dpd: print("    $%03X: committed=%02X escape=%02X%s"%(i,c,e,' *' if i in BENIGN else ''))
    wrd=[(i,wrC[i],wrE[i]) for i in range(0x10000) if wrC[i]!=wrE[i]]
    print(">>> work-RAM diffs committed-vs-escape: %d"%len(wrd))
    for i,c,e in wrd[:30]: print("    $F0%04X: committed=%02X escape=%02X"%(i,c,e))

# LIMITATION (why this doesn't yet crack the bug): injecting a MID-TICK $0532 state into a fresh
# interp is NOT faithful. capture_at_pc's SP is prefetch-skewed for stack-frame handlers like $0532
# (see memory mame-capture-precision), and the interp's full internal state at $0532 isn't reproduced
# by reg-file+workRAM alone -> the committed build resumes a corrupt frame ($42=$2404=SR). The diff is
# then escape-vs-corrupt. FAITHFUL FIX (next): capture S0 from the interp's OWN run (lockstep injects
# at $3A92 cleanly, then $0710-trap the first $0532) so there's no MAME skew + no fresh-inject; OR diff
# escape-vs-committed at an intermediate lockstep freeze (both run the full tick faithfully).
