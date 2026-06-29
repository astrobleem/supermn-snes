# Capture a 68K function's EXIT work RAM (ground truth) at its RETURN address R (one instr past the
# rts), from the SAME deterministic FF as extract_frame.py. R = [SP] read from the captured entry
# frame. Tapping the rts itself is WRONG: MAME read-taps fire at PREFETCH, before the immediately-
# preceding store commits. Usage: extract_exit.py <hex-addr> [start-frame]  (matches extract_frame).
import sys, shutil, struct
from pathlib import Path
sys.path.insert(0,"/home/chad/mame-mcp"); from mame_mcp.session import MameSession
ADDR=int(sys.argv[1],16) if len(sys.argv)>1 else 0xCC10
START=int(sys.argv[2]) if len(sys.argv)>2 else 1500
HERE=Path("/home/chad/supermn-snes/tools/mame-trace"); ENV=HERE/"record_env"
OUT=Path("/tmp/supermn-scratch/frame_%x"%ADDR)
for d in ("cfg","nvram"):
    if (ENV/d).exists():
        if (HERE/d).exists(): shutil.rmtree(HERE/d)
        shutil.copytree(ENV/d, HERE/d)
def be32(d,o): return (d[o]<<24)|(d[o+1]<<16)|(d[o+2]<<8)|d[o+3]
entry=(OUT/"entry_wram.bin").read_bytes(); regs=(OUT/"entry_regs.bin").read_bytes()
SP=be32(regs,15*4)&0xFFFFFF; R=be32(entry, SP-0xF00000)&0xFFFFFF   # [SP] at entry = return addr
print("$%06X: entry SP=$%06X  return R=[SP]=$%06X"%(ADDR,SP,R),flush=True)
s=MameSession(mame="mame", system="superman", rompath=str(HERE/"roms"), workdir=str(HERE), state_directory=str(HERE/"sta"),
              extra_args=["-playback","vplay.inp","-input_directory","/home/chad/supermn-snes/inp"])
try:
    s.launch(boot_wait=25); frame=0
    while frame < START-10:
        step=min(800,START-10-frame)
        r=s.cmd("capture_game_tick", addr=0xF00000, len=4, nth=step, maxFrames=step+400, timeout=180)
        if not r.get("registers"): break
        frame=r["frame"]
    # INVOCATION-CONSISTENT: pin the exit capture to the SAME call as the entry frame. At this
    # function's rts, SP = entry_SP + 4 (the frame is popped, then the return is popped). exp_sp
    # filters R-hits to that stack depth so a different invocation's return at the shared R isn't
    # captured (the old nth=1 grabbed the first R hit -> entry/exit could mismatch -> spurious REDs).
    ESP=(SP+4)&0xFFFFFF
    print("ff to %d; capture at return R=$%06X exp_sp=$%06X"%(frame,R,ESP),flush=True)
    X=s.cmd("capture_at_pc", pc=R, addr=0xF00000, len=0x10000, nth=1, exp_sp=ESP, maxFrames=8000, timeout=300)
    assert X.get("registers"), "no return hit at R=$%06X exp_sp=$%06X: %r"%(R,ESP,X)
    xw=bytes.fromhex(X["hex"])
    print("return frame=%d PC=$%06X SP=$%06X"%(X["frame"],X["registers"]["PC"]&0xFFFFFF,X["registers"]["SP"]&0xFFFFFF),flush=True)
    (OUT/"exit_wram.bin").write_bytes(xw)
    xr=X["registers"]   # registers at R = the function's net output (a7 popped)
    ev=[xr["D%d"%i] for i in range(8)]+[xr["A%d"%i] for i in range(7)]+[xr["SP"]&0xFFFFFFFF]
    (OUT/"exit_regs.bin").write_bytes(b"".join(struct.pack(">I",x&0xFFFFFFFF) for x in ev))
    deltas=[(i,entry[i],xw[i]) for i in range(0x10000) if entry[i]!=xw[i]]
    print("entry->exit changed: %d bytes"%len(deltas),flush=True)
    for i,o,n in deltas[:50]: print("  $F0%04X: %02X -> %02X"%(i,o,n),flush=True)
    print("wrote exit_wram.bin",flush=True)
finally: s.stop()
