#!/usr/bin/env python3
# freerun_rate.py — the HONEST realtime-distance metric (campaign topline): free-run from NAT with
# production gates, count GAME_TICKs via the game's own tick counter (work RAM $1C56, incremented
# once per tick in the GAME_TICK header addq.w #$1,$1c56(a5)) over N SNES frames. ticks/frame = the
# true current speed factor (1.0 = realtime), free of injected-state and pacing-wait artifacts.
# Usage: freerun_rate.py [frames=600]   env: ESC0=1 (gates off), PORT
import sys, os
sys.path.insert(0,'tools'); sys.path.insert(0,'/home/chad/Mesen2/python')
os.environ['DOTNET_ROOT']='/home/chad/.dotnet10'; os.environ['PATH']='/home/chad/.dotnet10:'+os.environ.get('PATH','')
import mesen_mcp.session as _sess; _sess.validate_mesen_build=lambda *a,**k: None
from mesen_mcp import McpSession
N=int(sys.argv[1]) if len(sys.argv)>1 else 600
ESC0=os.environ.get('ESC0')=='1'
NEXEN='/home/chad/Nexen/bin/linux-x64/Release/linux-x64/publish/Nexen'; NAT='/tmp/b0_native.mss'
with McpSession(rom='/home/chad/supermn-snes/build/interp.sfc',mesen=NEXEN,port=int(os.environ.get('PORT','7542')),boot_wait=6.0,socket_timeout=300.0) as m:
    def w16(a,v,mt='Sa1Memory'): m.write_u16(a,v,mt)
    def tick(): b=m.read_memory('snesMemory',0x401C56,2); return (b[0]<<8)|b[1]
    def runf(n,c=300):
        d=0
        while d<n: x=min(c,n-d); m.run_frames(x); d+=x
    m.load_state(NAT); runf(120)
    w16(0x0702,0); w16(0x0704,1)   # NAT is frozen at jh_spin -> release pulse
    w16(0x071A,1); w16(0x073A,1); w16(0x073C,0xA55A); w16(0x0736,0x5EEC)
    if ESC0: w16(0x071A,0); w16(0x073A,0); w16(0x073C,0); w16(0x0736,0)
    runf(60)
    t0=tick(); runf(N); t1=tick()
    d=(t1-t0)&0xFFFF
    print(">>> FREE-RUN: %d ticks / %d frames = %.4f ticks/frame (realtime=1.0; slowdown %.1fx)  ESC0=%s"%(d,N,d/N,N/max(1,d),ESC0),flush=True)
