#!/usr/bin/env python3
# Gameplay smoke-test for build/interp.sfc: does one real GAME_TICK actually run + return? Catches a
# build that ASSEMBLES + passes opsweep but breaks the gameplay execution path (e.g. deploy_escape's
# jah2 code-shift silently wrapping a short branch -> the interp sticks at the $0708 jsr, 0 frames).
# Re-captures the NAT first (it's a build-specific save-state). Exit 0 = OK, 1 = BROKEN.
import sys, os, subprocess
sys.path.insert(0,'tools'); sys.path.insert(0,'/home/chad/Mesen2/python')
os.environ['DOTNET_ROOT']='/home/chad/.dotnet10'; os.environ['PATH']='/home/chad/.dotnet10:'+os.environ.get('PATH','')
NEXEN='/home/chad/Nexen/bin/linux-x64/Release/linux-x64/publish/Nexen'; NAT=os.environ.get('NAT','/tmp/b0_native.mss')
# 1) re-capture the NAT on the current build (build-specific). A broken build may fail to freeze.
r=subprocess.run([sys.executable,'tools/dump_b0_native.py',NAT],capture_output=True,text=True,timeout=300)
if 'wrote' not in r.stdout:
    print("SMOKE: BROKEN — dump_b0_native could not freeze at jh_spin (gameplay path broken)\n"+r.stdout[-400:]+r.stderr[-400:],flush=True)
    sys.exit(1)
import mesen_mcp.session as _sess; _sess.validate_mesen_build=lambda *a,**k: None
from mesen_mcp import McpSession
with McpSession(rom=os.path.join(os.path.dirname(os.path.abspath(__file__)),'..','build','interp.sfc'),mesen=NEXEN,port=7521,boot_wait=6.0,socket_timeout=300.0) as m:
    def r16(a): b=m.read_memory('Sa1Memory',a,2); return b[0]|(b[1]<<8)
    def w16(a,v): m.write_u16(a,v,'Sa1Memory')
    def runf(n,c=300):
        d=0
        while d<n: x=min(c,n-d); m.run_frames(x); d+=x
    runf(300); m.load_state(NAT)
    # 2) run one GAME_TICK: PC=$3A92, disarm lockstep, trap at the return; must trap + advance PC.
    a7=r16(0x3C)|(r16(0x3E)<<16)
    rb=m.read_memory('snesMemory',0x400000|(a7&0xFFFF),4); R=(rb[0]<<24)|(rb[1]<<16)|(rb[2]<<8)|rb[3]
    w16(0x40,0x3A92); w16(0x42,0x0000); w16(0x0700,0); w16(0x072E,1); w16(0x071A,1)
    w16(0x0712,0); w16(0x0710,R&0xFFFF); w16(0x0716,(R>>16)&0xFFFF); w16(0x0760,0); w16(0x0702,0); w16(0x0704,1)
    trapped=False
    for _ in range(80):
        runf(10)
        if r16(0x0712): trapped=True; break
    pc=r16(0x40)|(r16(0x42)<<16)
    if trapped:
        print("SMOKE: OK — one GAME_TICK ran + returned to $%06X"%(R&0xFFFFFF),flush=True); sys.exit(0)
    print("SMOKE: BROKEN — GAME_TICK did not return (stuck at $%06X, 0 ticks). Gameplay execution path is broken."%pc,flush=True)
    sys.exit(1)
