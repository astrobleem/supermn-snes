# ON-vs-ON inlining check: run each escape (gate ON) on the DETERMINISTIC native base + a synthetic
# jsr, from a fixed gf260 regfile/work-RAM injection, and print a hash of the resulting $40+$41 work
# RAM. Run on the call-based build and the inlined build -> identical hashes prove the inlining is
# behavior-preserving (no flaky OFF interpreter reference needed). Usage: onon_capture.py <hex>...
import sys, os, hashlib
sys.path.insert(0,'tools'); sys.path.insert(0,'/home/chad/Mesen2/python')
os.environ['DOTNET_ROOT']='/home/chad/.dotnet10'; os.environ['PATH']='/home/chad/.dotnet10:'+os.environ.get('PATH','')
import mesen_mcp.session as _sess; _sess.validate_mesen_build=lambda *a,**k: None
from mesen_mcp import McpSession
S='/tmp/claude-1000/-home-chad-supermn-snes/bc5e5a48-495f-47e6-9724-405edc2118da/scratchpad'
regs=open(S+'/regsA.bin','rb').read(); wramA=open(S+'/wramA.bin','rb').read()
def be32(d,o): return (d[o]<<24)|(d[o+1]<<16)|(d[o+2]<<8)|d[o+3]
D=[be32(regs,i*4) for i in range(8)]; A=[be32(regs,(8+i)*4) for i in range(7)]+[be32(regs,15*4)]; USP=be32(regs,16*4)
def le32(v): return '%02x%02x%02x%02x'%(v&0xFF,(v>>8)&0xFF,(v>>16)&0xFF,(v>>24)&0xFF)
NEXEN='/home/chad/Nexen/bin/linux-x64/Release/linux-x64/publish/Nexen'; NAT='/tmp/b0_native.mss'; SCRATCH=0xFF00
TARGETS=[int(a,16) for a in sys.argv[1:]]
with McpSession(rom='/home/chad/supermn-snes/build/interp.sfc',mesen=NEXEN,port=7509,boot_wait=6.0,socket_timeout=300.0) as m:
    def r16(a,mt='Sa1Memory'): b=m.read_memory(mt,a,2); return b[0]|(b[1]<<8)
    def w16(a,v,mt='Sa1Memory'): m.write_u16(a,v,mt)
    def wh(a,hx,mt='Sa1Memory'): m.write_memory(mt,a,hx)
    def rd(a,n,mt='Sa1Memory'): return bytes(m.read_memory(mt,a,n))
    def runf(n,c=300):
        d=0
        while d<n: x=min(c,n-d); m.run_frames(x); d+=x
    runf(600)
    def cap(tgt):
        jsrb=bytes([0x4E,0xB9,0x00,0x00,(tgt>>8)&0xFF,tgt&0xFF])
        for _ in range(8):
            m.load_state(NAT)
            wh(0x00,''.join(le32(D[i]) for i in range(8))+''.join(le32(A[i]) for i in range(8)))
            w16(0x60,1);w16(0x6E,0);w16(0x70,0);w16(0x72,0);w16(0xA2,0)
            w16(0x7C,7);w16(0xA4,USP&0xFFFF);w16(0xA6,(USP>>16)&0xFFFF);w16(0xA8,1);w16(0xAA,0);w16(0x4A,0);w16(0x4C,0);w16(0xAC,0x7000)
            w16(0x0718,0xFFF8); wh(0x400000,wramA.hex(),'snesMemory'); w16(0x410000,0x0100,'snesMemory'); w16(0x410002,0x0100,'snesMemory')
            wh(0x400000+SCRATCH,jsrb.hex(),'snesMemory'); w16(0x40,SCRATCH); w16(0x42,0x00F0)
            w16(0x071A,1); w16(0x0712,0); w16(0x0710,SCRATCH+6); w16(0x0716,0x00F0); w16(0x0702,0); w16(0x0704,1)
            for _ in range(60):
                runf(20)
                if r16(0x0712) or r16(0x0702): break
            if r16(0x0712):
                b=rd(0x400000,0x10000,'snesMemory')+rd(0x410000,0x8000,'snesMemory')
                return hashlib.sha1(b).hexdigest()[:16]
        return "FROZE0"
    for t in TARGETS:
        print("%06X %s"%(t, cap(t)), flush=True)
