#!/usr/bin/env python3
# Clean cycles-per-interp-instruction over a LONG free-run span (no per-tick traps -> no overshoot
# noise). Boots b0_native, releases the jh_spin freeze, runs into steady execution, then free-runs a
# big window measuring (SA-1 cycleCount delta) / (interp instr-counter $4A/$4C delta). cycles/instr is
# an interp property ~independent of attract-vs-gameplay. Optional LH072E to toggle loop_hook.
# Usage: [LH072E=0|1] python3 tools/cycle_rate.py [warm_frames=200] [span_frames=400]
import sys, os
sys.path.insert(0,'tools'); sys.path.insert(0,'/home/chad/Mesen2/python')
os.environ['DOTNET_ROOT']='/home/chad/.dotnet10'; os.environ['PATH']='/home/chad/.dotnet10:'+os.environ.get('PATH','')
import mesen_mcp.session as _sess; _sess.validate_mesen_build=lambda *a,**k: None
from mesen_mcp import McpSession
NEXEN='/home/chad/Nexen/bin/linux-x64/Release/linux-x64/publish/Nexen'; NAT='/tmp/b0_native.mss'
WARM=int(sys.argv[1]) if len(sys.argv)>1 else 200
SPAN=int(sys.argv[2]) if len(sys.argv)>2 else 400
with McpSession(rom='/home/chad/supermn-snes/build/interp.sfc',mesen=NEXEN,port=7532,boot_wait=6.0,socket_timeout=300.0) as m:
    def r16(a,mt='Sa1Memory'): b=m.read_memory(mt,a,2); return b[0]|(b[1]<<8)
    def w16(a,v,mt='Sa1Memory'): m.write_u16(a,v,mt)
    def cyc(): return m.get_cpu_state('Sa1').get('cycleCount')
    def runf(n,c=300):
        d=0
        while d<n: x=min(c,n-d); m.run_frames(x); d+=x
    m.load_state(NAT); runf(120)
    w16(0x0700,0); w16(0x071A,0); w16(0x0712,0); w16(0x0710,0); w16(0x0704,1)   # release freeze
    if os.environ.get('LH072E') is not None: w16(0x072E,int(os.environ['LH072E'],0))
    runf(WARM)                                  # warm into steady execution
    # measure window: reset interp instr counter + game-frame counter, snapshot cycles
    w16(0x4A,0); w16(0x4C,0); w16(0x0760,0)
    c0=cyc(); g0=r16(0x0760)
    runf(SPAN)
    c1=cyc(); g1=r16(0x0760)
    instr=r16(0x4A)|(r16(0x4C)<<16)
    dcyc=c1-c0; ticks=g1-g0
    lh=os.environ.get('LH072E','(default on)')
    print(">>> LH072E=%s  span=%d frames"%(lh,SPAN),flush=True)
    print(">>> SA-1 cycles=%d  interp instr=%d  game-ticks(0760)=%d"%(dcyc,instr,ticks),flush=True)
    if instr: print(">>> cycles / interp-instr = %.1f"%(dcyc/instr),flush=True)
    if ticks: print(">>> cycles / game-tick    = %.0f   (60fps budget = 179000)"%(dcyc/ticks),flush=True)
    if ticks: print(">>> interp-instr / tick   = %.0f"%(instr/ticks),flush=True)
