#!/usr/bin/env python3
# Extract a MAME flying-stage reference for ON-vs-MAME validation: replay vplay.inp to the flying
# stage (~frame 6476, where capture 320 had 16 off-screen tiles), then capture an ADJACENT game-tick
# pair A (regsA/wramA) and B (wramB = the next tick). Writes scratchpad/flytick/{regsA,wramA,wramB}.bin.
import sys, struct, shutil
import os
from pathlib import Path
sys.path.insert(0, "/home/chad/mame-mcp")
from mame_mcp.session import MameSession
HERE = Path("/home/chad/supermn-snes/tools/mame-trace")
ENV = HERE / "record_env"
OUT = Path(os.environ.get('SUPERMN_SCRATCH', '/tmp/supermn-scratch') + '/flytick')
for d in ("cfg", "nvram"):                      # restore the recording's boot env
    if (ENV/d).exists():
        if (HERE/d).exists(): shutil.rmtree(HERE/d)
        shutil.copytree(ENV/d, HERE/d)
OUT.mkdir(parents=True, exist_ok=True)
def regsA_bytes(r):
    vals = [r["D%d" % i] for i in range(8)] + [r["A%d" % i] for i in range(7)]
    vals += [(r["SP"] + 60) & 0xFFFFFFFF, r["USP"], r["SR"]]
    return b"".join(struct.pack(">I", v & 0xFFFFFFFF) for v in vals)

TARGET = int(sys.argv[1]) if len(sys.argv) > 1 else 6476
s = MameSession(mame="mame", system="superman", rompath=str(HERE/"roms"), workdir=str(HERE),
                state_directory=str(HERE/"sta"),
                extra_args=["-playback", "vplay.inp", "-input_directory", "/home/chad/supermn-snes/inp"])
try:
    s.launch(boot_wait=25)
    frame = 0
    while frame < TARGET - 10:
        step = min(800, TARGET - 10 - frame)
        r = s.cmd("capture_game_tick", addr=0xF00000, len=4, nth=step, maxFrames=step + 400, timeout=180)
        if not r.get("registers"): print("playback ended at frame %d" % frame); break
        frame = r["frame"]; print("  drove to frame %d" % frame)
    A = s.cmd("capture_game_tick", addr=0xF00000, len=0x4000, nth=1, maxFrames=200, timeout=60)
    B = s.cmd("capture_game_tick", addr=0xF00000, len=0x4000, nth=1, maxFrames=200, timeout=60)
    print("A frame=%d pc=%04X ; B frame=%d" % (A["frame"], A["pc"], B["frame"]))
    (OUT/"regsA.bin").write_bytes(regsA_bytes(A["registers"]))
    (OUT/"wramA.bin").write_bytes(bytes.fromhex(A["hex"]))
    (OUT/"wramB.bin").write_bytes(bytes.fromhex(B["hex"]))
    print("wrote flytick reference (A frame %d -> B frame %d)" % (A["frame"], B["frame"]))
finally:
    s.stop()
