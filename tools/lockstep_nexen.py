#!/usr/bin/env python3
# FULL-TICK lockstep on Nexen (the reliable rts/table-class validator -- per memory
# mame-capture-precision, per-function capture_at_pc is prefetch-skewed for stack-frame fns;
# GAME_TICK lockstep is the validated-working ground truth). Inject MAME's frame-N 68K state
# (regsA/wramA from tools/mame_extract.py, a $3A92 GAME_TICK capture), run EXACTLY one game
# tick (freeze at the next $3A92 via the $0700/$0702/$0704 harness hook), and diff the interp's
# resulting 16KB work RAM vs MAME's wramB (frame N+1). The xlat dispatch table is always-on
# (built into ojmp_hook), so this validates whatever escapes are in the table IN CONTEXT.
# Usage: lockstep_nexen.py <triple-dir> [AC_hex]   (default AC=0x2F60, the combat1000 tick len)
import sys, os
sys.path.insert(0,'tools'); sys.path.insert(0,'/home/chad/Mesen2/python')
os.environ['DOTNET_ROOT']='/home/chad/.dotnet10'; os.environ['PATH']='/home/chad/.dotnet10:'+os.environ.get('PATH','')
import mesen_mcp.session as _sess; _sess.validate_mesen_build=lambda *a,**k: None
from mesen_mcp import McpSession
TD=sys.argv[1]; AC=int(sys.argv[2],16) if len(sys.argv)>2 else 0x2F60
wramA=open(TD+'/wramA.bin','rb').read(); wramB=open(TD+'/wramB.bin','rb').read(); regs=open(TD+'/regsA.bin','rb').read()
def be32(d,o): return (d[o]<<24)|(d[o+1]<<16)|(d[o+2]<<8)|d[o+3]
D=[be32(regs,i*4) for i in range(8)]; A=[be32(regs,(8+i)*4) for i in range(7)]
SP=be32(regs,15*4); USP=be32(regs,16*4); SR=be32(regs,17*4)&0xFFFF
Z=(SR>>2)&1;C=SR&1;N=(SR>>3)&1;V=(SR>>1)&1;X=(SR>>4)&1
def le32(v): return '%02x%02x%02x%02x'%(v&0xFF,(v>>8)&0xFF,(v>>16)&0xFF,(v>>24)&0xFF)
NEXEN='/home/chad/Nexen/bin/linux-x64/Release/linux-x64/publish/Nexen'; NAT='/tmp/b0_native.mss'
print("triple %s  AC=%04X  inj SP=%06X SR=%04X a5=%06X"%(TD,AC,SP&0xFFFFFF,SR,A[5]&0xFFFFFF),flush=True)
with McpSession(rom='/home/chad/supermn-snes/build/interp.sfc',mesen=NEXEN,port=7522,boot_wait=6.0,socket_timeout=300.0) as m:
    def r16(a): b=m.read_memory('Sa1Memory',a,2); return b[0]|(b[1]<<8)
    def w16(a,v,mt='Sa1Memory'): m.write_u16(a,v,mt)
    def wh(a,hx,mt='Sa1Memory'): m.write_memory(mt,a,hx)
    def runf(n,c=300):
        d=0
        while d<n: x=min(c,n-d); m.run_frames(x); d+=x
    m.load_state(NAT)
    runf(120)
    # arm the GAME_TICK freeze, run to B0 (interp's own next $3A92 at the $0708 IRQ site)
    w16(0x0700,1); w16(0x0702,0); w16(0x0704,1)
    b0=False
    for _ in range(60):
        runf(20)
        if r16(0x0702): b0=True; break
    print("B0 frozen=%s ($0702=%X)"%(b0,r16(0x0702)),flush=True)
    # inject MAME frame-N state over the frozen interp
    wh(0x00, ''.join(le32(D[i]) for i in range(8)) + ''.join(le32(A[i]) for i in range(7)))
    wh(0x40, le32(0x00003A92))               # PC = $3A92
    w16(0x3C, SP&0xFFFF); w16(0x3E,(SP>>16)&0xFF)
    w16(0x60,Z);w16(0x6E,C);w16(0x70,N);w16(0x72,V);w16(0xA2,X);w16(0x7C,SR&7 or 7)
    w16(0xA4,USP&0xFFFF);w16(0xA6,(USP>>16)&0xFFFF);w16(0xA8,1);w16(0xAA,0);w16(0x4A,0);w16(0x4C,0)
    w16(0xAC,AC); w16(0x0718,0xFFF8); w16(0x0724,0)
    for o in range(0,0x4000,0x2000): wh(0x400000+o, wramA[o:o+0x2000].hex(),'snesMemory')
    w16(0x410000,0,'snesMemory'); w16(0x410002,0,'snesMemory')
    # release -> run exactly one game tick -> freeze at B1
    w16(0x0702,0); w16(0x0704,1)
    b1=False
    for _ in range(200):
        runf(20)
        if r16(0x0702): b1=True; break
    instr=r16(0x4A)|(r16(0x4C)<<16)
    print("B1 frozen=%s instr(B0->B1)=%d  ce4 hits=%d"%(b1,instr,r16(0x0724)),flush=True)
    out=bytes(m.read_memory('snesMemory',0x400000,0x4000))
    excl=set(range(0x170A-0x80,0x170A+0x80))   # entry a7 region (stack churn) -> exclude
    diff=[i for i in range(0x4000) if out[i]!=wramB[i] and i not in excl]
    print(">>> $40 diff interp-vs-MAME(wramB) = %d bytes (stack-excl)"%len(diff),flush=True)
    for i in diff[:24]: print("   $F0%04X: interp=%02X mame=%02X (A=%02X)"%(i,out[i],wramB[i],wramA[i]),flush=True)
    print(">>>", "GREEN one-tick lockstep" if len(diff)<=8 else "DIFF=%d (residual? or escape bug)"%len(diff),flush=True)
