# Measure the SNES interp's actual GAME-frame rate: load the deterministic gameplay NAT, release the
# lockstep, enable the loop fast-path ($072E), run N real SNES frames, and read the $0760 game-frame
# counter (incremented once per GAME_TICK by the $0818 spin-collapse). game-fps = ticks*60/N.
import sys, os
sys.path.insert(0,'tools'); sys.path.insert(0,'/home/chad/Mesen2/python')
os.environ['DOTNET_ROOT']='/home/chad/.dotnet10'; os.environ['PATH']='/home/chad/.dotnet10:'+os.environ.get('PATH','')
import mesen_mcp.session as _sess; _sess.validate_mesen_build=lambda *a,**k: None
from mesen_mcp import McpSession
NEXEN='/home/chad/Nexen/bin/linux-x64/Release/linux-x64/publish/Nexen'; NAT='/tmp/b0_native.mss'
N=int(sys.argv[1]) if len(sys.argv)>1 else 1200
with McpSession(rom='/home/chad/supermn-snes/build/interp.sfc',mesen=NEXEN,port=7511,boot_wait=6.0,socket_timeout=300.0) as m:
    def r16(a): b=m.read_memory('Sa1Memory',a,2); return b[0]|(b[1]<<8)
    def w16(a,v): m.write_u16(a,v,'Sa1Memory')
    def runf(n,c=300):
        d=0
        while d<n: x=min(c,n-d); m.run_frames(x); d+=x
    runf(300)
    def measure(gate):
        m.load_state(NAT)
        w16(0x0700,0); w16(0x0702,0); w16(0x072E,1); w16(0x071A,gate); w16(0x0760,0); w16(0x0704,1)
        g0=r16(0x0760)
        runf(N)
        ticks=(r16(0x0760)-g0)&0xFFFF
        pc=r16(0x40)|(r16(0x42)<<16)
        fps=ticks*60.0/N
        print(">>> escapes %s ($071A=%d): %d game-frames / %d SNES-frames = %.2f game-fps  (final PC=$%06X)"%(
            'ON ' if gate else 'OFF',gate,ticks,N,fps,pc),flush=True)
        return fps
    foff=measure(0)
    fon =measure(1)
    print("\nspin-collapse: gameplay advances (was sub-0.05 fps with spin interpreted).")
    print("escape speedup: %.2f -> %.2f game-fps (%.2fx from the 25 deployed escapes, ~40%% coverage)"%(foff,fon,fon/foff if foff else 0))
