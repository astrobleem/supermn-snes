# Tick-level ON-vs-OFF differential on the DETERMINISTIC native base. Run exactly one real game-tick
# from the NAT (frozen at the jh_spin GAME_TICK boundary) with escapes ON ($071A=1) vs OFF (interp,
# $071A=0), and diff the resulting $40 work RAM + $41 video shadow. ON==OFF => every escape that fired
# this tick is bit-exact vs the interpreter (the reference), in the REAL execution context -- handles
# video / stack-args / bridges / however a function is reached, no per-function captures needed.
# Counts which escapes fired (their $072x counters) so a never-fired (e.g. jmp-reached) escape is visible.
import sys, os
sys.path.insert(0,'tools'); sys.path.insert(0,'/home/chad/Mesen2/python')
os.environ['DOTNET_ROOT']='/home/chad/.dotnet10'; os.environ['PATH']='/home/chad/.dotnet10:'+os.environ.get('PATH','')
import mesen_mcp.session as _sess; _sess.validate_mesen_build=lambda *a,**k: None
from mesen_mcp import McpSession
NEXEN='/home/chad/Nexen/bin/linux-x64/Release/linux-x64/publish/Nexen'; NAT='/tmp/b0_native.mss'
with McpSession(rom='/home/chad/supermn-snes/build/interp.sfc',mesen=NEXEN,port=7515,boot_wait=6.0,socket_timeout=300.0) as m:
    def r16(a,mt='Sa1Memory'): b=m.read_memory(mt,a,2); return b[0]|(b[1]<<8)
    def w16(a,v,mt='Sa1Memory'): m.write_u16(a,v,mt)
    def rd(a,n,mt='Sa1Memory'): return bytes(m.read_memory(mt,a,n))
    def runf(n,c=300):
        d=0
        while d<n: x=min(c,n-d); m.run_frames(x); d+=x
    runf(400)
    def one_tick(gate):
        # NAT is frozen at jh_spin MID-jsr-to-GAME_TICK ($3A92, called from $0708; the return $070E is
        # already pushed). Releasing as-is just re-fetches $0708 and re-freezes (0 instr). So: set PC =
        # $3A92 (continue INTO GAME_TICK), DISARM the lockstep ($0700=0), and trap at the GAME_TICK
        # return R=[a7] via the debug-freeze -> runs exactly one GAME_TICK.
        m.load_state(NAT)
        a7=r16(0x3C)|(r16(0x3E)<<16)
        rb=rd(0x400000|(a7&0xFFFF),4,'snesMemory'); R=(rb[0]<<24)|(rb[1]<<16)|(rb[2]<<8)|rb[3]   # [a7]=return (big-endian)
        w16(0x40,0x3A92); w16(0x42,0x0000)                       # PC = GAME_TICK entry
        w16(0x0700,0); w16(0x072E,1); w16(0x071A,gate)
        w16(0x0712,0); w16(0x0710,R&0xFFFF); w16(0x0716,(R>>16)&0xFFFF); w16(0x0702,0); w16(0x0704,1)
        ok=False
        for _ in range(80):
            runf(10)
            if r16(0x0712): ok=True; break          # trapped at GAME_TICK return = one tick done
        w40=rd(0x400000,0x10000,'snesMemory'); w41=rd(0x410000,0x8000,'snesMemory')
        return ok,w40,w41,R,a7&0xFFFF
    ok0,o40,o41,R0,a7=one_tick(0)   # OFF (interp reference)
    ok1,n40,n41,R1,_=one_tick(1)    # ON  (escapes)
    print("GAME_TICK return R=$%06X ; OFF trapped=%s ON trapped=%s"%(R0,ok0,ok1),flush=True)
    # Split $40 diffs: a BRIDGED escape pushes $00FE sentinel returns to the 68K stack (vs the interp's
    # real returns); after the callees pop them, those bytes sit BELOW a7 (dead/transient stack) and
    # legitimately differ. Only LIVE state (everything outside the transient-stack window just below a7)
    # must match. Window = [a7-0x400, a7) (the active stack working area; game data lives elsewhere).
    stk_lo=(a7-0x400)&0xFFFF
    ds=[i for i in range(0x10000) if o40[i]!=n40[i]]
    live=[i for i in ds if not (stk_lo<=i<a7)]; stack=[i for i in ds if stk_lo<=i<a7]
    d41=sum(1 for i in range(0x8000) if o41[i]!=n41[i])
    print("ON-vs-OFF  $40 diff: %d live + %d transient-stack(<a7=$%04X) ; $41 video-shadow diff=%d"
          %(len(live),len(stack),a7,d41),flush=True)
    if live:
        print("  first LIVE $40 diffs: %s"%["$F0%04X(off=%02X on=%02X)"%(i,o40[i],n40[i]) for i in live[:12]],flush=True)
    green = ok0 and ok1 and len(live)==0 and d41==0
    print(">>>", "GREEN -- escapes bit-exact vs interp over one tick%s"%(" (%d benign stack bytes ignored)"%len(stack) if stack else "")
          if green else "RED -- live$40diff=%d $41diff=%d (froze off=%s on=%s)"%(len(live),d41,ok0,ok1),flush=True)
