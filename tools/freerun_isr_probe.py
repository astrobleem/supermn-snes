#!/usr/bin/env python3
# freerun_isr_probe.py — price the 68K vblank ISR from FREE RUN (the injected-window blind spot:
# lockstep/hle_span ticks never see take_irq because $AC can't expire in a ~200-instr window).
# Free-runs the NAT state with escapes armed, alternates ONE exec-hook (the Nexen global-counter
# gotcha) between take_irq (ISR entry) and op_rte (ISR exit), and reports fires + ISR cyc spans
# normalized per FRAME and per game tick ($40:1C56).
# Usage: freerun_isr_probe.py [frames=600]   env: NAT, PORT
import sys, os
sys.path.insert(0,'tools'); sys.path.insert(0,'/home/chad/Mesen2/python')
os.environ['DOTNET_ROOT']='/home/chad/.dotnet10'; os.environ['PATH']='/home/chad/.dotnet10:'+os.environ.get('PATH','')
import mesen_mcp.session as _sess; _sess.validate_mesen_build=lambda *a,**k: None
from mesen_mcp import McpSession
import re
FRAMES=int(sys.argv[1]) if len(sys.argv)>1 else 600
NEXEN='/home/chad/Nexen/bin/linux-x64/Release/linux-x64/publish/Nexen'
NAT=os.environ.get('NAT','/tmp/b0_native.mss')
syms={m.group(2):int(m.group(1),16) for m in re.finditer(r'00:([0-9A-Fa-f]{4})\s+(\S+)',open('src/interp.sym').read())}
TAKE=syms['take_irq']; RTE=syms['op_rte']
ROM=os.path.join(os.path.dirname(os.path.abspath(__file__)),'..','build','interp.sfc')
print("free-run ISR probe: take_irq=$00%04X op_rte=$00%04X frames=%d"%(TAKE,RTE,FRAMES),flush=True)
with McpSession(rom=ROM,mesen=NEXEN,port=int(os.environ.get('PORT','7549')),boot_wait=6.0,socket_timeout=300.0) as m:
    def r16(a): b=m.read_memory('Sa1Memory',a,2); return b[0]|(b[1]<<8)
    def w16(a,v): m.write_u16(a,v,'Sa1Memory')
    def cyc(): return m.get_cpu_state('Sa1').get('cycleCount')
    def frames(): return m.get_state().get('frameCount') if hasattr(m,'get_state') else None
    def tickctr(): b=m.read_memory('snesMemory',0x401C56,2); return (b[0]<<8)|b[1]
    m.load_state(NAT)
    # release the NAT freeze -> production free-run with escapes armed (the PR-battery gates)
    w16(0x0700,0); w16(0x0702,0); w16(0x0710,0); w16(0x0712,0)
    w16(0x072E,1); w16(0x0704,1)                       # loop_hook on + RUN (the smoke-test release)
    w16(0x071A,1); w16(0x073A,1); w16(0x073C,0xA55A); w16(0x0736,0x5EEC)
    m.run_frames(30)                                   # settle
    c0=cyc(); t0=tickctr(); fires=0; spans=[]; fr=0
    while fr<FRAMES:
        h=m.add_exec_hook(TAKE, cpu_type='Sa1')
        r=m.run_until(max_frames=30, hook_handle=h)
        m.remove_hook(h)
        fr+=30                                          # approx: run_until consumed <=30 frames
        if (r or {}).get('reason')!='hookFired': continue
        fires+=1; ci=cyc()
        h2=m.add_exec_hook(RTE, cpu_type='Sa1')
        r2=m.run_until(max_frames=10, hook_handle=h2)
        m.remove_hook(h2)
        if (r2 or {}).get('reason')=='hookFired': spans.append(cyc()-ci)
    c1=cyc(); t1=tickctr()
    total=sum(spans); n=len(spans)
    print(">>> window=%d cyc, ~%d frames, game ticks=%d"%(c1-c0,FRAMES,t1-t0),flush=True)
    print(">>> take_irq fires=%d (%.2f/frame-approx), ISR spans n=%d avg=%d cyc"%(fires,fires/max(1,FRAMES),n,total//max(1,n)),flush=True)
    if n: print(">>> ISR cost: avg %d cyc/fire -> AT 30FPS (2 fires/tick) = %d cyc/tick of the 358K budget (%.1f%%)"%(total//n,2*(total//n),100*2*(total//n)/358000),flush=True)
    print(">>> spans (first 20):",spans[:20],flush=True)
