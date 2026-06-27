# Capture $00CC10's EXIT work-RAM (ground truth) at the RETURN address R (one instr past the rts),
# from the SAME deterministic FF that extract_frame.py used for the entry. R = [SP] read from the
# already-captured entry frame (entry_regs SP + entry_wram). Capturing at the rts itself ($00CC42)
# is WRONG: MAME read-taps fire at PREFETCH, so the rts-tap snapshots memory BEFORE the immediately-
# preceding store (e.g. $CC3E move.l a0,-$12(a6)) commits -> the last write is missing. At R every
# store of $00CC10 has retired. Playback is deterministic so R nth=1 = frame-N's $00CC10 return.
import sys, struct, shutil
from pathlib import Path
sys.path.insert(0,"/home/chad/mame-mcp"); from mame_mcp.session import MameSession
HERE=Path("/home/chad/supermn-snes/tools/mame-trace"); ENV=HERE/"record_env"
OUT=Path("/tmp/supermn-scratch/frame_cc10")
for d in ("cfg","nvram"):
    if (ENV/d).exists():
        if (HERE/d).exists(): shutil.rmtree(HERE/d)
        shutil.copytree(ENV/d, HERE/d)
def be32(d,o): return (d[o]<<24)|(d[o+1]<<16)|(d[o+2]<<8)|d[o+3]
entry=(OUT/"entry_wram.bin").read_bytes(); regs=(OUT/"entry_regs.bin").read_bytes()
SP=be32(regs,15*4)&0xFFFFFF; R=be32(entry, SP-0xF00000)&0xFFFFFF   # [SP] at entry = return addr
print("entry SP=$%06X  return R=[SP]=$%06X"%(SP,R),flush=True)
START=int(sys.argv[1]) if len(sys.argv)>1 else 1500
s=MameSession(mame="mame", system="superman", rompath=str(HERE/"roms"), workdir=str(HERE), state_directory=str(HERE/"sta"),
              extra_args=["-playback","vplay.inp","-input_directory","/home/chad/supermn-snes/inp"])
try:
    s.launch(boot_wait=25); frame=0
    while frame < START-10:
        step=min(800,START-10-frame)
        r=s.cmd("capture_game_tick", addr=0xF00000, len=4, nth=step, maxFrames=step+400, timeout=180)
        if not r.get("registers"): print("ended @%d"%frame); break
        frame=r["frame"]
    print("ff to frame %d; capture at return R=$%06X nth=1"%(frame,R),flush=True)
    X=s.cmd("capture_at_pc", pc=R, addr=0xF00000, len=0x10000, nth=1, maxFrames=8000, timeout=300)
    assert X.get("registers"), "no return hit at R=$%06X: %r"%(R,X)
    xr=X["registers"]; xw=bytes.fromhex(X["hex"])
    print("return frame=%d PC=$%06X SP=$%06X"%(X["frame"],xr["PC"]&0xFFFFFF,xr["SP"]&0xFFFFFF),flush=True)
    (OUT/"exit_wram.bin").write_bytes(xw)
    deltas=[(i, entry[i], xw[i]) for i in range(0x10000) if entry[i]!=xw[i]]
    print("entry->exit changed: %d bytes"%len(deltas),flush=True)
    for i,o,n in deltas: print("  $F0%04X: %02X -> %02X"%(i,o,n),flush=True)
    print("wrote exit_wram.bin",flush=True)
finally: s.stop()
