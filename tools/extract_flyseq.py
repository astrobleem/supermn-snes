#!/usr/bin/env python3
# Capture a DENSE sequence of adjacent game-ticks around the off-screen frame so we can find a tick
# that actually exercises entry_ce4's off-screen clamp and validate it against MAME (each tick's
# wramA is also the previous tick's wramB). Writes scratchpad/flyseq/s%02d.{regs,wram}.bin + frames.
import sys, struct, shutil
import os
from pathlib import Path
sys.path.insert(0, "/home/chad/mame-mcp")
from mame_mcp.session import MameSession
HERE = Path("/home/chad/supermn-snes/tools/mame-trace"); ENV = HERE / "record_env"
OUT = Path(os.environ.get('SUPERMN_SCRATCH', '/tmp/supermn-scratch') + '/flyseq')
for d in ("cfg", "nvram"):
    if (ENV/d).exists():
        if (HERE/d).exists(): shutil.rmtree(HERE/d)
        shutil.copytree(ENV/d, HERE/d)
if OUT.exists(): shutil.rmtree(OUT)
OUT.mkdir(parents=True)
def regsA_bytes(r):
    vals = [r["D%d" % i] for i in range(8)] + [r["A%d" % i] for i in range(7)]
    vals += [(r["SP"] + 60) & 0xFFFFFFFF, r["USP"], r["SR"]]
    return b"".join(struct.pack(">I", v & 0xFFFFFFFF) for v in vals)
TARGET = int(sys.argv[1]) if len(sys.argv) > 1 else 6468
N = int(sys.argv[2]) if len(sys.argv) > 2 else 22
s = MameSession(mame="mame", system="superman", rompath=str(HERE/"roms"), workdir=str(HERE),
                state_directory=str(HERE/"sta"),
                extra_args=["-playback", "vplay.inp", "-input_directory", "/home/chad/supermn-snes/inp"])
try:
    s.launch(boot_wait=25)
    frame = 0
    while frame < TARGET - 5:
        step = min(800, TARGET - 5 - frame)
        r = s.cmd("capture_game_tick", addr=0xF00000, len=4, nth=step, maxFrames=step + 400, timeout=180)
        if not r.get("registers"): break
        frame = r["frame"]; print("  drove to frame %d" % frame)
    frames = []
    for i in range(N):
        A = s.cmd("capture_game_tick", addr=0xF00000, len=0x4000, nth=1, maxFrames=200, timeout=60)
        (OUT/("s%02d.regs.bin" % i)).write_bytes(regsA_bytes(A["registers"]))
        (OUT/("s%02d.wram.bin" % i)).write_bytes(bytes.fromhex(A["hex"]))
        frames.append(A["frame"])
    print("captured %d adjacent ticks, frames %d..%d" % (N, frames[0], frames[-1]))
finally:
    s.stop()
