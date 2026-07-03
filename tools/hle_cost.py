#!/usr/bin/env python3
# hle_cost.py — SPIN-FREE cycle cost of a native escape body (transpiled OR hand-written HLE), via
# exec-hooks. Brackets ENTRY -> EXIT with add_exec_hook + run_until (the SA-1 stops AT the hook, no
# busy-spin), reading the Sa1 cycleCount at each. This is the ONLY reliable way to measure a sub-tick
# native span: the $0710 fetch-trap busy-spins to end-of-frame (~179K cyc pollution), and the
# whole-tick poke-diff is nondeterministic (~60K/tick B0-staging jitter) for effects smaller than that.
# Interp-side cost is NOT measurable this way (shared iloop has no distinct SA-1 addr) -- compare the
# native number against the interpreter baseline you already have (see MAIN_PLANNING_HANDOFF.md).
# Usage: hle_cost.py <triple> <ENTRY_hex24> <EXIT_hex24>   e.g. hle_cost.py .../ce4trip64 94B188 94B20E
import sys, os
sys.path.insert(0,'tools'); sys.path.insert(0,'/home/chad/Mesen2/python')
os.environ['DOTNET_ROOT']='/home/chad/.dotnet10'; os.environ['PATH']='/home/chad/.dotnet10:'+os.environ.get('PATH','')
import mesen_mcp.session as _sess; _sess.validate_mesen_build=lambda *a,**k: None
from mesen_mcp import McpSession
TD=sys.argv[1]; ENTRY=int(sys.argv[2],16); EXITA=int(sys.argv[3],16)
wramA=open(TD+'/wramA.bin','rb').read(); regs=open(TD+'/regsA.bin','rb').read()
def be32(d,o): return (d[o]<<24)|(d[o+1]<<16)|(d[o+2]<<8)|d[o+3]
D=[be32(regs,i*4) for i in range(8)]; A=[be32(regs,(8+i)*4) for i in range(7)]
SP=be32(regs,15*4); USP=be32(regs,16*4); SR=be32(regs,17*4)&0xFFFF
Z=(SR>>2)&1;C=SR&1;Nf=(SR>>3)&1;V=(SR>>1)&1;X=(SR>>4)&1
def le32(v): return '%02x%02x%02x%02x'%(v&0xFF,(v>>8)&0xFF,(v>>16)&0xFF,(v>>24)&0xFF)
WN=len(wramA); NEXEN='/home/chad/Nexen/bin/linux-x64/Release/linux-x64/publish/Nexen'; NAT='/tmp/b0_native.mss'
print("triple %s  ENTRY=$%06X EXIT=$%06X"%(TD,ENTRY,EXITA),flush=True)
with McpSession(rom='/home/chad/supermn-snes/build/interp.sfc',mesen=NEXEN,port=int(os.environ.get('PORT','7542')),boot_wait=6.0,socket_timeout=300.0) as m:
    def r16(a): b=m.read_memory('Sa1Memory',a,2); return b[0]|(b[1]<<8)
    def w16(a,v,mt='Sa1Memory'): m.write_u16(a,v,mt)
    def wh(a,hx,mt='Sa1Memory'): m.write_memory(mt,a,hx)
    def cyc(): return m.get_cpu_state('Sa1').get('cycleCount')
    def instr(): return r16(0x4A)|(r16(0x4C)<<16)
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
    w16(0x073A,1); w16(0x073C,0xA55A); w16(0x0736,0x5EEC)   # production gates on (match the shipped tick)
    for o in range(0,WN,0x2000): wh(0x400000+o, wramA[o:o+0x2000].hex(),'snesMemory')
    w16(0x410000,0,'snesMemory'); w16(0x410002,0,'snesMemory')
    h1=m.add_exec_hook(ENTRY, cpu_type='Sa1'); h2=m.add_exec_hook(EXITA, cpu_type='Sa1')
    w16(0x0712,0); w16(0x0710,0); w16(0x0714,1); runf(1); w16(0x0714,0)   # release $3A92
    r1=m.run_until(max_frames=600, hook_handle=h1); ce=cyc(); ie=instr()
    r2=m.run_until(max_frames=600, hook_handle=h2); cx=cyc(); ix=instr()
    ok = (r1 or {}).get('reason')=='hookFired' and (r2 or {}).get('reason')=='hookFired'
    print("entry fired=%s exit fired=%s"%((r1 or {}).get('reason'),(r2 or {}).get('reason')),flush=True)
    print(">>> NATIVE BODY COST = %s cyc  (interp-instr delta over it = %d; ~0 confirms it ran native)"%(
        (cx-ce) if ok else 'N/A (a hook did not fire -- check ENTRY/EXIT addrs + that it runs in this triple)', ix-ie),flush=True)
