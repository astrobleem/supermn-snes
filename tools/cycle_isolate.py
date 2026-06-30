#!/usr/bin/env python3
# WIP / BLOCKED — isolated per-escape cycle harness (driver method). The DESIGN is right: inject a
# 68K driver (jsr $TARGET ; bra self) into work RAM, set canonical work-RAM regs, and bracket
# escape-entry (SA-1 hook) -> the unique `bra self` PC. BLOCKER: the interp's $0710 freeze/release
# RESUMES the already-fetched frozen instruction ($3A92 GAME_TICK), so setting $40=DRV does NOT
# redirect the interp to the driver -- it runs the game tick and we catch the escape from the GAME's
# own dispatch (observed: entry fires with $40=$DB4C a0=$F01CFE, not the driver's $FE06/$F03000).
# To finish: need a clean interp redirect to $40 (a small interp-side "jump to $40 on a flag" hook,
# or inject the driver at a real fetch boundary). Until then, per-escape isolation is unsolved; the
# EA-specialization cycle benefit is component-measured (probe_helper_cost: helper 267-1805 vs inline
# ~18 cyc) and correctness-validated (entry_c172 bit-exact). See cycle-budget-realtime-gap memory.
# Isolated per-escape cycle harness (DRIVER method — robust, deterministic, repeatable). Clean
# before/after for any JSR-dispatched escape's per-invocation SA-1 cycle cost. Instead of bracketing
# a live gameplay stream (shared exit symbols / variable work / idle-stall timeouts = the earlier
# multimodal noise), it injects a tiny 68K DRIVER into work RAM:  jsr $TARGET ; bra self  and sets
# CANONICAL work-RAM registers (a0/a1 = known $F0 regions, a5 from the triple). It points the interp
# at the driver, then brackets escape-entry (SA-1 exec-hook) -> the unique `bra self` PC (the $0710
# 68K-PC trap, only this driver has it). Deterministic input -> tight, repeatable per-invocation cost.
# Usage: ESC_ENTRY=0x92DA5D TARGET68K=0x0015B4 [A0=0xF03000 A1=0xF04000] [N=12] python3 tools/cycle_isolate.py [triple]
import sys, os, statistics
sys.path.insert(0,'tools'); sys.path.insert(0,'/home/chad/Mesen2/python')
os.environ['DOTNET_ROOT']='/home/chad/.dotnet10'; os.environ['PATH']='/home/chad/.dotnet10:'+os.environ.get('PATH','')
import mesen_mcp.session as _sess; _sess.validate_mesen_build=lambda *a,**k: None
from mesen_mcp import McpSession
ENTRY=int(os.environ['ESC_ENTRY'],0); TGT=int(os.environ['TARGET68K'],0)
A0=int(os.environ.get('A0','0xF03000'),0); A1=int(os.environ.get('A1','0xF04000'),0)
NAME=os.environ.get('ESC_NAME','escape'); N=int(os.environ.get('N','12'))
DRV=0xFE00   # 68K work-RAM lo16 for the driver (top of bank, unused by the captured state)
TD=sys.argv[1] if len(sys.argv)>1 else '/tmp/supermn-scratch/ce4trip64'
wramA=open(TD+'/wramA.bin','rb').read(); regs=open(TD+'/regsA.bin','rb').read()
def be32(d,o): return (d[o]<<24)|(d[o+1]<<16)|(d[o+2]<<8)|d[o+3]
A5=be32(regs,(8+5)*4)
def le32(v): return '%02x%02x%02x%02x'%(v&0xFF,(v>>8)&0xFF,(v>>16)&0xFF,(v>>24)&0xFF)
NEXEN='/home/chad/Nexen/bin/linux-x64/Release/linux-x64/publish/Nexen'; NAT='/tmp/b0_native.mss'
# 68K driver bytes (big-endian): jsr $00TGT (4EB9 + 32-bit) ; bra.s self (60FE)
drv = bytes([0x4E,0xB9, (TGT>>24)&0xFF,(TGT>>16)&0xFF,(TGT>>8)&0xFF,TGT&0xFF, 0x60,0xFE])
BRA = DRV + 6   # the `bra self` PC (unique exit marker)
with McpSession(rom='/home/chad/supermn-snes/build/interp.sfc',mesen=NEXEN,port=7536,boot_wait=6.0,socket_timeout=300.0) as m:
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
    # base state: inject the triple's work RAM (valid a5-relative game state), the driver, regs
    for o in range(0,len(wramA),0x2000): wh(0x400000+o, wramA[o:o+0x2000].hex(),'snesMemory')
    wh(0x400000+DRV, drv.hex(),'snesMemory')                 # driver code in work RAM
    w16(0x0718,0xFFF8); w16(0x071A,1); w16(0xA8,1); w16(0xAA,0); w16(0x7C,7)
    Hin=m.add_exec_hook(ENTRY, cpu_type='Sa1')
    def setup():                                             # canonical regs + PC=driver
        w16(0x40,DRV); w16(0x42,0)                           # 68K PC = driver
        w16(0x20,A0&0xFFFF); w16(0x22,(A0>>16)&0xFFFF)       # a0
        w16(0x24,A1&0xFFFF); w16(0x26,(A1>>16)&0xFFFF)       # a1
        w16(0x34,A5&0xFFFF); w16(0x36,(A5>>16)&0xFFFF)       # a5
        w16(0x4A,0); w16(0x4C,0)
    samples=[]
    for k in range(N):
        setup()
        w16(0x0712,0); w16(0x0710,0); w16(0x0714,1); runf(1); w16(0x0714,0)   # release one step
        r=m.run_until(max_frames=120, hook_handle=Hin)       # run to the escape entry
        if r.get('reason')!='hookFired':
            if k==0: print(">>> escape did not dispatch (reason=%s) -- check TARGET68K is jah2-escaped"%r.get('reason'),flush=True)
            continue
        c0=cyc()
        # now run until the 68K interp fetches BRA (escape returned to driver) via the $0710 PC-trap
        w16(0x0712,0); w16(0x0710,BRA); w16(0x0716,0)
        hit=False
        for _ in range(30):
            runf(2)
            if r16(0x0712): hit=True; break
        if not hit: continue
        d=cyc()-c0
        if 0 < d < 5_000_000: samples.append(d)
    samples.sort()
    print(">>> %s (a0=%06X a1=%06X): %d samples: %s"%(NAME,A0,A1,len(samples),samples),flush=True)
    if samples:
        med=statistics.median(samples)
        clust=[s for s in samples if abs(s-med)<=0.1*med]
        print(">>> MEDIAN=%d cyc/invocation  (tight cluster n=%d within 10%%: mean=%.0f)"%(med,len(clust),sum(clust)/len(clust) if clust else 0),flush=True)
