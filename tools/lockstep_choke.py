#!/usr/bin/env python3
# Chokepoint A/B on the GREEN ESC=0 baseline. Clones lockstep_nexen's PROVEN $0700 jsr-hook injection
# (the reliable boundary; the $0710 fetch-trap method drifts). Always ESC=0 ($071A=0) so the buggy
# ESC=1 escapes are OUT; the fetch-chokepoint is gated on a DEDICATED flag $073A (env CHOKE).
#   CHOKE=0 -> pure interp baseline (ce4 interpreted). Must be GREEN (== lockstep_nexen ESC=0).
#   CHOKE=1 -> ce4/entry_ce4t dispatched natively via xlat_choke. Must STAY GREEN + counter>0.
# Reports SA-1 cycles B0->B1, interp instr count, work-RAM diff vs MAME wramB, and the $40:7FE0 counter.
import sys, os
sys.path.insert(0,'tools'); sys.path.insert(0,'/home/chad/Mesen2/python')
os.environ['DOTNET_ROOT']='/home/chad/.dotnet10'; os.environ['PATH']='/home/chad/.dotnet10:'+os.environ.get('PATH','')
import mesen_mcp.session as _sess; _sess.validate_mesen_build=lambda *a,**k: None
from mesen_mcp import McpSession
TD=sys.argv[1] if len(sys.argv)>1 else '/tmp/supermn-scratch/ce4trip64'
AC=int(os.environ.get('AC','2F60'),16)
CHOKE=int(os.environ.get('CHOKE','0'))
SWIN=int(os.environ.get('SWIN','0'))   # scheduler switch-IN escape (entry_swin): 1 -> arm $073C=$A55A
ESC=int(os.environ.get('ESC','0'))     # $071A global escape gate (jah2/xlat/coroutine); default 0 = the historical GREEN baseline
wramA=open(TD+'/wramA.bin','rb').read(); wramB=open(TD+'/wramB.bin','rb').read(); regs=open(TD+'/regsA.bin','rb').read()
def be32(d,o): return (d[o]<<24)|(d[o+1]<<16)|(d[o+2]<<8)|d[o+3]
D=[be32(regs,i*4) for i in range(8)]; A=[be32(regs,(8+i)*4) for i in range(7)]
SP=be32(regs,15*4); USP=be32(regs,16*4); SR=be32(regs,17*4)&0xFFFF
Z=(SR>>2)&1;C=SR&1;N=(SR>>3)&1;V=(SR>>1)&1;X=(SR>>4)&1
def le32(v): return '%02x%02x%02x%02x'%(v&0xFF,(v>>8)&0xFF,(v>>16)&0xFF,(v>>24)&0xFF)
NEXEN='/home/chad/Nexen/bin/linux-x64/Release/linux-x64/publish/Nexen'; NAT='/tmp/b0_native.mss'
print("triple %s  AC=%04X  CHOKE=%d  SWIN=%d  ESC=%d"%(TD,AC,CHOKE,SWIN,ESC),flush=True)
PORT=int(os.environ.get('PORT','7523'))
with McpSession(rom='/home/chad/supermn-snes/build/interp.sfc',mesen=NEXEN,port=PORT,boot_wait=6.0,socket_timeout=300.0) as m:
    def r16(a): b=m.read_memory('Sa1Memory',a,2); return b[0]|(b[1]<<8)
    def w16(a,v,mt='Sa1Memory'): m.write_u16(a,v,mt)
    def wh(a,hx,mt='Sa1Memory'): m.write_memory(mt,a,hx)
    def runf(n,c=300):
        d=0
        while d<n: x=min(c,n-d); m.run_frames(x); d+=x
    m.load_state(NAT)
    w16(0x073A,0)                 # chokepoint OFF during boot-drive to B0
    w16(0x073C,0)                 # switch-IN escape OFF during boot-drive too
    m.write_u16(0x407FE0,0,'snesMemory')   # zero ce4-dispatch counter EARLY (catch fires during run-to-B0)
    runf(120)
    w16(0x0700,1); w16(0x0702,0); w16(0x0704,1)
    b0=False
    for _ in range(60):
        runf(20)
        if r16(0x0702): b0=True; break
    # DIAG (advisor): did the chokepoint fire during run-to-B0? => $073A is NOT free (indexed write flips it)
    g=r16(0x073A); pc=m.read_memory('snesMemory',0x407FE0,2); precnt=pc[0]|(pc[1]<<8)
    print("B0 frozen=%s   [pre-arm $073A=%04X  ce4_cnt=%d]"%(b0,g,precnt),flush=True)
    if not b0:
        ring=m.read_memory('Sa1Memory',0x0400,0x200); idx=r16(0x48)
        def pc_at(o): return ((ring[o+2]|(ring[o+3]<<8))<<16)|(ring[o]|(ring[o+1]<<8))
        pcs=[pc_at((idx+4*k)&0x1FF) for k in range(128)]
        print("   B0 NO-FREEZE last 40 68K PCs: %s"%' '.join('%05X'%p for p in pcs[-40:]),flush=True)
    wh(0x00, ''.join(le32(D[i]) for i in range(8)) + ''.join(le32(A[i]) for i in range(7)))
    wh(0x40, le32(0x00003A92))
    w16(0x3C, SP&0xFFFF); w16(0x3E,(SP>>16)&0xFF)
    w16(0x60,Z);w16(0x6E,C);w16(0x70,N);w16(0x72,V);w16(0xA2,X);w16(0x7C,SR&7 or 7)
    w16(0xA4,USP&0xFFFF);w16(0xA6,(USP>>16)&0xFFFF);w16(0xA8,1);w16(0xAA,0);w16(0x4A,0);w16(0x4C,0)
    w16(0xAC,AC); w16(0x0718,0xFFF8); w16(0x0724,0); w16(0x0730,0); w16(0x071A,ESC)
    WN=len(wramA)
    for o in range(0,WN,0x2000): wh(0x400000+o, wramA[o:o+0x2000].hex(),'snesMemory')
    w16(0x410000,0,'snesMemory'); w16(0x410002,0,'snesMemory')
    w16(0x407FE0,0,'snesMemory')  # zero ce4-dispatch counter
    w16(0x407FE2,0,'snesMemory')  # zero swin commit counter
    w16(0x407FE4,0,'snesMemory')  # zero 8fat counter (campaign 2)
    w16(0x407FE6,0,'snesMemory')  # zero fd2t counter (campaign 2)
    w16(0x073A,CHOKE)             # arm chokepoint for the measured tick
    w16(0x073C,0xA55A if SWIN else 0)  # arm switch-IN escape (magic-match gate in entry_swin)
    try: cyc0=m.get_cpu_state('Sa1').get('cycleCount')
    except Exception: cyc0=None
    w16(0x0702,0); w16(0x0704,1)
    b1=False
    for _ in range(200):
        runf(20)
        if r16(0x0702): b1=True; break
    try: cyc1=m.get_cpu_state('Sa1').get('cycleCount')
    except Exception: cyc1=None
    c_ce4=r16(0x0724); c_13be=r16(0x0730)
    ctr=m.read_memory('snesMemory',0x407FE2,6)
    c_swin=ctr[0]|(ctr[1]<<8); c_8fa=ctr[2]|(ctr[3]<<8); c_fd2=ctr[4]|(ctr[5]<<8)
    instr=r16(0x4A)|(r16(0x4C)<<16)
    cyc=(cyc1-cyc0) if (b1 and cyc0 is not None and cyc1 is not None) else -1
    print("B1 frozen=%s  cycles(B0->B1)=%d  instr=%d  dispatch: ce4=%d 13be=%d swin=%d 8fa=%d fd2=%d"%(b1,cyc,instr,c_ce4,c_13be,c_swin,c_8fa,c_fd2),flush=True)
    out=bytes(m.read_memory('snesMemory',0x400000,WN))
    excl=set(range(0x170A-0x80,0x170A+0x80))
    diff=[i for i in range(WN) if out[i]!=wramB[i] and i not in excl]
    print(">>> $40 diff vs MAME(wramB) = %d bytes (stack-excl)  %s"%(len(diff),"GREEN" if len(diff)<=8 else "DIFF"),flush=True)
    for i in diff[:12]: print("   $F0%04X: interp=%02X mame=%02X (A=%02X)"%(i,out[i],wramB[i],wramA[i]),flush=True)
