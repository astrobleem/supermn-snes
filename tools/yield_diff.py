#!/usr/bin/env python3
# SINGLE-YIELD DIFFERENTIAL harness. Debugs a native escape of a 68K routine by capturing the
# routine's GROUND-TRUTH memory effect from MAME, then (optionally) running the escape on the SAME
# injected state and diffing. Generic: give it the trigger PC, the done PC, and the work-RAM window.
#
# Phase 1 (MAME, this file): capture full work RAM at TRIG (S0) and at the next DONE (S_truth). Since
# no task body runs between $0532 (yield) and $0550 bra $74c -> $074C, S0->S_truth == EXACTLY what the
# switch-out ($0532-$0550) writes. Prints the changed bytes + the key regs (a5,a7,a4,a6,d0) + the trap
# frame, so the escape's intended writes can be checked against reality.
#   python3 tools/yield_diff.py [TRIG=0x0532] [DONE=0x074C] [state=combat1000]
import sys, os
sys.path.insert(0, 'tools'); sys.path.insert(0, '/home/chad/mame-mcp')
from mame_mcp.session import MameSession
from pathlib import Path
TRIG=int(os.environ.get('TRIG','0x0532'),0); DONE=int(os.environ.get('DONE','0x074C'),0)
STATE=os.environ.get('STATE','combat1000'); NTH=int(os.environ.get('NTH','3'))
HERE=Path('tools/mame-trace').resolve(); WBASE=0xF00000; WLEN=0x10000
OUT=Path('/tmp/supermn-scratch/yield'); OUT.mkdir(parents=True, exist_ok=True)
sess=MameSession(mame='mame', system='superman', rompath=str(HERE/'roms'), workdir=str(HERE), state_directory=str(HERE/'sta'))
try:
    sess.launch(boot_wait=25); sess.load_state(STATE); sess.run_frames(4)
    # S0 at the NTH TRIG (skip the first couple so the scheduler is in steady state)
    A=sess.cmd('capture_at_pc', pc=TRIG, addr=WBASE, len=WLEN, nth=NTH, maxFrames=1200, timeout=60)
    if not A.get('registers'): raise SystemExit('TRIG $%04X not reached'%TRIG)
    r=A['registers']; s0=bytes.fromhex(A['hex'])
    def rv(n): return r.get(n,0)&0xFFFFFFFF
    a5=rv('A5'); a7=rv('SP'); a4=rv('A4'); a6=rv('A6'); d0=rv('D0')
    print(">>> S0 at $%04X (nth=%d): a5=%06X a7=%06X a4=%06X a6=%06X d0=%08X SR=%04X"%(
          TRIG,NTH,a5&0xFFFFFF,a7&0xFFFFFF,a4&0xFFFFFF,a6&0xFFFFFF,d0,rv('SR')&0xFFFF))
    def w32(buf,addr): o=addr-WBASE; return (buf[o]<<24)|(buf[o+1]<<16)|(buf[o+2]<<8)|buf[o+3]
    def w16(buf,addr): o=addr-WBASE; return (buf[o]<<8)|buf[o+1]
    print("    *(a5+6) SP-slot ptr = %08X   *(a5+$4a) descr ptr = %08X"%(w32(s0,a5+6),w32(s0,a5+0x4a)))
    print("    descr word @(a5+$4a target) = %04X"%w16(s0,w32(s0,a5+0x4a)&0xFFFFFF))
    print("    trap frame @a7: SR=%04X resume-PC=%06X"%(w16(s0,a7&0xFFFFFF),w32(s0,a7&0xFFFFFF)+2 and w32(s0,(a7&0xFFFFFF)+2)&0xFFFFFF))
    # S_truth at the very next DONE
    B=sess.cmd('capture_at_pc', pc=DONE, addr=WBASE, len=WLEN, nth=1, maxFrames=400, timeout=60)
    if not B.get('hex'): raise SystemExit('DONE $%04X not reached after TRIG'%DONE)
    st=bytes.fromhex(B['hex'])
    (OUT/'s0.bin').write_bytes(s0); (OUT/'s_truth.bin').write_bytes(st)
    open(OUT/'s0_regs.txt','w').write(repr({k:hex(v) for k,v in r.items()}))
    # diff: what the switch-out ($0532-$0550) actually wrote
    diffs=[(WBASE+i, s0[i], st[i]) for i in range(WLEN) if s0[i]!=st[i]]
    print(">>> S0 -> S_truth: %d bytes changed by the switch-out ($%04X-$0550):"%(len(diffs),TRIG))
    # group contiguous runs
    runs=[]; i=0
    while i<len(diffs):
        j=i
        while j+1<len(diffs) and diffs[j+1][0]==diffs[j][0]+1: j+=1
        a=diffs[i][0]; old=bytes(d[1] for d in diffs[i:j+1]); new=bytes(d[2] for d in diffs[i:j+1])
        runs.append((a,old,new)); i=j+1
    for a,old,new in runs:
        tag=''
        if a==(w32(s0,a5+6)&0xFFFFFF): tag=' <- SP-slot (move.l a7,(a6))'
        if a<=(a5+0x4a)<=a+len(old)-1 or a==(w32(s0,a5+0x4a)&0xFFFFFF): tag=' <- descriptor (a4)'
        print("    $%06X (%2dB): %s -> %s%s"%(a,len(old),old.hex(),new.hex(),tag))
    print(">>> saved at %s/{s0,s_truth}.bin"%OUT)
finally:
    sess.stop()
