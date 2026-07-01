#!/usr/bin/env python3
# Clean native-rate measurement in GAMEPLAY over a long span (averages out the single-tick
# overshoot noise). Reuses lockstep_trap's boot+inject to land a gameplay triple, then FREE-RUNS
# until the $0760 game-tick counter reaches N ticks, measuring SA-1 cycleCount + interp instr-counter
# ($4A/$4C). Run ESC=1 and ESC=0 over the same tick count -> clean native cyc/instr.
# Usage: python3 tools/cycle_rate_gp.py <triple-dir> <ESC> [N_ticks=12]
import sys, os
sys.path.insert(0,'tools'); sys.path.insert(0,'/home/chad/Mesen2/python')
os.environ['DOTNET_ROOT']='/home/chad/.dotnet10'; os.environ['PATH']='/home/chad/.dotnet10:'+os.environ.get('PATH','')
import mesen_mcp.session as _sess; _sess.validate_mesen_build=lambda *a,**k: None
from mesen_mcp import McpSession
TD=sys.argv[1]; ESC=int(sys.argv[2]); N=int(sys.argv[3]) if len(sys.argv)>3 else 12
CHOKE=int(os.environ.get('CHOKE','0'))   # $073A fetch-chokepoint gate (0=off baseline, 1=on)
wramA=open(TD+'/wramA.bin','rb').read(); regs=open(TD+'/regsA.bin','rb').read()
def be32(d,o): return (d[o]<<24)|(d[o+1]<<16)|(d[o+2]<<8)|d[o+3]
D=[be32(regs,i*4) for i in range(8)]; A=[be32(regs,(8+i)*4) for i in range(7)]
SP=be32(regs,15*4); USP=be32(regs,16*4); SR=be32(regs,17*4)&0xFFFF
Z=(SR>>2)&1;C=SR&1;N_=(SR>>3)&1;V=(SR>>1)&1;X=(SR>>4)&1
def le32(v): return '%02x%02x%02x%02x'%(v&0xFF,(v>>8)&0xFF,(v>>16)&0xFF,(v>>24)&0xFF)
WN=len(wramA)
NEXEN='/home/chad/Nexen/bin/linux-x64/Release/linux-x64/publish/Nexen'; NAT='/tmp/b0_native.mss'
with McpSession(rom='/home/chad/supermn-snes/build/interp.sfc',mesen=NEXEN,port=int(os.environ.get('PORT','7533')),boot_wait=6.0,socket_timeout=300.0) as m:
    def r16(a,mt='Sa1Memory'): b=m.read_memory(mt,a,2); return b[0]|(b[1]<<8)
    def w16(a,v,mt='Sa1Memory'): m.write_u16(a,v,mt)
    def wh(a,hx,mt='Sa1Memory'): m.write_memory(mt,a,hx)
    def cyc(): return m.get_cpu_state('Sa1').get('cycleCount')
    def runf(n,c=300):
        d=0
        while d<n: x=min(c,n-d); m.run_frames(x); d+=x
    m.load_state(NAT); runf(120)
    w16(0x0700,0); w16(0x071A,0); w16(0x0712,0); w16(0x0716,0); w16(0x0710,0x0708); w16(0x0704,1)
    for _ in range(240):
        runf(5)
        if r16(0x0712): break
        w16(0x0710,0x0708); w16(0x0716,0)
    w16(0x0712,0); w16(0x0710,0); w16(0x0714,1); runf(1); w16(0x0714,0)
    for _ in range(60):
        w16(0x0710,0x3A92); w16(0x0716,0); runf(4)
        if r16(0x0712): break
    # inject the gameplay triple
    wh(0x00, ''.join(le32(D[i]) for i in range(8)) + ''.join(le32(A[i]) for i in range(7)))
    wh(0x40, le32(0x00003A92)); w16(0x3C, SP&0xFFFF); w16(0x3E,(SP>>16)&0xFF)
    w16(0x60,Z);w16(0x6E,C);w16(0x70,N_);w16(0x72,V);w16(0xA2,X);w16(0x7C,SR&7 or 7)
    w16(0xA4,USP&0xFFFF);w16(0xA6,(USP>>16)&0xFFFF);w16(0xA8,1);w16(0xAA,0);w16(0x4A,0);w16(0x4C,0)
    w16(0xAC,0x2F60); w16(0x0718,0xFFF8); w16(0x071A,ESC); w16(0x073A,CHOKE)
    for o in range(0,WN,0x2000): wh(0x400000+o, wramA[o:o+0x2000].hex(),'snesMemory')
    w16(0x410000,0,'snesMemory'); w16(0x410002,0,'snesMemory')
    # release the freeze and FREE-RUN until $0760 reaches N ticks
    w16(0x0712,0); w16(0x0710,0); w16(0x0714,1); runf(1); w16(0x0714,0)
    w16(0x4A,0); w16(0x4C,0); w16(0x0760,0)
    c0=cyc()
    for _ in range(2000):
        runf(8)
        if r16(0x0760) >= N: break
    c1=cyc(); ticks=r16(0x0760); instr=r16(0x4A)|(r16(0x4C)<<16)
    dcyc=c1-c0
    print(">>> ESC=%d  ticks=%d  SA-1 cycles=%d  interp instr=%d"%(ESC,ticks,dcyc,instr),flush=True)
    if ticks: print(">>> cycles/tick=%.0f  interp-instr/tick=%.0f  cyc/interp-instr=%.0f"%(dcyc/ticks,instr/ticks,dcyc/instr if instr else 0),flush=True)
