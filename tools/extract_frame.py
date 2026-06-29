# Capture a 68K function's ENTRY frame (regfile + 64KB work RAM at $F0xxxx) from MAME's deterministic
# playback, for escape-vs-MAME ground-truth validation. The 64KB carries the a6 frame (own link OR a
# frame-sharing caller's). Usage: extract_frame.py <hex-addr> [start-frame]  (default $00CC10, 1500).
import sys, struct, shutil
from pathlib import Path
sys.path.insert(0,"/home/chad/mame-mcp"); from mame_mcp.session import MameSession
ADDR=int(sys.argv[1],16) if len(sys.argv)>1 else 0xCC10
START=int(sys.argv[2]) if len(sys.argv)>2 else 1500
HERE=Path("/home/chad/supermn-snes/tools/mame-trace"); ENV=HERE/"record_env"
OUT=Path("/tmp/supermn-scratch/frame_%x"%ADDR); OUT.mkdir(parents=True,exist_ok=True)
for d in ("cfg","nvram"):
    if (ENV/d).exists():
        if (HERE/d).exists(): shutil.rmtree(HERE/d)
        shutil.copytree(ENV/d, HERE/d)
def regsA(r):
    v=[r["D%d"%i] for i in range(8)]+[r["A%d"%i] for i in range(7)]+[r["SP"]&0xFFFFFFFF, r.get("USP",0), r.get("SR",0)]
    return b"".join(struct.pack(">I",x&0xFFFFFFFF) for x in v)
s=MameSession(mame="mame", system="superman", rompath=str(HERE/"roms"), workdir=str(HERE), state_directory=str(HERE/"sta"),
              extra_args=["-playback","vplay.inp","-input_directory","/home/chad/supermn-snes/inp"])
try:
    s.launch(boot_wait=25); frame=0
    while frame < START-10:
        step=min(800,START-10-frame)
        r=s.cmd("capture_game_tick", addr=0xF00000, len=4, nth=step, maxFrames=step+400, timeout=180)
        if not r.get("registers"): print("ended @%d"%frame); break
        frame=r["frame"]
    print("ff to frame %d; arming capture_at_pc $%06X"%(frame,ADDR), flush=True)
    # REPRESENTATIVE capture: skip DEGENERATE invocations (e.g. all source ptrs a0-a4 == 0 -> the fn
    # does nothing / reads garbage), which produce false escape-vs-MAME REDs (the escape and MAME can
    # map a null/edge read differently, and val only injects $F0 work RAM). Walk nth=1.. until a call
    # with a non-zero A-register, or fall back to nth=1. Override with NTH=<n> env.
    import os as _os
    forced=_os.environ.get("NTH")
    def be32(d,o): return ((d[o]<<24)|(d[o+1]<<16)|(d[o+2]<<8)|d[o+3])&0xFFFFFF
    E=None
    for nth in ([int(forced)] if forced else range(1,25)):
        E=s.cmd("capture_at_pc", pc=ADDR, addr=0xF00000, len=0x10000, nth=nth, maxFrames=8000, timeout=300)
        if not E.get("registers"): break
        er=E["registers"]; aregs=[er.get("A%d"%i,0)&0xFFFFFF for i in range(5)]
        SP=er["SP"]&0xFFFFFF; ew=bytes.fromhex(E["hex"]); R=be32(ew, SP-0xF00000) if 0<=SP-0xF00000<0xFFFC else -1
        degenerate=all(a==0 for a in aregs)
        # also reject invocations whose [SP] (the rts return) is NOT a plausible 68K code address:
        # tail-dispatched/recursive entries (e.g. [SP]=$0CE4 self-loop, $3C0000 garbage) can't be
        # exit-captured (no real return to trap) and produce mismatched entry/exit pairs.
        badret = not (0x000400 <= R < 0x040000)
        skip = (degenerate or badret) and not forced
        print("  nth=%d frame=%d SP=%06X [SP]=%06X a0-a4=%s%s"%(nth,E.get("frame",0),SP,R&0xFFFFFF,[hex(a) for a in aregs],
              (" DEGENERATE-skip" if degenerate else " BADRET-skip") if skip else ""),flush=True)
        if forced or not skip: break
    assert E and E.get("registers"), "no $%06X hit: %r"%(ADDR,E)
    er=E["registers"]; ew=bytes.fromhex(E["hex"])
    print("$%06X entry frame=%d SP=%06X a6=%06X SR=%04X"%(ADDR,E["frame"],er["SP"]&0xFFFFFF,er["A6"]&0xFFFFFF,er.get("SR",0)),flush=True)
    (OUT/"entry_regs.bin").write_bytes(regsA(er)); (OUT/"entry_wram.bin").write_bytes(ew)
    print("wrote %s"%OUT,flush=True)
finally: s.stop()
