# Capture $00CC10's entry frame (regfile + 64KB work RAM) from MAME's deterministic playthrough.
# $00CC10 is frame-sharing (reads caller's a6 frame, no own link) -> the 64KB carries the frame.
import sys, struct, shutil
from pathlib import Path
sys.path.insert(0,"/home/chad/mame-mcp"); from mame_mcp.session import MameSession
HERE=Path("/home/chad/supermn-snes/tools/mame-trace"); ENV=HERE/"record_env"
OUT=Path("/tmp/supermn-scratch/frame_cc10"); OUT.mkdir(parents=True,exist_ok=True)
for d in ("cfg","nvram"):
    if (ENV/d).exists():
        if (HERE/d).exists(): shutil.rmtree(HERE/d)
        shutil.copytree(ENV/d, HERE/d)
def regsA(r):
    v=[r["D%d"%i] for i in range(8)]+[r["A%d"%i] for i in range(7)]+[r["SP"]&0xFFFFFFFF, r.get("USP",0), r.get("SR",0)]
    return b"".join(struct.pack(">I",x&0xFFFFFFFF) for x in v)
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
    print("ff to frame %d; arming capture_at_pc $00CC10"%frame, flush=True)
    E=s.cmd("capture_at_pc", pc=0xCC10, addr=0xF00000, len=0x10000, nth=1, maxFrames=8000, timeout=300)
    assert E.get("registers"), "no $00CC10 hit: %r"%E
    er=E["registers"]; ew=bytes.fromhex(E["hex"])
    print("CC10 entry frame=%d a6=%06X a5=%06X SR=%04X D7=%08X"%(E["frame"],er["A6"]&0xFFFFFF,er["A5"]&0xFFFFFF,er.get("SR",0),er["D7"]),flush=True)
    (OUT/"entry_regs.bin").write_bytes(regsA(er)); (OUT/"entry_wram.bin").write_bytes(ew)
    print("wrote frame_cc10",flush=True)
finally: s.stop()
