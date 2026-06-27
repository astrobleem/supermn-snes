# Validate a FRAME-SHARING leaf using a DETERMINISTIC MAME-captured entry frame (regfile+64KB work
# RAM + SR), injected into the interp + isolated synthetic-jsr ON vs OFF. Avoids the flaky b0-tick
# capture (non-deterministic Nexen resume). Usage: val_frame.py <hex-target> <frame-dir>
import sys, os, json
sys.path.insert(0,'tools'); sys.path.insert(0,'/home/chad/Mesen2/python')
os.environ['DOTNET_ROOT']='/home/chad/.dotnet10'; os.environ['PATH']='/home/chad/.dotnet10:'+os.environ.get('PATH','')
import mesen_mcp.session as _sess; _sess.validate_mesen_build=lambda *a,**k: None
from mesen_mcp import McpSession
TGT=int(sys.argv[1],16); FD=sys.argv[2]
regs=open(FD+'/entry_regs.bin','rb').read(); wram=open(FD+'/entry_wram.bin','rb').read()
assert len(wram)==0x10000
def be32(d,o): return (d[o]<<24)|(d[o+1]<<16)|(d[o+2]<<8)|d[o+3]
D=[be32(regs,i*4) for i in range(8)]; A=[be32(regs,(8+i)*4) for i in range(7)]; SP=be32(regs,15*4); USP=be32(regs,16*4); SR=be32(regs,17*4)&0xFFFF
def le32(v): return '%02x%02x%02x%02x'%(v&0xFF,(v>>8)&0xFF,(v>>16)&0xFF,(v>>24)&0xFF)
# CCR: bit0=C bit1=V bit2=Z bit3=N bit4=X
Z=(SR>>2)&1; C=SR&1; N=(SR>>3)&1; V=(SR>>1)&1; X=(SR>>4)&1
NEXEN='/home/chad/Nexen/bin/linux-x64/Release/linux-x64/publish/Nexen'
cpu=json.load(open('/tmp/b0_cpu.json')); iram=open('/tmp/b0_iram.bin','rb').read(); bwram=open('/tmp/b0_bwram.bin','rb').read()
SCRATCH=0xFF00; jsrb=bytes([0x4E,0xB9,0x00,0x00,(TGT>>8)&0xFF,TGT&0xFF])
with McpSession(rom='/home/chad/supermn-snes/build/interp.sfc',mesen=NEXEN,port=7479,boot_wait=6.0,socket_timeout=300.0) as m:
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
    def run(hook):
        freezeB0()
        wh(0x00, ''.join(le32(D[i]) for i in range(8)) + ''.join(le32(A[i]) for i in range(7)))  # D0-D7,A0-A6
        wh(0x3C, le32(SP))                                                                        # A7 (not A6 @ $38!)
        w16(0x60,Z); w16(0x6E,C); w16(0x70,N); w16(0x72,V); w16(0xA2,X)
        w16(0x7C,SR&7 or 7); w16(0xA4,USP&0xFFFF); w16(0xA6,(USP>>16)&0xFFFF); w16(0xA8,1); w16(0xAA,0); w16(0x4A,0); w16(0x4C,0); w16(0xAC,0x7000)
        w16(0x0718,0xFFF8)
        for o in range(0,0x10000,0x4000): wh(0x400000+o,wram[o:o+0x4000].hex(),'snesMemory')
        w16(0x410000,0x0100,'snesMemory'); w16(0x410002,0x0100,'snesMemory')
        wh(0x400000+SCRATCH, jsrb.hex(),'snesMemory'); w16(0x40,SCRATCH); w16(0x42,0x00F0)
        w16(0x071A,hook); w16(0x0712,0); w16(0x0710,SCRATCH+6); w16(0x0716,0x00F0); w16(0x0702,0); w16(0x0704,1)
        for _ in range(300):
            runf(20)
            if r16(0x0712) or r16(0x0702): break
        return r16(0x0712), rd(0x00,0x40), rd(0x400000,0x10000,'snesMemory'), rd(0x410000,0x8000,'snesMemory')
    print("[Nexen] boot...",flush=True); runf(600)
    def run_complete(hook):
        for attempt in range(8):
            fz,rf,m40,m41=run(hook)
            if fz: return fz,rf,m40,m41
            print("  hook=%d attempt %d froze=0, retry"%(hook,attempt),flush=True)
        return fz,rf,m40,m41
    of,orf,o40,o41=run_complete(0); nf,nrf,n40,n41=run_complete(1)
    RN=['d0','d1','d2','d3','d4','d5','d6','d7','a0','a1','a2','a3','a4','a5','a6','a7']
    def g(b,s): i=s*4; return b[i]|b[i+1]<<8|b[i+2]<<16|b[i+3]<<24
    rdiff=[RN[s] for s in range(16) if g(orf,s)!=g(nrf,s)]
    a7=SP; ex=set(range(SCRATCH,SCRATCH+8))|set(range((a7-4)&0xFFFF,((a7-4)&0xFFFF)+4))
    bd40=sum(1 for i in range(0x10000) if i not in ex and o40[i]!=n40[i]); bd41=sum(1 for i in range(0x8000) if o41[i]!=n41[i])
    print("[val_frame %06X] a6=%06X OFF froze=%d ON froze=%d ; regdiff=%s ; $40diff=%d ; $41diff=%d"%(TGT,A[6]&0xFFFFFF,of,nf,rdiff or 'NONE',bd40,bd41),flush=True)
    work_off=sum(1 for i in range(0x10000) if i not in ex and o40[i]!=wram[i])
    print("  OFF work-RAM changed vs input frame: %d bytes (fn executed if >0)"%work_off,flush=True)
    print(">>>", "GREEN-frame $%06X bit-exact"%TGT if (not rdiff and bd40==0 and bd41==0 and nf and of) else "RED",flush=True)
