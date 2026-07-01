#!/usr/bin/env python3
# Multi-tick hardening for the ce4 fetch-chokepoint. Inject a triple, run N ticks (proven $0700 jsr-hook
# freeze per tick), dump final 64KB work RAM. Run CHOKE=0 and CHOKE=1 separately -> diff the dumps.
# Identical (modulo $7FE0 counter) => ce4-native == ce4-interpreted across ALL invocations over N ticks
# (catches register-level divergence that a single-tick work-RAM diff would miss). No MAME needed: it's
# a self-differential (native-dispatch vs interpret in the SAME interp; both diverge from MAME identically).
import sys, os
sys.path.insert(0,'tools'); sys.path.insert(0,'/home/chad/Mesen2/python')
os.environ['DOTNET_ROOT']='/home/chad/.dotnet10'; os.environ['PATH']='/home/chad/.dotnet10:'+os.environ.get('PATH','')
import mesen_mcp.session as _sess; _sess.validate_mesen_build=lambda *a,**k: None
from mesen_mcp import McpSession
TD=sys.argv[1] if len(sys.argv)>1 else '/tmp/supermn-scratch/ce4trip64'
NTICKS=int(os.environ.get('NTICKS','20'))
CHOKE=int(os.environ.get('CHOKE','0'))
OUT=os.environ.get('OUT','/tmp/mt_dump.bin')
PORT=int(os.environ.get('PORT','7523'))
AC=int(os.environ.get('AC','2F60'),16)
wramA=open(TD+'/wramA.bin','rb').read(); regs=open(TD+'/regsA.bin','rb').read()
def be32(d,o): return (d[o]<<24)|(d[o+1]<<16)|(d[o+2]<<8)|d[o+3]
D=[be32(regs,i*4) for i in range(8)]; A=[be32(regs,(8+i)*4) for i in range(7)]
SP=be32(regs,15*4); USP=be32(regs,16*4); SR=be32(regs,17*4)&0xFFFF
Z=(SR>>2)&1;C=SR&1;N=(SR>>3)&1;V=(SR>>1)&1;X=(SR>>4)&1
def le32(v): return '%02x%02x%02x%02x'%(v&0xFF,(v>>8)&0xFF,(v>>16)&0xFF,(v>>24)&0xFF)
WN=len(wramA); NEXEN='/home/chad/Nexen/bin/linux-x64/Release/linux-x64/publish/Nexen'; NAT='/tmp/b0_native.mss'
print("triple %s CHOKE=%d NTICKS=%d"%(TD,CHOKE,NTICKS),flush=True)
with McpSession(rom='/home/chad/supermn-snes/build/interp.sfc',mesen=NEXEN,port=PORT,boot_wait=6.0,socket_timeout=300.0) as m:
    def r16(a): b=m.read_memory('Sa1Memory',a,2); return b[0]|(b[1]<<8)
    def w16(a,v,mt='Sa1Memory'): m.write_u16(a,v,mt)
    def wh(a,hx,mt='Sa1Memory'): m.write_memory(mt,a,hx)
    def runf(n,c=300):
        d=0
        while d<n: x=min(c,n-d); m.run_frames(x); d+=x
    m.load_state(NAT); w16(0x073A,0); runf(120)
    w16(0x0700,1); w16(0x0702,0); w16(0x0704,1)
    b0=False
    for _ in range(60):
        runf(20)
        if r16(0x0702): b0=True; break
    print("B0 frozen=%s"%b0,flush=True)
    wh(0x00, ''.join(le32(D[i]) for i in range(8)) + ''.join(le32(A[i]) for i in range(7)))
    wh(0x40, le32(0x00003A92)); w16(0x3C, SP&0xFFFF); w16(0x3E,(SP>>16)&0xFF)
    w16(0x60,Z);w16(0x6E,C);w16(0x70,N);w16(0x72,V);w16(0xA2,X);w16(0x7C,SR&7 or 7)
    w16(0xA4,USP&0xFFFF);w16(0xA6,(USP>>16)&0xFFFF);w16(0xA8,1);w16(0xAA,0);w16(0x4A,0);w16(0x4C,0)
    w16(0xAC,AC); w16(0x0718,0xFFF8); w16(0x0724,0); w16(0x0730,0); w16(0x071A,0)
    for o in range(0,WN,0x2000): wh(0x400000+o, wramA[o:o+0x2000].hex(),'snesMemory')
    w16(0x410000,0,'snesMemory'); w16(0x410002,0,'snesMemory')
    m.write_u16(0x407FE0,0,'snesMemory')
    w16(0x073A,CHOKE)
    ticks=0
    for t in range(NTICKS):
        w16(0x0702,0); w16(0x0704,1)
        got=False
        for _ in range(200):
            runf(20)
            if r16(0x0702): got=True; break
        if not got:
            print("  tick %d: NO B%d freeze (derailed)"%(t+1,t+1),flush=True); break
        ticks+=1
    c_ce4=r16(0x0724); c_13be=r16(0x0730)
    sp=r16(0x3C)|(r16(0x3E)<<16)   # 68K a7 at the $3A92 boundary: diffs below SP (dead stack) are benign
    print("completed %d/%d ticks   dispatch: ce4=%d 13be=%d   boundarySP=$%06X"%(ticks,NTICKS,c_ce4,c_13be,sp),flush=True)
    out=bytes(m.read_memory('snesMemory',0x400000,WN))
    open(OUT,'wb').write(out)
    print("dumped %d bytes -> %s"%(len(out),OUT),flush=True)
