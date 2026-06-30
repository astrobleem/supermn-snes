#!/usr/bin/env python3
# Probe: does Nexen expose a usable SA-1 cycleCount? Boot, release the jh_spin freeze, run to
# gameplay, then read get_cpu_state('Sa1')['cycleCount'] before/after run_frames and confirm it
# advances monotonically (and compare 5A22 vs Sa1). Step 0 for the cycle meter (task #5).
import sys, os, json
sys.path.insert(0,'tools'); sys.path.insert(0,'/home/chad/Mesen2/python')
os.environ['DOTNET_ROOT']='/home/chad/.dotnet10'; os.environ['PATH']='/home/chad/.dotnet10:'+os.environ.get('PATH','')
import mesen_mcp.session as _sess; _sess.validate_mesen_build=lambda *a,**k: None
from mesen_mcp import McpSession
NEXEN='/home/chad/Nexen/bin/linux-x64/Release/linux-x64/publish/Nexen'; NAT='/tmp/b0_native.mss'
with McpSession(rom='/home/chad/supermn-snes/build/interp.sfc',mesen=NEXEN,port=7531,boot_wait=6.0,socket_timeout=300.0) as m:
    def w16(a,v,mt='Sa1Memory'): m.write_u16(a,v,mt)
    def cyc(cpu):
        st=m.get_cpu_state(cpu)
        return st.get('cycleCount'), sorted(st.keys())
    m.load_state(NAT); m.run_frames(120)
    w16(0x0700,0); w16(0x0704,1)   # release the jh_spin freeze so the interp actually runs
    m.run_frames(30)
    print(">>> get_cpu_state('Sa1') keys:", cyc('Sa1')[1], flush=True)
    print(">>> get_cpu_state('Snes') keys:", cyc('Snes')[1], flush=True)
    s0,_=cyc('Sa1'); c0,_=cyc('Snes')
    m.run_frames(10)
    s1,_=cyc('Sa1'); c1,_=cyc('Snes')
    m.run_frames(10)
    s2,_=cyc('Sa1'); c2,_=cyc('Snes')
    print(">>> Sa1 cycleCount: %s -> %s -> %s  (d10f: %s, %s)"%(s0,s1,s2, (s1-s0) if (s0 is not None and s1 is not None) else 'n/a', (s2-s1) if (s1 is not None and s2 is not None) else 'n/a'), flush=True)
    print(">>> Snes cycleCount: %s -> %s -> %s (d10f: %s, %s)"%(c0,c1,c2, (c1-c0) if (c0 is not None and c1 is not None) else 'n/a', (c2-c1) if (c1 is not None and c2 is not None) else 'n/a'), flush=True)
    # sanity: per-frame SA-1 cycle delta should be ~constant for a ~10-frame run
    print(">>> VERDICT: SA-1 cycleCount %s"%("USABLE (advances monotonically)" if (s0 is not None and s2 is not None and s2>s1>s0) else "PROBLEM (missing or not advancing)"), flush=True)
