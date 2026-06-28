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
    E=s.cmd("capture_at_pc", pc=ADDR, addr=0xF00000, len=0x10000, nth=1, maxFrames=8000, timeout=300)
    assert E.get("registers"), "no $%06X hit: %r"%(ADDR,E)
    er=E["registers"]; ew=bytes.fromhex(E["hex"])
    print("$%06X entry frame=%d SP=%06X a6=%06X SR=%04X"%(ADDR,E["frame"],er["SP"]&0xFFFFFF,er["A6"]&0xFFFFFF,er.get("SR",0)),flush=True)
    (OUT/"entry_regs.bin").write_bytes(regsA(er)); (OUT/"entry_wram.bin").write_bytes(ew)
    print("wrote %s"%OUT,flush=True)
finally: s.stop()
