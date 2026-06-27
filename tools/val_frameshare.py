# Validate a FRAME-SHARING leaf (reads caller's a6 frame, no own link) that val_synth can't (wrong
# frame) and val_tick can't (global-gate skew). Capture the CORRECT entry state (regfile+64KB+$41)
# from the gf260 tick at the fn's entry (debug-freeze, gate off), then do an ISOLATED synthetic-jsr
# ON vs OFF from that captured state. Both start identical -> ON==OFF proves escape==interp.
import sys, os, json
sys.path.insert(0,'tools'); sys.path.insert(0,'/home/chad/Mesen2/python')
os.environ['DOTNET_ROOT']='/home/chad/.dotnet10'; os.environ['PATH']='/home/chad/.dotnet10:'+os.environ.get('PATH','')
import mesen_mcp.session as _sess; _sess.validate_mesen_build=lambda *a,**k: None
from mesen_mcp import McpSession
S='/tmp/claude-1000/-home-chad-supermn-snes/bc5e5a48-495f-47e6-9724-405edc2118da/scratchpad'
TGT=int(sys.argv[1],16)
regs=open(S+'/regsA.bin','rb').read(); wramA=open(S+'/wramA.bin','rb').read()
def be32(d,o): return (d[o]<<24)|(d[o+1]<<16)|(d[o+2]<<8)|d[o+3]
D=[be32(regs,i*4) for i in range(8)]; A=[be32(regs,(8+i)*4) for i in range(7)]+[be32(regs,15*4)]; USP=be32(regs,16*4)
def le32(v): return '%02x%02x%02x%02x'%(v&0xFF,(v>>8)&0xFF,(v>>16)&0xFF,(v>>24)&0xFF)
NEXEN='/home/chad/Nexen/bin/linux-x64/Release/linux-x64/publish/Nexen'
cpu=json.load(open('/tmp/b0_cpu.json')); iram=open('/tmp/b0_iram.bin','rb').read(); bwram=open('/tmp/b0_bwram.bin','rb').read()
SCRATCH=0xFF00; jsrb=bytes([0x4E,0xB9,0x00,0x00,(TGT>>8)&0xFF,TGT&0xFF])
with McpSession(rom='/home/chad/supermn-snes/build/interp.sfc',mesen=NEXEN,port=7475,boot_wait=6.0,socket_timeout=300.0) as m:
    def r16(a,mt='Sa1Memory'): b=m.read_memory(mt,a,2); return b[0]|(b[1]<<8)
    def w16(a,v,mt='Sa1Memory'): m.write_u16(a,v,mt)
    def wh(a,hx,mt='Sa1Memory'): m.write_memory(mt,a,hx)
    def rd(a,n,mt='Sa1Memory'): return bytes(m.read_memory(mt,a,n))
    def runf(n,c=300):
        d=0
        while d<n: x=min(c,n-d); m.run_frames(x); d+=x
    def setcpu(st): m.tool("set_cpu_state",{k:st[k] for k in ('cpuType','pc','k','a','x','y','sp','d','dbr','ps','emulationMode') if k in st})
    def transplant():
        for o in range(0,len(iram),0x400): wh(0x0000+o,iram[o:o+0x400].hex())
        for o in range(0,len(bwram),0x4000): wh(0x400000+o,bwram[o:o+0x4000].hex(),'snesMemory')
        setcpu(cpu['sa1']); setcpu(cpu['snes'])
    def freezeB0():
        transplant(); w16(0x0700,1)
        for _ in range(10):
            if r16(0x0702): break
            runf(60)
    def inject_tickstart():
        wh(0x00,''.join(le32(D[i]) for i in range(8))+''.join(le32(A[i]) for i in range(8))); wh(0x40,le32(0x00003A92))
        w16(0x60,1);w16(0x6E,0);w16(0x70,0);w16(0x72,0);w16(0xA2,0);w16(0x7C,7);w16(0xA4,USP&0xFFFF);w16(0xA6,(USP>>16)&0xFFFF);w16(0xA8,1);w16(0xAA,0);w16(0x4A,0);w16(0x4C,0);w16(0xAC,0x7000)
        w16(0x0718,0xFFF8); wh(0x400000,wramA.hex(),'snesMemory'); w16(0x410000,0x0100,'snesMemory'); w16(0x410002,0x0100,'snesMemory')
    print("[Nexen] boot+transplant...",flush=True); runf(600); freezeB0()
    # PHASE 1: capture the fn's entry state from the gf260 tick (gate off, debug-freeze at TGT)
    inject_tickstart()
    w16(0x071A,0); w16(0x0712,0); w16(0x0710,TGT&0xFFFF); w16(0x0716,(TGT>>16)&0xFFFF); w16(0x0702,0); w16(0x0704,1)
    hit=0
    for _ in range(60):
        runf(20)
        if r16(0x0712): hit=1; break
        if r16(0x0702): break
    if not hit:
        print("[%06X] NOT reached by gf260 tick (can't capture frame) -> SKIP"%TGT,flush=True); sys.exit(2)
    cap_dp=rd(0x00,0x40)               # regfile $00-$3F (entry context incl. a6 frame ptr)
    cap_fl=[r16(a) for a in (0x60,0x6E,0x70,0x72,0xA2,0x7C,0xA4,0xA6,0xA8,0xAA,0xAC)]
    cap_w=rd(0x400000,0x10000,'snesMemory'); cap_41=rd(0x410000,0x8000,'snesMemory')
    print("[%06X] captured entry: a6=%08X a5=%08X"%(TGT, be32(cap_dp,0x3C)&0 or (cap_dp[0x30]|cap_dp[0x31]<<8|cap_dp[0x32]<<16|cap_dp[0x33]<<24), cap_dp[0x34]|cap_dp[0x35]<<8|cap_dp[0x36]<<16|cap_dp[0x37]<<24),flush=True)
    a7=cap_dp[0x3C]|cap_dp[0x3D]<<8|cap_dp[0x3E]<<16|cap_dp[0x3F]<<24
    # PHASE 2: isolated synthetic-jsr ON/OFF from the captured entry state
    def run(hook):
        freezeB0()
        wh(0x00, cap_dp.hex())                                  # restore entry regfile
        for a,v in zip((0x60,0x6E,0x70,0x72,0xA2,0x7C,0xA4,0xA6,0xA8,0xAA,0xAC), cap_fl): w16(a,v)
        w16(0x0718,0xFFF8)
        for o in range(0,0x10000,0x4000): wh(0x400000+o,cap_w[o:o+0x4000].hex(),'snesMemory')
        for o in range(0,0x8000,0x4000): wh(0x410000+o,cap_41[o:o+0x4000].hex(),'snesMemory')
        wh(0x400000+SCRATCH, jsrb.hex(),'snesMemory')           # synthetic jsr.l TGT at $F0FF00
        w16(0x40,SCRATCH); w16(0x42,0x00F0)
        w16(0x071A,hook); w16(0x0712,0); w16(0x0710,SCRATCH+6); w16(0x0716,0x00F0); w16(0x0702,0); w16(0x0704,1)
        for _ in range(60):
            runf(20)
            if r16(0x0712) or r16(0x0702): break
        return r16(0x0712), rd(0x00,0x40), rd(0x400000,0x10000,'snesMemory'), rd(0x410000,0x8000,'snesMemory')
    of,orf,o40,o41=run(0); nf,nrf,n40,n41=run(1)
    RN=['d0','d1','d2','d3','d4','d5','d6','d7','a0','a1','a2','a3','a4','a5','a6','a7']
    def g(b,s): i=s*4; return b[i]|b[i+1]<<8|b[i+2]<<16|b[i+3]<<24
    rdiff=[RN[s] for s in range(16) if g(orf,s)!=g(nrf,s)]
    ex=set(range(SCRATCH,SCRATCH+8))|set(range((a7-4)&0xFFFF,((a7-4)&0xFFFF)+4))
    bd40=sum(1 for i in range(0x10000) if i not in ex and o40[i]!=n40[i]); bd41=sum(1 for i in range(0x8000) if o41[i]!=n41[i])
    print("[frameshare %06X] OFF froze=%d ON froze=%d ; regdiff=%s ; $40diff=%d ; $41diff=%d"%(TGT,of,nf,rdiff or 'NONE',bd40,bd41),flush=True)
    dd=[(i,o40[i],n40[i]) for i in range(0x10000) if i not in ex and o40[i]!=n40[i]]
    print("  $40 diffs (off:off_val/on_val):", [('%04X:%02X/%02X'%d) for d in dd[:8]],flush=True)
    print(">>>", "GREEN-frameshare $%06X bit-exact"%TGT if (not rdiff and bd40==0 and bd41==0 and nf and of) else "RED",flush=True)
