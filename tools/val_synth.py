# Synthetic-jsr escape validator: from the consistent gf260 base, FORCE a jsr.l TARGET (so the
# function runs even if gf260's tick never calls it), then compare ON(escape) vs OFF(interp) at the
# return. Both start from the identical injected base -> ON==OFF proves escape==interp bit-exact.
# Scratch jsr lives at work-RAM $F0FF00; trap (debug-freeze) at $F0FF06.
import sys, os, json
sys.path.insert(0,'tools'); sys.path.insert(0,'/home/chad/Mesen2/python')
os.environ['DOTNET_ROOT']='/home/chad/.dotnet10'; os.environ['PATH']='/home/chad/.dotnet10:'+os.environ.get('PATH','')
import mesen_mcp.session as _sess; _sess.validate_mesen_build=lambda *a,**k: None
from mesen_mcp import McpSession
S='/tmp/claude-1000/-home-chad-supermn-snes/bc5e5a48-495f-47e6-9724-405edc2118da/scratchpad'
TARGET=int(sys.argv[1],16)
regs=open(S+'/regsA.bin','rb').read(); wramA=open(S+'/wramA.bin','rb').read()
def be32(d,o): return (d[o]<<24)|(d[o+1]<<16)|(d[o+2]<<8)|d[o+3]
D=[be32(regs,i*4) for i in range(8)]; A=[be32(regs,(8+i)*4) for i in range(7)]+[be32(regs,15*4)]; USP=be32(regs,16*4)
def le32(v): return '%02x%02x%02x%02x'%(v&0xFF,(v>>8)&0xFF,(v>>16)&0xFF,(v>>24)&0xFF)
NEXEN='/home/chad/Nexen/bin/linux-x64/Release/linux-x64/publish/Nexen'
cpu=json.load(open('/tmp/b0_cpu.json')); iram=open('/tmp/b0_iram.bin','rb').read(); bwram=open('/tmp/b0_bwram.bin','rb').read()
# synthetic jsr.l TARGET at $F0FF00 ; bytes 4E B9 00 00 hi lo (68K big-endian)
SCRATCH=0xFF00
jsrbytes=bytes([0x4E,0xB9,0x00,0x00,(TARGET>>8)&0xFF,TARGET&0xFF])
with McpSession(rom='/home/chad/supermn-snes/build/interp.sfc',mesen=NEXEN,port=7465,boot_wait=6.0,socket_timeout=300.0) as m:
    def r16(a,mt='Sa1Memory'): b=m.read_memory(mt,a,2); return b[0]|(b[1]<<8)
    def w16(a,v,mt='Sa1Memory'): m.write_u16(a,v,mt)
    def wh(a,hx,mt='Sa1Memory'): m.write_memory(mt,a,hx)
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
    def inject(hook):
        # regfile = gf260 D/A; work RAM = gf260 16KB overlay (consistent base)
        wh(0x00,''.join(le32(D[i]) for i in range(8))+''.join(le32(A[i]) for i in range(8)))
        w16(0x60,1); w16(0x6E,0); w16(0x70,0); w16(0x72,0); w16(0xA2,0)
        w16(0x7C,7); w16(0xA4,USP&0xFFFF); w16(0xA6,(USP>>16)&0xFFFF); w16(0xA8,1); w16(0xAA,0); w16(0x4A,0); w16(0x4C,0); w16(0xAC,0x7000)
        w16(0x0718,0xFFF8); wh(0x400000,wramA.hex(),'snesMemory'); w16(0x410000,0x0100,'snesMemory'); w16(0x410002,0x0100,'snesMemory')
        # plant synthetic jsr.l at work-RAM $F0FF00 (=$40:FF00); PC there; trap at +6
        wh(0x400000+SCRATCH, jsrbytes.hex(),'snesMemory')
        w16(0x40,SCRATCH); w16(0x42,0x00F0)
        w16(0x071A,hook); w16(0x0712,0); w16(0x0714,0); w16(0x0710,SCRATCH+6); w16(0x0716,0x00F0)
        w16(0x0702,0); w16(0x0704,1)
    print("[Nexen] boot+transplant...",flush=True); runf(600); freezeB0()
    print("[Nexen] transplant ok PC=$%06X"%(r16(0x40)|(r16(0x42)<<16)),flush=True)
    def run(hook):
        freezeB0(); inject(hook)
        for _ in range(60):
            runf(20)
            if r16(0x0712) or r16(0x0702): break
        return r16(0x0712), bytes(m.read_memory('Sa1Memory',0x00,0x40)), bytes(m.read_memory('snesMemory',0x400000,0x10000)), bytes(m.read_memory('snesMemory',0x410000,0x8000))
    of,orf,o40,o41=run(0); nf,nrf,n40,n41=run(1)
    RN=['d0','d1','d2','d3','d4','d5','d6','d7','a0','a1','a2','a3','a4','a5','a6','a7']
    def rd(b,sl): i=sl*4; return b[i]|(b[i+1]<<8)|(b[i+2]<<16)|(b[i+3]<<24)
    rdiff=[RN[sl] for sl in range(16) if rd(orf,sl)!=rd(nrf,sl)]
    # exclude scratch ($FF00-$FF07) from $40 compare (synthetic jsr + pushed return live there)
    ex=set(range(SCRATCH,SCRATCH+8)) | set(range((A[7]-4)&0xFFFF,((A[7]-4)&0xFFFF)+4))
    bd40=sum(1 for i in range(len(o40)) if i not in ex and o40[i]!=n40[i])
    bd41=sum(1 for i in range(len(o41)) if o41[i]!=n41[i])
    print("[synth $%06X] OFF froze=%d ON froze=%d ; regdiff=%s ; $40diff=%d ; $41diff=%d"%(TARGET,of,nf,rdiff or 'NONE',bd40,bd41),flush=True)
    print(">>>", "GREEN — escape $%06X == interp (synthetic-jsr ON/OFF bit-exact)"%TARGET if (not rdiff and bd40==0 and bd41==0 and nf and of) else "RED",flush=True)
