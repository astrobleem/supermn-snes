#!/usr/bin/env python3
# tick_timeline.py — COMPLETE cycle-attribution timeline of one GAME_TICK (Phase-0 instrument).
# Exec-hooks LH_OFF ($00:80FB, the fetch-path point reached by EVERY genuinely-interpreted 68K
# instruction -- inext is NOT universal, branch paths bypass it; lh_off is what the $4A counter counts) and run_until's stop-by-stop through the tick, reading the SA-1
# cycleCount + the 68K PC ($40/$42) at every stop. The cyc GAP between consecutive stops = that
# instruction's full cost INCLUDING any native span it triggered (escape body, loop_hook-collapsed
# loop, IRQ slice landing in it) -> hidden fetch-less cycle sinks show up as giant gaps at their
# trigger PC. Ends at the first stop whose 68K PC is the $0818 main-loop idle.
# Usage: tick_timeline.py <triple> [top_n]   env: ESC0=1 (gates off), PORT
import sys, os, collections
sys.path.insert(0,'tools'); sys.path.insert(0,'/home/chad/Mesen2/python')
os.environ['DOTNET_ROOT']='/home/chad/.dotnet10'; os.environ['PATH']='/home/chad/.dotnet10:'+os.environ.get('PATH','')
import mesen_mcp.session as _sess; _sess.validate_mesen_build=lambda *a,**k: None
from mesen_mcp import McpSession
TD=sys.argv[1]; TOPN=int(sys.argv[2]) if len(sys.argv)>2 else 40
ESC0=os.environ.get('ESC0')=='1'
LH_OFF=0x0080FB; DFG_RFF=0x00D1D9       # src/interp.sym (re-check after interp rebuild)
wramA=open(TD+'/wramA.bin','rb').read(); regs=open(TD+'/regsA.bin','rb').read()
def be32(d,o): return (d[o]<<24)|(d[o+1]<<16)|(d[o+2]<<8)|d[o+3]
D=[be32(regs,i*4) for i in range(8)]; A=[be32(regs,(8+i)*4) for i in range(7)]
SP=be32(regs,15*4); USP=be32(regs,16*4); SR=be32(regs,17*4)&0xFFFF
Z=(SR>>2)&1;C=SR&1;Nf=(SR>>3)&1;V=(SR>>1)&1;X=(SR>>4)&1
def le32(v): return '%02x%02x%02x%02x'%(v&0xFF,(v>>8)&0xFF,(v>>16)&0xFF,(v>>24)&0xFF)
WN=len(wramA); NEXEN='/home/chad/Nexen/bin/linux-x64/Release/linux-x64/publish/Nexen'; NAT='/tmp/b0_native.mss'
print("triple %s  ESC0=%s"%(TD,ESC0),flush=True)
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
    h_stop=m.add_exec_hook(LH_OFF, cpu_type='Sa1'); h_rff=m.add_exec_hook(DFG_RFF, cpu_type='Sa1')
    w16(0x0712,0); w16(0x0714,1)
    r=m.run_until(max_frames=10, hook_handle=h_rff)          # point 0: the $3A92 release wake
    c_prev=cyc(); pc_prev=0x3A92; bank_prev=0
    events=[]                                                 # (pc24, gap_cyc)
    total=0
    while True:
        r=m.run_until(max_frames=60, hook_handle=h_stop)
        if (r or {}).get('reason')!='hookFired':
            print("!! lh_off stop lost (reason=%s) after %d events"%((r or {}).get('reason'),len(events)),flush=True)
            break
        c_now=cyc()
        gap=c_now-c_prev
        events.append(((bank_prev<<16)|pc_prev,gap)); total+=gap
        pc_prev=r16(0x40); bank_prev=r16(0x42)&0xFF
        c_prev=c_now
        if bank_prev==0 and 0x0810<=pc_prev<=0x0830: break    # reached the main-loop idle -> tick done
        if len(events)>12000: print("!! runaway (12K stops) -- aborting",flush=True); break
    print(">>> %d interp stops, attributed total = %d cyc"%(len(events),total),flush=True)
    agg=collections.Counter(); cnt=collections.Counter()
    for pc,g in events: agg[pc]+=g; cnt[pc]+=1
    print(">>> TOP %d PCs by attributed cycles:"%TOPN,flush=True)
    import capstone as _cs; _MD=_cs.Cs(_cs.CS_ARCH_M68K,_cs.CS_MODE_BIG_ENDIAN)
    _ROM=open('build/interp.sfc','rb').read()
    for pc,g in agg.most_common(TOPN):
        try: ins=next(_MD.disasm(_ROM[0x10000+(pc&0x3FFFFF):0x10000+(pc&0x3FFFFF)+8],pc)); d='%s %s'%(ins.mnemonic,ins.op_str)
        except StopIteration: d='?'
        print(">>>   $%06X  %8d cyc  x%-4d (avg %6d)  [%s]"%(pc,g,cnt[pc],g//max(1,cnt[pc]),d),flush=True)
    print(">>> gap histogram: <500=%d  500-2K=%d  2K-10K=%d  10K-50K=%d  50K-200K=%d  >200K=%d"%(
        sum(1 for _,g in events if g<500), sum(1 for _,g in events if 500<=g<2000),
        sum(1 for _,g in events if 2000<=g<10000), sum(1 for _,g in events if 10000<=g<50000),
        sum(1 for _,g in events if 50000<=g<200000), sum(1 for _,g in events if g>=200000)),flush=True)
