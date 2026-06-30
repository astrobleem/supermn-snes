#!/usr/bin/env python3
# SCHEDULER GROUND-TRUTH tracer. Injects the real ce4trip64 triple, runs ONE GAME_TICK with the
# dbg_fetch PC stream ENABLED ($0718=0), then histograms the EXACT interpreted PCs in $0500-$07FF
# (the scheduler + trap handlers). Tells us the real control flow: how many enabled tasks dispatch a
# body ($077A+) vs defer/skip ($0796), so we know what's collapsible natively vs irreducible.
# Usage: python3 tools/sched_trace.py /tmp/supermn-scratch/ce4trip64
import sys, os, collections
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
with McpSession(rom='/home/chad/supermn-snes/build/interp.sfc',mesen=NEXEN,port=7540,boot_wait=6.0,socket_timeout=300.0) as m:
    def r16(a,mt='Sa1Memory'): b=m.read_memory(mt,a,2); return b[0]|(b[1]<<8)
    def w16(a,v,mt='Sa1Memory'): m.write_u16(a,v,mt)
    def wh(a,hx,mt='Sa1Memory'): m.write_memory(mt,a,hx)
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
    # inject
    wh(0x00, ''.join(le32(D[i]) for i in range(8)) + ''.join(le32(A[i]) for i in range(7)))
    wh(0x40, le32(0x00003A92)); w16(0x3C, SP&0xFFFF); w16(0x3E,(SP>>16)&0xFF)
    w16(0x60,Z);w16(0x6E,C);w16(0x70,Nf);w16(0x72,V);w16(0xA2,X);w16(0x7C,SR&7 or 7)
    w16(0xA4,USP&0xFFFF);w16(0xA6,(USP>>16)&0xFFFF);w16(0xA8,1);w16(0xAA,0);w16(0x4A,0);w16(0x4C,0)
    w16(0xAC,0x2F60); w16(0x0718,0); w16(0x071A,1)        # $0718=0 -> ENABLE PC stream
    for o in range(0,WN,0x2000): wh(0x400000+o, wramA[o:o+0x2000].hex(),'snesMemory')
    w16(0x410000,0,'snesMemory'); w16(0x410002,0,'snesMemory')
    # run ONE tick: clear trap, STEP PAST the current $3A92 into the tick, THEN re-arm $3A92 to catch
    # the NEXT tick boundary (else the trap re-fires at the same $3A92 immediately -> empty window).
    w16(0x0712,0); w16(0x0710,0); w16(0x0714,1); runf(1); w16(0x0714,0)
    for _ in range(80):
        w16(0x0710,0x3A92); w16(0x0716,0); runf(4)
        if r16(0x0712): break
    cnt=r16(0x0718)|(r16(0x071A)<<16) if False else r16(0x0718)
    # PC stream is at $40:8000.. as 16-bit LE PCs; byte count in $0718 (wraps at buffer end)
    nbytes=r16(0x0718)
    if nbytes==0 or nbytes>0x7000: nbytes=0x7000
    raw=b''
    for o in range(0,nbytes,0x1000):
        ln=min(0x1000,nbytes-o); raw+=bytes(m.read_memory('snesMemory',0x408000+o,ln))
    pcs=[raw[i]|(raw[i+1]<<8) for i in range(0,len(raw)-1,2)]
    sched=[p for p in pcs if 0x0500<=p<0x0800]
    h=collections.Counter(sched)
    print(">>> total streamed PCs=%d  scheduler($0500-$07FF)=%d"%(len(pcs),len(sched)))
    print(">>> exact PC histogram in $0500-$07FF (count >=2):")
    for pc,c in sorted(h.items()):
        if c>=2: print("    $%04X x%d"%(pc,c))
    # key dispatch markers
    for mk,lbl in [(0x0774,'btst#30 readiness'),(0x0778,'bne->$0796'),(0x0796,'defer path'),(0x077a,'dispatch body'),(0x07ea,'scan-done')]:
        print("    [marker] $%04X %-20s x%d"%(mk,lbl,h.get(mk,0)))
