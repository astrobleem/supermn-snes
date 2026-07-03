#!/usr/bin/env python3
# body_residency.py — total per-tick RESIDENCY of one native span (Phase-0 instrument): alternates
# run_until(ENTRY-hook) / run_until(EXIT-hook) across one GAME_TICK, accumulating cyc in-span. Built
# for wait-class escape bodies (e.g. entry_26a0, the GAME_TICK frame-sync: its native body spins on
# the frame flag -> its residency = PACING WAIT, to be EXCLUDED from active-compute). EXIT defaults
# to inext ($00:D128 -- jah2-class bodies end `jmp inext`). Tick end = the $0818 fetch trap ($0712).
# Usage: body_residency.py <triple> <ENTRY_hex24> [EXIT_hex24=00D128]   env: ESC0=1, PORT
import sys, os, collections
sys.path.insert(0,'tools'); sys.path.insert(0,'/home/chad/Mesen2/python')
os.environ['DOTNET_ROOT']='/home/chad/.dotnet10'; os.environ['PATH']='/home/chad/.dotnet10:'+os.environ.get('PATH','')
import mesen_mcp.session as _sess; _sess.validate_mesen_build=lambda *a,**k: None
from mesen_mcp import McpSession
TD=sys.argv[1]; ENTRY=int(sys.argv[2],16); EXITA=int(sys.argv[3],16) if len(sys.argv)>3 else 0x00D128
ESC0=os.environ.get('ESC0')=='1'
LH_OFF=0x0080FB; DFG_RFF=0x00D1D9       # src/interp.sym (re-check after interp rebuild)
wramA=open(TD+'/wramA.bin','rb').read(); regs=open(TD+'/regsA.bin','rb').read()
def be32(d,o): return (d[o]<<24)|(d[o+1]<<16)|(d[o+2]<<8)|d[o+3]
D=[be32(regs,i*4) for i in range(8)]; A=[be32(regs,(8+i)*4) for i in range(7)]
SP=be32(regs,15*4); USP=be32(regs,16*4); SR=be32(regs,17*4)&0xFFFF
Z=(SR>>2)&1;C=SR&1;Nf=(SR>>3)&1;V=(SR>>1)&1;X=(SR>>4)&1
def le32(v): return '%02x%02x%02x%02x'%(v&0xFF,(v>>8)&0xFF,(v>>16)&0xFF,(v>>24)&0xFF)
WN=len(wramA); NEXEN='/home/chad/Nexen/bin/linux-x64/Release/linux-x64/publish/Nexen'; NAT='/tmp/b0_native.mss'
print("triple %s  ENTRY=$%06X EXIT=$%06X ESC0=%s"%(TD,ENTRY,EXITA,ESC0),flush=True)
with McpSession(rom='/home/chad/supermn-snes/build/interp.sfc',mesen=NEXEN,port=int(os.environ.get('PORT','7542')),boot_wait=6.0,socket_timeout=300.0) as m:
    def r16(a): b=m.read_memory('Sa1Memory',a,2); return b[0]|(b[1]<<8)
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
    w16(0xAC,0x2F60); w16(0x0718,0xFFF8); w16(0x0724,0); w16(0x0730,0); w16(0x0734,0); w16(0x071A,1)
    w16(0x073A,1); w16(0x073C,0xA55A); w16(0x0736,0x5EEC)
    if ESC0: w16(0x071A,0); w16(0x073A,0); w16(0x073C,0); w16(0x0736,0)
    for o in range(0,WN,0x2000): wh(0x400000+o, wramA[o:o+0x2000].hex(),'snesMemory')
    w16(0x410000,0,'snesMemory'); w16(0x410002,0,'snesMemory')
    # Normalization: instead of a fragile one-tick end trap, run a FIXED cycle window and divide by
    # the game's own tick counter ($40:1C56, +1 per GAME_TICK header) -> residency PER TICK.
    WINDOW=int(os.environ.get('WINDOW','6000000'))
    def tickctr(): b=m.read_memory('snesMemory',0x401C56,2); return (b[0]<<8)|b[1]
    # NEXEN GOTCHA (verified in McpTools.cs): run_until stops when ANY registered hook matches --
    # the hookHandle arg is only checked against the GLOBAL match counter. So keep exactly ONE hook
    # registered at a time (add/remove alternation), else an inext exit-hook hijacks every stop.
    h_rff=m.add_exec_hook(DFG_RFF, cpu_type='Sa1')
    w16(0x0712,0); w16(0x0714,1)
    r=m.run_until(max_frames=10, hook_handle=h_rff)          # $3A92 release wake
    m.remove_hook(h_rff)
    c0=cyc(); t0=tickctr()
    spans=[]
    while True:
        h_in=m.add_exec_hook(ENTRY, cpu_type='Sa1')
        r=m.run_until(max_frames=15, hook_handle=h_in)
        m.remove_hook(h_in)
        if (r or {}).get('reason')!='hookFired':
            if cyc()-c0>=WINDOW: break
            continue                                          # sparse fires: keep waiting in-window
        if cyc()-c0>=WINDOW: break
        ci=cyc()
        h_out=m.add_exec_hook(EXITA, cpu_type='Sa1')
        r=m.run_until(max_frames=30, hook_handle=h_out)
        m.remove_hook(h_out)
        if (r or {}).get('reason')!='hookFired':
            print("!! exit lost after entry #%d"%len(spans),flush=True); break
        spans.append(cyc()-ci)
        if len(spans)>4000: print("!! runaway",flush=True); break
    c1=cyc(); t1=tickctr()
    ticks=max(1,(t1-t0)&0xFFFF)
    tot=sum(spans)
    print(">>> window=%d cyc, ticks=%d, fires=%d (%.1f/tick), RESIDENCY=%d cyc = %d/tick = %.1f%% of tick"%(
        c1-c0,ticks,len(spans),len(spans)/ticks,tot,tot//ticks,100.0*tot/max(1,c1-c0)),flush=True)
    print(">>> spans (first 24):",spans[:24],flush=True)
