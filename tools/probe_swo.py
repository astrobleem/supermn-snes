#!/usr/bin/env python3
# Freeze at the FIRST $0532 (yield trap), dump the state entry_swo depends on so we can verify the
# address math against reality: a5, a7, the trap frame at (a7), *(a5+6) [SP-save-slot ptr], *(a5+$4a)
# [descriptor ptr]. Then release ONE step (re-freeze at $075C, after switch-out+scan) and read the
# saved SP + frame to see if the saved frame survived (resume PC should be the trap PC, not $0000).
import sys, os
sys.path.insert(0,'tools'); sys.path.insert(0,'/home/chad/Mesen2/python')
os.environ['DOTNET_ROOT']='/home/chad/.dotnet10'; os.environ['PATH']='/home/chad/.dotnet10:'+os.environ.get('PATH','')
import mesen_mcp.session as _sess; _sess.validate_mesen_build=lambda *a,**k: None
from mesen_mcp import McpSession
TD=sys.argv[1] if len(sys.argv)>1 else '/tmp/supermn-scratch/ce4trip64'
regs=open(TD+'/regsA.bin','rb').read(); wramA=open(TD+'/wramA.bin','rb').read()
def be32(d,o): return (d[o]<<24)|(d[o+1]<<16)|(d[o+2]<<8)|d[o+3]
D=[be32(regs,i*4) for i in range(8)]; A=[be32(regs,(8+i)*4) for i in range(7)]
SP=be32(regs,15*4); USP=be32(regs,16*4); SR=be32(regs,17*4)&0xFFFF
Z=(SR>>2)&1;C=SR&1;Nf=(SR>>3)&1;V=(SR>>1)&1;X=(SR>>4)&1
def le32(v): return '%02x%02x%02x%02x'%(v&0xFF,(v>>8)&0xFF,(v>>16)&0xFF,(v>>24)&0xFF)
WN=len(wramA); NEXEN='/home/chad/Nexen/bin/linux-x64/Release/linux-x64/publish/Nexen'; NAT='/tmp/b0_native.mss'
with McpSession(rom='/home/chad/supermn-snes/build/interp.sfc',mesen=NEXEN,port=7570,boot_wait=6.0,socket_timeout=300.0) as m:
    def r16(a,mt='Sa1Memory'): b=m.read_memory(mt,a,2); return b[0]|(b[1]<<8)
    def w16(a,v,mt='Sa1Memory'): m.write_u16(a,v,mt)
    def wh(a,hx,mt='Sa1Memory'): m.write_memory(mt,a,hx)
    def rwram32(addr):  # BE long at work-RAM addr (lo16 used)
        b=m.read_memory('snesMemory',0x400000+(addr&0xFFFF),4); return (b[0]<<24)|(b[1]<<16)|(b[2]<<8)|b[3]
    def rwram16(addr):
        b=m.read_memory('snesMemory',0x400000+(addr&0xFFFF),2); return (b[0]<<8)|b[1]
    def runf(n,c=300):
        d=0
        while d<n: x=min(c,n-d); m.run_frames(x); d+=x
    m.load_state(NAT); runf(120)
    w16(0x0700,0); w16(0x0738,0); w16(0x071A,1); w16(0x0712,0); w16(0x0716,0); w16(0x0710,0x0708); w16(0x0704,1)
    for _ in range(240):
        runf(5)
        if r16(0x0712): break
        w16(0x0710,0x0708); w16(0x0716,0)
    w16(0x0712,0); w16(0x0710,0); w16(0x0714,1); runf(1); w16(0x0714,0)
    for _ in range(60):
        w16(0x0710,0x3A92); w16(0x0716,0); runf(4)
        if r16(0x0712): break
    wh(0x00, ''.join(le32(D[i]) for i in range(8)) + ''.join(le32(A[i]) for i in range(7)))
    wh(0x40, le32(0x00003A92)); w16(0x3C, SP&0xFFFF); w16(0x3E,(SP>>16)&0xFF)
    w16(0x60,Z);w16(0x6E,C);w16(0x70,Nf);w16(0x72,V);w16(0xA2,X);w16(0x7C,SR&7 or 7)
    w16(0xA4,USP&0xFFFF);w16(0xA6,(USP>>16)&0xFFFF);w16(0xA8,1);w16(0xAA,0);w16(0x4A,0);w16(0x4C,0)
    w16(0xAC,0x2F60); w16(0x0718,0xFFF8); w16(0x071A,1)
    for o in range(0,WN,0x2000): wh(0x400000+o, wramA[o:o+0x2000].hex(),'snesMemory')
    w16(0x410000,0,'snesMemory'); w16(0x410002,0,'snesMemory')
    # release + run the tick (it crashes); read entry_swo's work-RAM sentinels ($40:7FE0)
    def rs(off): b=m.read_memory('snesMemory',0x407FE0+off,2); return b[0]|(b[1]<<8)
    m.write_u16(0x407FE0,0,'snesMemory')
    w16(0x0712,0); w16(0x0710,0); w16(0x0714,1); runf(3); w16(0x0714,0)
    fires=rs(0); a7=rs(2)|(rs(4)<<16)
    framepc=(m.read_memory('snesMemory',0x407FE6,1)[0]<<16)|(m.read_memory('snesMemory',0x407FE7,1)[0]<<8)|m.read_memory('snesMemory',0x407FE8,1)[0]
    print(">>> entry_swo fires=%d  (last call) a7=%06X  trap-frame resume-PC@(a7+2)=%06X"%(fires,a7,framepc))
    print("    => if resume-PC is a valid code addr, my SAVE corrupts it; if already 0, upstream bug")
