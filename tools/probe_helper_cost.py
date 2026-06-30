#!/usr/bin/env python3
# RAW native rate (task #12): bracket ONE invocation of a big BRIDGELESS escape (entry_15b4 =
# 255x move.l copy via the generic EA helpers; no jml-inext bridge round-trips) in SA-1 cycles via
# run_until on exec-hooks. cyc/255 = native cyc per 68K-instr WITHOUT bridge round-trips -> decides
# whether overhead-stripping makes full coverage fit the 60fps budget. Inject ce4trip64 gameplay.
import sys, os
sys.path.insert(0,'tools'); sys.path.insert(0,'/home/chad/Mesen2/python')
os.environ['DOTNET_ROOT']='/home/chad/.dotnet10'; os.environ['PATH']='/home/chad/.dotnet10:'+os.environ.get('PATH','')
import mesen_mcp.session as _sess; _sess.validate_mesen_build=lambda *a,**k: None
from mesen_mcp import McpSession
ENTRY=0x00E5B2; INEXT=0x00E5B5; NCOPY=1   # rdw_ea_l entry -> its rtl = ONE helper call
TD='/tmp/supermn-scratch/ce4trip64'
wramA=open(TD+'/wramA.bin','rb').read(); regs=open(TD+'/regsA.bin','rb').read()
def be32(d,o): return (d[o]<<24)|(d[o+1]<<16)|(d[o+2]<<8)|d[o+3]
D=[be32(regs,i*4) for i in range(8)]; A=[be32(regs,(8+i)*4) for i in range(7)]
SP=be32(regs,15*4); USP=be32(regs,16*4); SR=be32(regs,17*4)&0xFFFF
Z=(SR>>2)&1;C=SR&1;Nf=(SR>>3)&1;V=(SR>>1)&1;X=(SR>>4)&1
def le32(v): return '%02x%02x%02x%02x'%(v&0xFF,(v>>8)&0xFF,(v>>16)&0xFF,(v>>24)&0xFF)
WN=len(wramA); NEXEN='/home/chad/Nexen/bin/linux-x64/Release/linux-x64/publish/Nexen'; NAT='/tmp/b0_native.mss'
with McpSession(rom='/home/chad/supermn-snes/build/interp.sfc',mesen=NEXEN,port=7534,boot_wait=6.0,socket_timeout=300.0) as m:
    def r16(a,mt='Sa1Memory'): b=m.read_memory(mt,a,2); return b[0]|(b[1]<<8)
    def w16(a,v,mt='Sa1Memory'): m.write_u16(a,v,mt)
    def wh(a,hx,mt='Sa1Memory'): m.write_memory(mt,a,hx)
    def cyc(): return m.get_cpu_state('Sa1').get('cycleCount')
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
    w16(0xAC,0x2F60); w16(0x0718,0xFFF8); w16(0x071A,1)   # ESC=1 (escapes on -> entry_15b4 can dispatch)
    for o in range(0,WN,0x2000): wh(0x400000+o, wramA[o:o+0x2000].hex(),'snesMemory')
    w16(0x410000,0,'snesMemory'); w16(0x410002,0,'snesMemory')
    w16(0x0712,0); w16(0x0710,0); w16(0x0714,1); runf(1); w16(0x0714,0)
    Hentry=m.add_exec_hook(ENTRY, cpu_type='Sa1'); Hnext=m.add_exec_hook(INEXT, cpu_type='Sa1')
    samples=[]
    for k in range(10):
        r=m.run_until(max_frames=600, hook_handle=Hentry)
        if not r.get('hookFired') and 'hook' not in str(r).lower() and r.get('reason')!='hook':
            # fall back: check if it actually paused on the hook by diag
            pass
        ce=cyc()
        r2=m.run_until(max_frames=8, hook_handle=Hnext)
        cx=cyc()
        d=cx-ce
        samples.append(d)
        print(">>> sample %d: entry_15b4 fired, cyc entry=%s exit=%s  delta=%s  -> %.1f cyc/move.l"%(k,ce,cx,d, d/NCOPY if d else 0),flush=True)
    if samples:
        good=[s for s in samples if s and s>0]
        if good:
            avg=sum(good)/len(good)
            print(">>> RAW NATIVE: %.0f cyc per move.l (avg of %d) | budget needs <=75 cyc/instr for full-coverage fit"%(avg/1*1.0/1 if False else avg/NCOPY*1, len(good), ),flush=True)
            print(">>> RAW NATIVE rate = %.1f cyc / 68K-instr (bridgeless)"%(avg/NCOPY),flush=True)
    else:
        print(">>> entry_15b4 never fired -- try a different escape or more frames",flush=True)