# Isolated per-escape cycle harness (DRIVER method — robust, deterministic, repeatable). Clean
# before/after for any JSR-dispatched escape's per-invocation SA-1 cycle cost. Instead of bracketing
# a live gameplay stream (shared exit symbols / variable work / idle-stall timeouts = the earlier
# multimodal noise), it injects a tiny 68K DRIVER into work RAM:  jsr $TARGET ; bra self  and sets
# CANONICAL work-RAM registers (a0/a1 = known $F0 regions, a5 from the triple). It points the interp
# at the driver, then brackets escape-entry (SA-1 exec-hook) -> the unique `bra self` PC (the $0710
# 68K-PC trap, only this driver has it). Deterministic input -> tight, repeatable per-invocation cost.
# Usage: ESC_ENTRY=0x92DA5D TARGET68K=0x0015B4 [A0=0xF03000 A1=0xF04000] [N=12] python3 tools/cycle_isolate.py [triple]
import sys, os, statistics
sys.path.insert(0,'tools'); sys.path.insert(0,'/home/chad/Mesen2/python')
os.environ['DOTNET_ROOT']='/home/chad/.dotnet10'; os.environ['PATH']='/home/chad/.dotnet10:'+os.environ.get('PATH','')
import mesen_mcp.session as _sess; _sess.validate_mesen_build=lambda *a,**k: None
from mesen_mcp import McpSession
ENTRY=int(os.environ['ESC_ENTRY'],0); TGT=int(os.environ['TARGET68K'],0)
A0=int(os.environ.get('A0','0xF03000'),0); A1=int(os.environ.get('A1','0xF04000'),0)
NAME=os.environ.get('ESC_NAME','escape'); N=int(os.environ.get('N','12'))
DRV=0xFE00   # 68K work-RAM lo16 for the driver (top of bank, unused by the captured state)
TD=sys.argv[1] if len(sys.argv)>1 else '/tmp/supermn-scratch/ce4trip64'
wramA=open(TD+'/wramA.bin','rb').read(); regs=open(TD+'/regsA.bin','rb').read()
def be32(d,o): return (d[o]<<24)|(d[o+1]<<16)|(d[o+2]<<8)|d[o+3]
A5=be32(regs,(8+5)*4)
def le32(v): return '%02x%02x%02x%02x'%(v&0xFF,(v>>8)&0xFF,(v>>16)&0xFF,(v>>24)&0xFF)
NEXEN='/home/chad/Nexen/bin/linux-x64/Release/linux-x64/publish/Nexen'; NAT='/tmp/b0_native.mss'
# 68K driver bytes (big-endian): jsr $00TGT (4EB9 + 32-bit) ; bra.s self (60FE)
drv = bytes([0x4E,0xB9, (TGT>>24)&0xFF,(TGT>>16)&0xFF,(TGT>>8)&0xFF,TGT&0xFF, 0x60,0xFE])
BRA = DRV + 6   # the `bra self` PC (unique exit marker)
with McpSession(rom='/home/chad/supermn-snes/build/interp.sfc',mesen=NEXEN,port=7536,boot_wait=6.0,socket_timeout=300.0) as m:
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
    # base state: inject the triple's work RAM (valid a5-relative game state), the driver, regs
    for o in range(0,len(wramA),0x2000): wh(0x400000+o, wramA[o:o+0x2000].hex(),'snesMemory')
    wh(0x400000+DRV, drv.hex(),'snesMemory')                 # driver code in work RAM
    w16(0x0718,0xFFF8); w16(0x071A,1); w16(0xA8,1); w16(0xAA,0); w16(0x7C,7)
    Hin=m.add_exec_hook(ENTRY, cpu_type='Sa1')
    def setup():                                             # canonical regs + PC=driver
        w16(0x40,DRV); w16(0x42,0)                           # 68K PC = driver
        w16(0x20,A0&0xFFFF); w16(0x22,(A0>>16)&0xFFFF)       # a0
        w16(0x24,A1&0xFFFF); w16(0x26,(A1>>16)&0xFFFF)       # a1
        w16(0x34,A5&0xFFFF); w16(0x36,(A5>>16)&0xFFFF)       # a5
        w16(0x4A,0); w16(0x4C,0)
    samples=[]
    for k in range(N):
        setup()
        w16(0x0712,0); w16(0x0710,0); w16(0x0714,1); runf(1); w16(0x0714,0)   # release one step
        r=m.run_until(max_frames=120, hook_handle=Hin)       # run to the escape entry
        if r.get('reason')!='hookFired':
            if k==0: print(">>> escape did not dispatch (reason=%s) -- check TARGET68K is jah2-escaped"%r.get('reason'),flush=True)
            continue
        c0=cyc()
        # now run until the 68K interp fetches BRA (escape returned to driver) via the $0710 PC-trap
        w16(0x0712,0); w16(0x0710,BRA); w16(0x0716,0)
        hit=False
        for _ in range(30):
            runf(2)
            if r16(0x0712): hit=True; break
        if not hit: continue
        d=cyc()-c0
        if 0 < d < 5_000_000: samples.append(d)
    samples.sort()
    print(">>> %s (a0=%06X a1=%06X): %d samples: %s"%(NAME,A0,A1,len(samples),samples),flush=True)
    if samples:
        med=statistics.median(samples)
        clust=[s for s in samples if abs(s-med)<=0.1*med]
        print(">>> MEDIAN=%d cyc/invocation  (tight cluster n=%d within 10%%: mean=%.0f)"%(med,len(clust),sum(clust)/len(clust) if clust else 0),flush=True)
