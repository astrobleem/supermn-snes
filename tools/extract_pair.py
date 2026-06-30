#!/usr/bin/env python3
# Capture a 68K function's ENTRY frame AND its EXIT frame from the SAME invocation, in ONE MAME run
# (sequential capture -> the exit R-hit after the entry trap is the same call's return). Fixes the
# capture-correspondence bug where extract_frame + extract_exit (separate launches) grab DIFFERENT
# invocations of a multi-call routine (e.g. $0C9A6 number->ASCII, called per HUD number). Writes the
# same files val_escape_mame reads: frame_<addr>/{entry,exit}_{regs,wram}.bin.
# WIP: helps a5-relative multi-call routines, but for STACK-FRAME functions ($0C9A6 etc) the entry
# [SP] is still PREFETCH-STALE (capture_at_pc fires at prefetch) -> exit R is wrong -> miss. The real
# fix is the mame-mcp bridge prefetch-skew (snapshot at instruction execution). Also: FF-target counts
# game-ticks not SNES frames -> overshoots (saw frame 6734 for START=1500); recalibrate before use.
# Usage: extract_pair.py <hex-addr> [start-frame]
import sys, struct, shutil
from pathlib import Path
sys.path.insert(0,"/home/chad/mame-mcp"); from mame_mcp.session import MameSession
ADDR=int(sys.argv[1],16); START=int(sys.argv[2]) if len(sys.argv)>2 else 1500
HERE=Path("/home/chad/supermn-snes/tools/mame-trace"); ENV=HERE/"record_env"
OUT=Path("/tmp/supermn-scratch/frame_%x"%ADDR); OUT.mkdir(parents=True,exist_ok=True)
for d in ("cfg","nvram"):
    if (ENV/d).exists():
        if (HERE/d).exists(): shutil.rmtree(HERE/d)
        shutil.copytree(ENV/d, HERE/d)
def be32(d,o): return ((d[o]<<24)|(d[o+1]<<16)|(d[o+2]<<8)|d[o+3])&0xFFFFFFFF
def regsA(r):
    v=[r["D%d"%i] for i in range(8)]+[r["A%d"%i] for i in range(7)]+[r["SP"]&0xFFFFFFFF,r.get("USP",0),r.get("SR",0)]
    return b"".join(struct.pack(">I",x&0xFFFFFFFF) for x in v)
def exitregs(r):
    v=[r["D%d"%i] for i in range(8)]+[r["A%d"%i] for i in range(7)]+[r["SP"]&0xFFFFFFFF]
    return b"".join(struct.pack(">I",x&0xFFFFFFFF) for x in v)
s=MameSession(mame="mame",system="superman",rompath=str(HERE/"roms"),workdir=str(HERE),state_directory=str(HERE/"sta"),
              extra_args=["-playback","vplay.inp","-input_directory","/home/chad/supermn-snes/inp"])
try:
    s.launch(boot_wait=25); frame=0
    while frame < START-10:
        step=min(800,START-10-frame)
        r=s.cmd("capture_game_tick",addr=0xF00000,len=4,nth=step,maxFrames=step+400,timeout=180)
        if not r.get("registers"): break
        frame=r["frame"]
    # entry: walk invocations until one with a real code return [SP]
    er=ew=None; R=SP=None
    for nth in range(1,25):
        E=s.cmd("capture_at_pc",pc=ADDR,addr=0xF00000,len=0x10000,nth=nth,maxFrames=8000,timeout=300)
        if not E.get("registers"): break
        er=E["registers"]; ew=bytes.fromhex(E["hex"]); SP=er["SP"]&0xFFFFFF
        R=be32(ew,SP-0xF00000)&0xFFFFFF
        print("  entry nth=%d f=%d SP=%06X [SP]=%06X"%(nth,E.get("frame",0),SP,R),flush=True)
        if 0x000400<=R<0x040000: break
        er=None
    assert er is not None,"no clean entry"
    (OUT/"entry_regs.bin").write_bytes(regsA(er)); (OUT/"entry_wram.bin").write_bytes(ew)
    ESP=(SP+4)&0xFFFFFF
    print("ENTRY f=%d SP=%06X R=%06X exp_sp_exit=%06X (SEQUENTIAL -> same invocation)"%(E.get("frame",0),SP,R,ESP),flush=True)
    # exit: the NEXT time PC=R at the post-return SP -- in the SAME run this is THIS call's return
    X=s.cmd("capture_at_pc",pc=R,addr=0xF00000,len=0x10000,nth=1,exp_sp=ESP,maxFrames=8000,timeout=300)
    assert X.get("registers"),"exit miss at R=%06X exp_sp=%06X"%(R,ESP)
    xr=X["registers"]; xw=bytes.fromhex(X["hex"])
    (OUT/"exit_regs.bin").write_bytes(exitregs(xr)); (OUT/"exit_wram.bin").write_bytes(xw)
    nd=sum(1 for i in range(0x10000) if ew[i]!=xw[i])
    print("EXIT  f=%d PC=%06X SP=%06X  entry->exit changed=%d bytes"%(X.get("frame",0),xr["PC"]&0xFFFFFF,xr["SP"]&0xFFFFFF,nd),flush=True)
finally: s.stop()
