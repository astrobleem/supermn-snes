#!/usr/bin/env python3
# Isolated per-escape cycle harness (DRIVER + interp-REDIRECT) — PRECISE, deterministic, repeatable
# per-invocation SA-1 cycle cost for any JSR-dispatched escape. Clean before/after for every codegen
# change. Beats the earlier multimodal bracket noise by controlling the whole thing:
#   1. DRIVER: inject a 68K driver into work RAM:  jsr $TARGET ; bra self  . PC bank = $00F0 so the
#      interp fetches it as code from work RAM (ifetch handles $42==$00F0, the C-Chip-replay path).
#   2. REDIRECT: the interp's dbg_fetch honors $0738==$A5A5 -> on freeze-release it re-fetches from
#      $40/$42 instead of executing the frozen opcode, so we point the interp at the driver.
#   3. CANONICAL INPUT: a0/a1/a5/a7 = fixed work-RAM addrs each sample -> identical work every time.
#   4. UNIQUE EXIT: bracket escape-entry (SA-1 hook) -> the driver's `bra self` PC ($00F0:FE06) via the
#      $0710 PC-trap. Only this driver has that PC. Deterministic input -> a TIGHT, repeatable number.
# Usage: ESC_ENTRY=0x92DA5D TARGET68K=0x0015B4 [A0=.. A1=.. A7=.. N=12] python3 tools/cycle_isolate.py [triple]
import sys, os, statistics
sys.path.insert(0,'tools'); sys.path.insert(0,'/home/chad/Mesen2/python')
os.environ['DOTNET_ROOT']='/home/chad/.dotnet10'; os.environ['PATH']='/home/chad/.dotnet10:'+os.environ.get('PATH','')
import mesen_mcp.session as _sess; _sess.validate_mesen_build=lambda *a,**k: None
from mesen_mcp import McpSession
ENTRY=int(os.environ['ESC_ENTRY'],0); TGT=int(os.environ['TARGET68K'],0)
A0=int(os.environ.get('A0','0xF03000'),0); A1=int(os.environ.get('A1','0xF04000'),0); A7=int(os.environ.get('A7','0xF01700'),0)
NAME=os.environ.get('ESC_NAME','escape'); N=int(os.environ.get('N','12'))
JMPMODE=os.environ.get('DRIVER_JMP') is not None         # jmp(a0) dispatch (jmp-state/coroutine) vs jsr (jah2)
DRV=0xFE00; DRVBANK=0x00F0
# EXIT: where the escape lands when done. jsr-leaf returns to the driver's `bra self` ($FE06); a
# jmp-state/coroutine escape yields to a fixed PC (e.g. c172 -> $C170). Set EXIT_PC / EXIT_BANK for those.
EXITPC=int(os.environ.get('EXIT_PC', str(DRV+6)),0); EXITBANK=int(os.environ.get('EXIT_BANK', '0x00F0'),0)
TD=sys.argv[1] if len(sys.argv)>1 else '/tmp/supermn-scratch/ce4trip64'
regs=open(TD+'/regsA.bin','rb').read(); wramA=open(TD+'/wramA.bin','rb').read()
def be32(d,o): return (d[o]<<24)|(d[o+1]<<16)|(d[o+2]<<8)|d[o+3]
A5=be32(regs,(8+5)*4)
NEXEN='/home/chad/Nexen/bin/linux-x64/Release/linux-x64/publish/Nexen'; NAT='/tmp/b0_native.mss'
if JMPMODE:                                              # jmp (a0) -> ojmp_hook -> xlat (a0 set to TGT below)
    drv = bytes([0x4E,0xD0])
else:                                                    # jsr $00TGT ; bra.s self
    drv = bytes([0x4E,0xB9,(TGT>>24)&0xFF,(TGT>>16)&0xFF,(TGT>>8)&0xFF,TGT&0xFF, 0x60,0xFE])
BRA=EXITPC
with McpSession(rom='/home/chad/supermn-snes/build/interp.sfc',mesen=NEXEN,port=7537,boot_wait=6.0,socket_timeout=300.0) as m:
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
    # stay frozen at the $0708 IRQ entry (escape-safe; $3A92 is itself escaped with $071A=1 so it can
    # never be trapped). We redirect from this freeze. Inject work RAM + driver while frozen.
    for o in range(0,len(wramA),0x2000): wh(0x400000+o, wramA[o:o+0x2000].hex(),'snesMemory')
    wh(0x400000+DRV, drv.hex(),'snesMemory')           # driver into work RAM
    w16(0x0718,0xFFF8); w16(0xA8,1); w16(0xAA,0); w16(0x7C,7)
    Hin=m.add_exec_hook(ENTRY, cpu_type='Sa1')
    def setup():
        w16(0x40,DRV); w16(0x42,DRVBANK)
        a0 = TGT if JMPMODE else A0                       # jmp(a0) mode: a0 = the dispatch target PC
        w16(0x20,a0&0xFFFF); w16(0x22,(a0>>16)&0xFFFF)
        w16(0x24,A1&0xFFFF); w16(0x26,(A1>>16)&0xFFFF)
        w16(0x34,A5&0xFFFF); w16(0x36,(A5>>16)&0xFFFF)
        w16(0x3C,A7&0xFFFF); w16(0x3E,(A7>>16)&0xFFFF)
        w16(0x4A,0); w16(0x4C,0)
    samples=[]; diag=[]
    for k in range(N):
        setup()
        w16(0x0738,0xA5A5)                             # redirect magic -> re-fetch from $40 on release
        w16(0x0712,0); w16(0x0710,0); w16(0x0714,1)    # release current freeze -> redirect -> driver
        r=m.run_until(max_frames=20, hook_handle=Hin)  # run to escape entry (do NOT runf first -> would eat it)
        if k==0: diag.append(('entry_reason',r.get('reason'),'$40=%04X'%r16(0x40),'$42=%04X'%r16(0x42)))
        if r.get('reason')!='hookFired': continue
        c0=cyc()
        w16(0x0714,0); w16(0x0712,0); w16(0x0710,BRA); w16(0x0716,EXITBANK)   # arm exit trap (bra-self or yield PC)
        hit=False
        for _ in range(40):
            runf(2)
            if r16(0x0712): hit=True; break
        if k==0: diag.append(('exit_hit',hit,'$40=%04X'%r16(0x40),'$42=%04X'%r16(0x42)))
        if not hit: continue
        d=cyc()-c0
        if 0 < d < 5_000_000: samples.append(d)
    if diag: print(">>> diag:", diag, flush=True)
    samples.sort()
    print(">>> %s (a0=%06X a1=%06X N=%d): %d samples: %s"%(NAME,A0,A1,N,len(samples),samples),flush=True)
    if samples:
        med=statistics.median(samples)
        clust=[s for s in samples if abs(s-med)<=0.05*med]
        print(">>> MEDIAN=%d cyc/invocation  (cluster within 5%%: n=%d/%d mean=%.0f)"%(med,len(clust),len(samples),sum(clust)/len(clust) if clust else med),flush=True)
