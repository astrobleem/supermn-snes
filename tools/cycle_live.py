#!/usr/bin/env python3
# LIVE-CONTEXT per-escape cycle harness — measures STATE-DEPENDENT escapes (collision/object handlers
# that read passed-in a0/a1 + full object state, which the synthetic driver in cycle_isolate.py can't
# reproduce). Instead of a driver, it injects the FULL real triple state (regs + work RAM), lets the
# GAME run until the escape NATURALLY dispatches from its real caller (SA-1 entry hook), reads the
# return PC off the 68K stack [a7], and brackets entry -> that return PC ($0710 trap). Re-injecting the
# same triple is deterministic -> the SAME invocation each sample -> tight before/after for codegen.
# Usage: ESC_ENTRY=0x00D1ED ESC_NAME=entry_25110 [N=6] python3 tools/cycle_live.py <triple-dir>
import sys, os, statistics
sys.path.insert(0,'tools'); sys.path.insert(0,'/home/chad/Mesen2/python')
os.environ['DOTNET_ROOT']='/home/chad/.dotnet10'; os.environ['PATH']='/home/chad/.dotnet10:'+os.environ.get('PATH','')
import mesen_mcp.session as _sess; _sess.validate_mesen_build=lambda *a,**k: None
from mesen_mcp import McpSession
ENTRY=int(os.environ['ESC_ENTRY'],0); NAME=os.environ.get('ESC_NAME','escape'); N=int(os.environ.get('N','6'))
TD=sys.argv[1]
regs=open(TD+'/regsA.bin','rb').read(); wramA=open(TD+'/wramA.bin','rb').read()
def be32(d,o): return (d[o]<<24)|(d[o+1]<<16)|(d[o+2]<<8)|d[o+3]
D=[be32(regs,i*4) for i in range(8)]; A=[be32(regs,(8+i)*4) for i in range(7)]
SP=be32(regs,15*4); USP=be32(regs,16*4); SR=be32(regs,17*4)&0xFFFF
Z=(SR>>2)&1;C=SR&1;Nf=(SR>>3)&1;V=(SR>>1)&1;X=(SR>>4)&1
def le32(v): return '%02x%02x%02x%02x'%(v&0xFF,(v>>8)&0xFF,(v>>16)&0xFF,(v>>24)&0xFF)
WN=len(wramA); NEXEN='/home/chad/Nexen/bin/linux-x64/Release/linux-x64/publish/Nexen'; NAT='/tmp/b0_native.mss'
with McpSession(rom='/home/chad/supermn-snes/build/interp.sfc',mesen=NEXEN,port=7538,boot_wait=6.0,socket_timeout=300.0) as m:
    def r16(a,mt='Sa1Memory'): b=m.read_memory(mt,a,2); return b[0]|(b[1]<<8)
    def w16(a,v,mt='Sa1Memory'): m.write_u16(a,v,mt)
    def wh(a,hx,mt='Sa1Memory'): m.write_memory(mt,a,hx)
    def cyc(): return m.get_cpu_state('Sa1').get('cycleCount')
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
        if r16(0x0712): break                          # frozen at $3A92 (GAME_TICK)
    Hin=m.add_exec_hook(ENTRY, cpu_type='Sa1')
    def inject():
        wh(0x00, ''.join(le32(D[i]) for i in range(8)) + ''.join(le32(A[i]) for i in range(7)))
        wh(0x40, le32(0x00003A92)); w16(0x3C, SP&0xFFFF); w16(0x3E,(SP>>16)&0xFF)
        w16(0x60,Z);w16(0x6E,C);w16(0x70,Nf);w16(0x72,V);w16(0xA2,X);w16(0x7C,SR&7 or 7)
        w16(0xA4,USP&0xFFFF);w16(0xA6,(USP>>16)&0xFFFF);w16(0xA8,1);w16(0xAA,0);w16(0x4A,0);w16(0x4C,0)
        w16(0xAC,0x2F60); w16(0x0718,0xFFF8); w16(0x071A,1)
        for o in range(0,WN,0x2000): wh(0x400000+o, wramA[o:o+0x2000].hex(),'snesMemory')
        w16(0x410000,0,'snesMemory'); w16(0x410002,0,'snesMemory')
    def reach_3a92():                                  # re-freeze at the next $3A92 GAME_TICK
        w16(0x0712,0); w16(0x0710,0); w16(0x0714,1); runf(1); w16(0x0714,0)
        for _ in range(60):
            w16(0x0710,0x3A92); w16(0x0716,0); runf(4)
            if r16(0x0712): return True
        return False
    samples=[]; firstret=None
    for k in range(N):
        if k>0: reach_3a92()
        inject()
        w16(0x0712,0); w16(0x0710,0); w16(0x0714,1)    # release -> run the GAME_TICK
        r=m.run_until(max_frames=600, hook_handle=Hin)  # until the escape NATURALLY dispatches
        if r.get('reason')!='hookFired':
            if k==0: print(">>> %s did NOT dispatch in this triple's tick -> not active here"%NAME,flush=True)
            continue
        c0=cyc()
        a7=r16(0x3C)|(r16(0x3E)<<16)                    # 68K SP
        # return PC = [a7] (big-endian 32-bit on the 68K stack); work RAM via snesMemory $40:
        rb=m.read_memory('snesMemory',0x400000+(a7&0xFFFF),4)
        ret_hi=(rb[0]<<8)|rb[1]; ret_lo=(rb[2]<<8)|rb[3]   # 68K big-endian long
        retpc=ret_lo; retbank=ret_hi&0xFF
        if firstret is None: firstret=(hex(a7),hex(ret_hi),hex(ret_lo)); print(">>> a7=%06X return=[%02X%04X]"%(a7,retbank,retpc),flush=True)
        w16(0x0714,0); w16(0x0712,0); w16(0x0710,retpc); w16(0x0716,retbank)   # trap the return
        hit=False
        for _ in range(50):
            runf(2)
            if r16(0x0712): hit=True; break
        if not hit: continue
        d=cyc()-c0
        if 0 < d < 5_000_000: samples.append(d)
    samples.sort()
    print(">>> %s LIVE (triple %s): %d samples: %s"%(NAME,os.path.basename(TD.rstrip('/')),len(samples),samples),flush=True)
    if samples:
        med=statistics.median(samples)
        clust=[s for s in samples if abs(s-med)<=0.05*med]
        print(">>> MEDIAN=%d cyc/invocation  (cluster within 5%%: n=%d/%d)"%(med,len(clust),len(samples)),flush=True)
