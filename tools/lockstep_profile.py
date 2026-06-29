#!/usr/bin/env python3
# DETERMINISTIC hot-profile: inject a MAME GAME_TICK triple (regsA/wramA) and run exactly one $0708
# interval with PC streaming ON, then histogram the interp's genuinely-executed 68K PC stream by
# 64-byte region. Unlike profile_real (which free-runs the interp -> drifted code path), this profiles
# the REAL MAME-aligned code path -- the correct source for picking AOT-table targets. Reports, per hot
# region, whether it's already an escape entry. Usage: lockstep_profile.py <triple-dir> [AC_hex]
import sys, os, collections
sys.path.insert(0,'tools'); sys.path.insert(0,'/home/chad/Mesen2/python')
os.environ['DOTNET_ROOT']='/home/chad/.dotnet10'; os.environ['PATH']='/home/chad/.dotnet10:'+os.environ.get('PATH','')
import mesen_mcp.session as _sess; _sess.validate_mesen_build=lambda *a,**k: None
from mesen_mcp import McpSession
from capstone import *
md=Cs(CS_ARCH_M68K,CS_MODE_M68K_000)
IMG=open('build/interp.sfc','rb').read()[0x10000:0x10000+0x40000]
def desc(pc):
    try: ins=next(md.disasm(IMG[pc:pc+8],pc)); return "%s %s"%(ins.mnemonic,ins.op_str)
    except StopIteration: return "?"
TD=sys.argv[1]; AC=int(sys.argv[2],16) if len(sys.argv)>2 else 0x2F60
wramA=open(TD+'/wramA.bin','rb').read(); regs=open(TD+'/regsA.bin','rb').read()
def be32(d,o): return (d[o]<<24)|(d[o+1]<<16)|(d[o+2]<<8)|d[o+3]
D=[be32(regs,i*4) for i in range(8)]; A=[be32(regs,(8+i)*4) for i in range(7)]
SP=be32(regs,15*4); USP=be32(regs,16*4); SR=be32(regs,17*4)&0xFFFF
Z=(SR>>2)&1;C=SR&1;N=(SR>>3)&1;V=(SR>>1)&1;X=(SR>>4)&1
def le32(v): return '%02x%02x%02x%02x'%(v&0xFF,(v>>8)&0xFF,(v>>16)&0xFF,(v>>24)&0xFF)
NEXEN='/home/chad/Nexen/bin/linux-x64/Release/linux-x64/publish/Nexen'; NAT='/tmp/b0_native.mss'
with McpSession(rom='/home/chad/supermn-snes/build/interp.sfc',mesen=NEXEN,port=7524,boot_wait=6.0,socket_timeout=300.0) as m:
    def r16(a): b=m.read_memory('Sa1Memory',a,2); return b[0]|(b[1]<<8)
    def w16(a,v,mt='Sa1Memory'): m.write_u16(a,v,mt)
    def wh(a,hx,mt='Sa1Memory'): m.write_memory(mt,a,hx)
    def runf(n,c=300):
        d=0
        while d<n: x=min(c,n-d); m.run_frames(x); d+=x
    m.load_state(NAT); runf(120)
    w16(0x0700,1); w16(0x0702,0); w16(0x0704,1)
    for _ in range(60):
        runf(20)
        if r16(0x0702): break
    wh(0x00, ''.join(le32(D[i]) for i in range(8)) + ''.join(le32(A[i]) for i in range(7)))
    wh(0x40, le32(0x00003A92)); w16(0x3C, SP&0xFFFF); w16(0x3E,(SP>>16)&0xFF)
    w16(0x60,Z);w16(0x6E,C);w16(0x70,N);w16(0x72,V);w16(0xA2,X);w16(0x7C,SR&7 or 7)
    w16(0xA4,USP&0xFFFF);w16(0xA6,(USP>>16)&0xFFFF);w16(0xA8,1);w16(0xAA,0);w16(0x4A,0);w16(0x4C,0)
    w16(0xAC,AC); w16(0x0718,0)                # streaming ON
    for o in range(0,0x4000,0x2000): wh(0x400000+o, wramA[o:o+0x2000].hex(),'snesMemory')
    w16(0x410000,0,'snesMemory'); w16(0x410002,0,'snesMemory')
    w16(0x0702,0); w16(0x0704,1)
    for _ in range(200):
        runf(20)
        if r16(0x0702): break
    nb=r16(0x0718)
    stream=m.read_memory('snesMemory',0x408000,min(nb,0xFFF8))
    pcs=[((stream[i+2]|(stream[i+3]<<8))<<16)|(stream[i]|(stream[i+1]<<8)) for i in range(0,len(stream)-3,4)]
    irq=set(range(0x06F0,0x0762))|{0x0818}
    c=collections.Counter(p&~0x3F for p in pcs if 0x800<=p<0x40000 and p not in irq)
    print(">>> deterministic interval: %d streamed PCs, instr=%d"%(len(pcs), r16(0x4A)|(r16(0x4C)<<16)),flush=True)
    print(">>> top interpreted regions (DETERMINISTIC gameplay):",flush=True)
    for reg,n in c.most_common(20):
        print(">>> $%06X  x%-4d  [%s]"%(reg,n,desc(reg)),flush=True)
