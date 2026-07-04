#!/usr/bin/env python3
# contention_combat.py — the COMBAT-class 5A22-contention measurement (companion to
# contention_probe.py, which free-runs the light NAT). Injects a combat triple
# (body_residency preamble: NAT -> $0708 stage -> $3A92 trap -> regs+wram inject) and
# free-runs K ticks, reporting PER-TICK SA-1 cycles. Run twice: PARK=0 (live) then PARK=1
# (5A22 parked in a WRAM bra-$ before release -> zero bus presence, no conflicts).
# Injection pins the start state, so tick i pairs across the two runs.
# Usage: contention_combat.py [triple=/tmp/supermn-scratch/ce4trip64] [K=6]   env: PARK, PORT
import sys, os
sys.path.insert(0,'tools'); sys.path.insert(0,'/home/chad/Mesen2/python')
os.environ['DOTNET_ROOT']='/home/chad/.dotnet10'; os.environ['PATH']='/home/chad/.dotnet10:'+os.environ.get('PATH','')
import mesen_mcp.session as _sess; _sess.validate_mesen_build=lambda *a,**k: None
from mesen_mcp import McpSession

TD=sys.argv[1] if len(sys.argv)>1 else '/tmp/supermn-scratch/ce4trip64'
K=int(sys.argv[2]) if len(sys.argv)>2 else 6
PARK=os.environ.get('PARK')=='1'
LH_OFF=0x0080FB; DFG_RFF=0x00D1D9       # src/interp.sym (re-check after interp rebuild)
F_CVLOOP=0x298835; PARKADDR=0x7EF800    # see contention_probe.py
wramA=open(TD+'/wramA.bin','rb').read(); regs=open(TD+'/regsA.bin','rb').read()
def be32(d,o): return (d[o]<<24)|(d[o+1]<<16)|(d[o+2]<<8)|d[o+3]
D=[be32(regs,i*4) for i in range(8)]; A=[be32(regs,(8+i)*4) for i in range(7)]
SP=be32(regs,15*4); USP=be32(regs,16*4); SR=be32(regs,17*4)&0xFFFF
Z=(SR>>2)&1;C=SR&1;Nf=(SR>>3)&1;V=(SR>>1)&1;X=(SR>>4)&1
def le32(v): return '%02x%02x%02x%02x'%(v&0xFF,(v>>8)&0xFF,(v>>16)&0xFF,(v>>24)&0xFF)
WN=len(wramA); NEXEN='/home/chad/Nexen/bin/linux-x64/Release/linux-x64/publish/Nexen'; NAT='/tmp/b0_native.mss'
print("combat contention: triple=%s K=%d PARK=%d"%(TD,K,PARK),flush=True)
with McpSession(rom='/home/chad/supermn-snes/build/interp.sfc',mesen=NEXEN,port=int(os.environ.get('PORT','7552')),boot_wait=6.0,socket_timeout=300.0) as m:
    def r16(a): b=m.read_memory('Sa1Memory',a,2); return b[0]|(b[1]<<8)
    def w16(a,v,mt='Sa1Memory'): m.write_u16(a,v,mt)
    def wh(a,hx,mt='Sa1Memory'): m.write_memory(mt,a,hx)
    def cyc(): return m.get_cpu_state('Sa1').get('cycleCount')
    def tickctr(): b=m.read_memory('snesMemory',0x401C56,2); return (b[0]<<8)|b[1]
    def runf(n,c=300):
        d=0
        while d<n: x=min(c,n-d); m.run_frames(x); d+=x
    m.load_state(NAT); runf(120)
    w16(0x0700,0); w16(0x071A,0); w16(0x0712,0); w16(0x0716,0); w16(0x0710,0x0708); w16(0x0704,1)
    for _ in range(240):
        runf(5)
        if r16(0x0712): break
        w16(0x0710,0x0708); w16(0x0716,0)
    w16(0x0712,0); w16(0x0710,0); w16(0x0714,1); runf(1); w16(0x0714,0)
    for _ in range(60):
        w16(0x0710,0x3A92); w16(0x0716,0); runf(4)
        if r16(0x0712): break
    wh(0x00, ''.join(le32(D[i]) for i in range(8)) + ''.join(le32(A[i]) for i in range(7)))
    wh(0x40, le32(0x00003A92)); w16(0x3C, SP&0xFFFF); w16(0x3E,(SP>>16)&0xFF)
    w16(0x60,Z);w16(0x6E,C);w16(0x70,Nf);w16(0x72,V);w16(0xA2,X);w16(0x7C,SR&7 or 7)
    w16(0xA4,USP&0xFFFF);w16(0xA6,(USP>>16)&0xFFFF);w16(0xA8,1);w16(0xAA,0);w16(0x4A,0);w16(0x4C,0)
    w16(0xAC,0x2F60); w16(0x0718,0xFFF8); w16(0x0724,0); w16(0x0730,0); w16(0x0734,0); w16(0x071A,1)
    w16(0x073A,1); w16(0x073C,0xA55A); w16(0x0736,0x5EEC)
    for o in range(0,WN,0x2000): wh(0x400000+o, wramA[o:o+0x2000].hex(),'snesMemory')
    w16(0x410000,0,'snesMemory'); w16(0x410002,0,'snesMemory')
    if PARK:
        wh(PARKADDR,'80fe','snesMemory')                # WRAM bra-$
        m.write_memory('snesPrgRom',F_CVLOOP,'5c00f87e'+'ea')   # jml $7EF800 over cv_loop
        runf(3)
        st=m.get_cpu_state('Snes')
        print("[PARK] 5A22 at $%02X:%04X"%(st.get('k',0),st.get('pc',0)),flush=True)
    h_rff=m.add_exec_hook(DFG_RFF, cpu_type='Sa1')
    w16(0x0712,0); w16(0x0714,1)
    r=m.run_until(max_frames=10, hook_handle=h_rff)      # $3A92 release wake
    m.remove_hook(h_rff)
    if os.environ.get('SAMPLE')=='1':
        import collections
        hist=collections.Counter(); reqs=collections.Counter()
        for i in range(160):
            m.run_frames(1)
            st=m.get_cpu_state('Snes')
            hist["%02X:%04X"%(st.get('k',0),st.get('pc',0)&0xFF00)]+=1
            reqs[(r16(0x3300),r16(0x3302))]+=1
        print("PC pages:",hist.most_common(8),flush=True)
        print("req/ack:",reqs.most_common(6),flush=True)
    perts=[]
    t=tickctr(); c=cyc(); fr=0
    while len(perts)<K and fr<4000:
        m.run_frames(2); fr+=2
        tn=tickctr()
        if tn!=t:
            cn=cyc(); perts.append((tn-t)&0xFFFF and (cn-c)//((tn-t)&0xFFFF)); t=tn; c=cn
    print(">>> per-tick cyc:", perts, flush=True)
    good=perts[:K]
    if good: print(">>> mean %d cyc/tick over %d ticks (PARK=%d)"%(sum(good)//len(good),len(good),PARK),flush=True)
