#!/usr/bin/env python3
# SYNTHETIC bit27 (first-dispatch wake-up) differential for entry_swin. The captured triples never
# exercise the $07D2 bclr-set branch ($07D8 descriptor write-back + $07DE frame patch), so this test
# manufactures it: find the FIRST ready task the scan will hit (enable-mask bit + descriptor bit30),
# SET descriptor bit27 in the injected work RAM, run ONE tick with SWIN=0 vs SWIN=1, and byte-diff the
# end states (work RAM + DP reg file). Both arms run the same mutated state -> 0 diffs (mod $7FE2
# counter) == the wake-up path is bit-faithful. Clones lockstep_choke's proven injection skeleton.
import sys, os
sys.path.insert(0,'tools'); sys.path.insert(0,'/home/chad/Mesen2/python')
os.environ['DOTNET_ROOT']='/home/chad/.dotnet10'; os.environ['PATH']='/home/chad/.dotnet10:'+os.environ.get('PATH','')
import mesen_mcp.session as _sess; _sess.validate_mesen_build=lambda *a,**k: None
from mesen_mcp import McpSession
TD=sys.argv[1] if len(sys.argv)>1 else '/tmp/supermn-scratch/ce4trip64'
AC=int(os.environ.get('AC','2F60'),16)
SWIN=int(os.environ.get('SWIN','0'))
OUT=os.environ.get('OUT','/tmp/synth_b27.bin')
PORT=int(os.environ.get('PORT','7523'))
wramA=bytearray(open(TD+'/wramA.bin','rb').read()); regs=open(TD+'/regsA.bin','rb').read()
def be32(d,o): return (d[o]<<24)|(d[o+1]<<16)|(d[o+2]<<8)|d[o+3]
D=[be32(regs,i*4) for i in range(8)]; A=[be32(regs,(8+i)*4) for i in range(7)]
SP=be32(regs,15*4); USP=be32(regs,16*4); SR=be32(regs,17*4)&0xFFFF
Z=(SR>>2)&1;C=SR&1;N=(SR>>3)&1;V=(SR>>1)&1;X=(SR>>4)&1
def le32(v): return '%02x%02x%02x%02x'%(v&0xFF,(v>>8)&0xFF,(v>>16)&0xFF,(v>>24)&0xFF)
# --- set bit27 on ALL 16 task descriptors (readiness is marked mid-tick, not at the $3A92
# boundary, so a static ready-scan finds nothing; blanket bit27 makes every switch-in of the
# tick take the wake-up branch — identically in both arms, so the self-diff stays valid) ---
nset=0
for idx in range(16):
    doff=0x4E+idx*4
    if not (wramA[doff] & 0x08):
        wramA[doff] |= 0x08; nset+=1       # bit27 = byte0 bit3 of the BE long
print("triple %s  SWIN=%d  bit27 set on %d/16 descriptors"%(TD,SWIN,nset),flush=True)
WN=len(wramA)
NEXEN=os.environ.get(
    'NEXEN',
    '/mnt/sdc1/Nexen-r5-20260712/bin/linux-x64/Release/linux-x64/publish/Nexen',
)
NAT=os.environ.get('NAT','/tmp/b0_native.mss')
with McpSession(rom='/home/chad/supermn-snes/build/interp.sfc',mesen=NEXEN,port=PORT,boot_wait=6.0,socket_timeout=300.0) as m:
    def r16(a): b=m.read_memory('Sa1Memory',a,2); return b[0]|(b[1]<<8)
    def w16(a,v,mt='Sa1Memory'): m.write_u16(a,v,mt)
    def wh(a,hx,mt='Sa1Memory'): m.write_memory(mt,a,hx)
    def runf(n,c=300):
        d=0
        while d<n: x=min(c,n-d); m.run_frames(x); d+=x
    m.load_state(NAT); w16(0x073A,0); w16(0x073C,0); runf(120)
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
    for o in range(0,WN,0x2000): wh(0x400000+o, bytes(wramA[o:o+0x2000]).hex(),'snesMemory')
    w16(0x410000,0,'snesMemory'); w16(0x410002,0,'snesMemory')
    m.write_u16(0x407FE0,0,'snesMemory'); m.write_u16(0x407FE2,0,'snesMemory')
    w16(0x073C,0xA55A if SWIN else 0)
    w16(0x0702,0); w16(0x0704,1)
    b1=False
    for _ in range(200):
        runf(20)
        if r16(0x0702): b1=True; break
    sw=m.read_memory('snesMemory',0x407FE2,2); c_swin=sw[0]|(sw[1]<<8)
    instr=r16(0x4A)|(r16(0x4C)<<16)
    print("B1 frozen=%s  instr=%d  swin=%d"%(b1,instr,c_swin),flush=True)
    out=bytes(m.read_memory('snesMemory',0x400000,WN))
    dp=bytes(m.read_memory('Sa1Memory',0x0000,0x40))   # DP reg file at the boundary
    open(OUT,'wb').write(out+dp)
    print("dumped %d bytes (wram+dp) -> %s"%(len(out)+len(dp),OUT),flush=True)
