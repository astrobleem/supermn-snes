#!/usr/bin/env python3
# Find who writes $40:104F ($F0104F) during a tick. Inject trip1000 ESC=0 (CHOKE from env), write-hook
# on the SA-1 write to $40104F, run one tick via run_until, log each write: 68K PC ($40), native SA-1 PC,
# value. Compare CHOKE=0 (interp ce4) vs CHOKE=1 (native ce4) to localize the entry_ce4t divergence.
import sys, os
sys.path.insert(0,'tools'); sys.path.insert(0,'/home/chad/Mesen2/python')
os.environ['DOTNET_ROOT']='/home/chad/.dotnet10'; os.environ['PATH']='/home/chad/.dotnet10:'+os.environ.get('PATH','')
import mesen_mcp.session as _sess; _sess.validate_mesen_build=lambda *a,**k: None
from mesen_mcp import McpSession
TD=os.environ.get('TD','/tmp/supermn-scratch/trip1000')
CHOKE=int(os.environ.get('CHOKE','0')); PORT=int(os.environ.get('PORT','7523')); AC=int(os.environ.get('AC','2F60'),16)
WATCH=int(os.environ.get('WATCH','0x40104F'),0)
wramA=open(TD+'/wramA.bin','rb').read(); regs=open(TD+'/regsA.bin','rb').read()
def be32(d,o): return (d[o]<<24)|(d[o+1]<<16)|(d[o+2]<<8)|d[o+3]
D=[be32(regs,i*4) for i in range(8)]; A=[be32(regs,(8+i)*4) for i in range(7)]
SP=be32(regs,15*4); USP=be32(regs,16*4); SR=be32(regs,17*4)&0xFFFF
Z=(SR>>2)&1;C=SR&1;N=(SR>>3)&1;V=(SR>>1)&1;X=(SR>>4)&1
def le32(v): return '%02x%02x%02x%02x'%(v&0xFF,(v>>8)&0xFF,(v>>16)&0xFF,(v>>24)&0xFF)
WN=len(wramA); NEXEN='/home/chad/Nexen/bin/linux-x64/Release/linux-x64/publish/Nexen'; NAT='/tmp/b0_native.mss'
print("TD=%s CHOKE=%d WATCH=$%06X"%(TD,CHOKE,WATCH),flush=True)
with McpSession(rom='/home/chad/supermn-snes/build/interp.sfc',mesen=NEXEN,port=PORT,boot_wait=6.0,socket_timeout=300.0) as m:
    def r16(a): b=m.read_memory('Sa1Memory',a,2); return b[0]|(b[1]<<8)
    def rb(a): return m.read_memory('snesMemory',a,1)[0]
    def w16(a,v,mt='Sa1Memory'): m.write_u16(a,v,mt)
    def wh(a,hx,mt='Sa1Memory'): m.write_memory(mt,a,hx)
    def runf(n,c=300):
        d=0
        while d<n: x=min(c,n-d); m.run_frames(x); d+=x
    m.load_state(NAT); w16(0x073A,0); runf(120)
    w16(0x0700,1); w16(0x0702,0); w16(0x0704,1)
    for _ in range(60):
        runf(20)
        if r16(0x0702): break
    wh(0x00, ''.join(le32(D[i]) for i in range(8)) + ''.join(le32(A[i]) for i in range(7)))
    wh(0x40, le32(0x00003A92)); w16(0x3C, SP&0xFFFF); w16(0x3E,(SP>>16)&0xFF)
    w16(0x60,Z);w16(0x6E,C);w16(0x70,N);w16(0x72,V);w16(0xA2,X);w16(0x7C,SR&7 or 7)
    w16(0xA4,USP&0xFFFF);w16(0xA6,(USP>>16)&0xFFFF);w16(0xA8,1);w16(0xAA,0);w16(0x4A,0);w16(0x4C,0)
    w16(0xAC,AC); w16(0x0718,0xFFF8); w16(0x0724,0); w16(0x0730,0); w16(0x071A,0)
    for o in range(0,WN,0x2000): wh(0x400000+o, wramA[o:o+0x2000].hex(),'snesMemory')
    w16(0x410000,0,'snesMemory'); w16(0x410002,0,'snesMemory')
    m.write_u16(0x407FE0,0,'snesMemory'); w16(0x073A,CHOKE)
    H=m.add_write_hook(WATCH, cpu_type='Sa1')
    w16(0x0702,0); w16(0x0704,1)
    writes=[]
    for _ in range(400):
        r=m.run_until(max_frames=8, hook_handle=H)
        if r.get('reason')=='hookFired':
            pc68=r16(0x40)|(r16(0x42)<<16)
            try: npc=m.get_cpu_state('Sa1').get('pc')
            except Exception: npc=None
            val=rb(WATCH&0xFFFFFF) if WATCH>=0x400000 else 0
            writes.append((pc68,npc,val))
            continue
        if r16(0x0702): break
    print("writes to $%06X this tick (68K PC, nativePC, val):"%WATCH,flush=True)
    for pc,npc,val in writes:
        print("   68K=$%05X  nativePC=%s  ->val=$%02X"%(pc, ('$%06X'%npc if npc is not None else '?'), val),flush=True)
    print("final $%06X = $%02X   B1=%s"%(WATCH, rb(WATCH&0xFFFFFF), bool(r16(0x0702))),flush=True)
