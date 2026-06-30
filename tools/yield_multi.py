#!/usr/bin/env python3
# Value-dependence check for the switch-out body: capture K sequential $0532 yields from MAME, and for
# each, sim CORRECT ($0532-$0550, 68K semantics) vs entry_swo (my asm). Any divergence => a value-
# dependent body bug. All-match => the body is fully correct and the regression is the integration.
import sys, os
sys.path.insert(0,'tools'); sys.path.insert(0,'/home/chad/mame-mcp')
from mame_mcp.session import MameSession
from pathlib import Path
HERE=Path('tools/mame-trace').resolve(); WBASE=0xF00000; K=int(os.environ.get('K','8'))
REGORD=['D0','D1','D2','D3','D4','D5','D6','D7','A0','A1','A2','A3','A4','A5','A6']
def sims(W0, regs):
    a5=regs['A5']&0xFFFFFFFF; a7=regs['SP']&0xFFFFFFFF
    def mk():
        W=bytearray(W0)
        def w32(a,v):o=(a-WBASE)&0xFFFF;W[o]=(v>>24)&0xFF;W[(o+1)&0xFFFF]=(v>>16)&0xFF;W[(o+2)&0xFFFF]=(v>>8)&0xFF;W[(o+3)&0xFFFF]=v&0xFF
        def w16(a,v):o=(a-WBASE)&0xFFFF;W[o]=(v>>8)&0xFF;W[(o+1)&0xFFFF]=v&0xFF
        def r32(a):o=(a-WBASE)&0xFFFF;return (W[o]<<24)|(W[(o+1)&0xFFFF]<<16)|(W[(o+2)&0xFFFF]<<8)|W[(o+3)&0xFFFF]
        def r16(a):o=(a-WBASE)&0xFFFF;return (W[o]<<8)|W[(o+1)&0xFFFF]
        return W,w32,w16,r32,r16
    def correct():
        W,w32,w16,r32,r16=mk(); na7=(a7-60)&0xFFFFFFFF
        for i,r in enumerate(REGORD): w32(na7+i*4, regs[r]&0xFFFFFFFF)
        w32(r32(a5+6)&0xFFFFFFFF, na7)
        a4=r32(a5+0x4a)&0xFFFFFFFF; w16(a4,(r16(a4)&0xCFFF)|0xC000); return W
    def myasm():
        W,w32,w16,r32,r16=mk(); na7=(a7&0xFFFF0000)|((a7-60)&0xFFFF); wp=na7&0xFFFF
        for i,r in enumerate(REGORD): w32(WBASE|((wp+i*4)&0xFFFF), regs[r]&0xFFFFFFFF)
        w32(r32((a5+6)&0xFFFFFFFF)&0xFFFFFFFF, na7)
        a4=r32((a5+0x4a)&0xFFFFFFFF)&0xFFFFFFFF; w16(a4,(r16(a4)&0xCFFF)|0xC000); return W
    C=correct(); M=myasm(); return [i for i in range(len(C)) if C[i]!=M[i]]
sess=MameSession(mame='mame',system='superman',rompath=str(HERE/'roms'),workdir=str(HERE),state_directory=str(HERE/'sta'))
try:
    sess.launch(boot_wait=30); sess.load_state('combat1000'); sess.run_frames(4)
    ok=0
    for k in range(K):
        nth = 3 if k==0 else 1   # first jumps in; then each next $0532
        A=sess.cmd('capture_at_pc', pc=0x0532, addr=WBASE, len=0x10000, nth=nth, maxFrames=1200, timeout=60)
        if not A.get('registers'): print("k=%d: no $0532"%k); break
        regs={x:int(v) for x,v in A['registers'].items()}; W0=bytes.fromhex(A['hex'])
        a5=regs['A5']&0xFFFFFF; a7=regs['SP']&0xFFFFFF; rp=((W0[(a7+2-WBASE)&0xFFFF]<<16)|(W0[(a7+3-WBASE)&0xFFFF]<<8)|W0[(a7+4-WBASE)&0xFFFF])
        d=sims(W0,regs)
        tag="MATCH" if not d else "DIVERGE@"+",".join("%06X"%(WBASE+x) for x in d[:8])
        print("  $0532 #%d: a5=%06X a7=%06X resume-PC=%06X  body=%s"%(k,a5,a7,rp,tag))
        if not d: ok+=1
    print(">>> %d/%d switch-outs: body bit-exact"%(ok,K))
finally:
    sess.stop()
