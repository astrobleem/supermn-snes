#!/usr/bin/env python3
# Replay the user's vplay.inp in the recording's exact boot env and capture a dense spread of
# game-tick states across the gameplay, so the Mesen side can scan for the off-screen clamp.
import sys, struct, shutil
import os
from pathlib import Path
sys.path.insert(0, "/home/chad/mame-mcp")
from mame_mcp.session import MameSession
HERE = Path("/home/chad/supermn-snes/tools/mame-trace")
ENV = HERE/"record_env"
OUT = Path(os.environ.get('SUPERMN_SCRATCH', '/tmp/supermn-scratch') + '/ticks')

# restore the recording's boot env so playback matches the recording's boot
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

STEP = int(sys.argv[1]) if len(sys.argv) > 1 else 2
NCAP = int(sys.argv[2]) if len(sys.argv) > 2 else 150
s = MameSession(mame="mame", system="superman", rompath=str(HERE/"roms"), workdir=str(HERE),
                state_directory=str(HERE/"sta"),
                extra_args=["-playback", "vplay.inp", "-input_directory", "/home/chad/supermn-snes/inp"])
try:
    s.launch(boot_wait=25)
    # get to the first gameplay GAME_TICK (skip boot + the recorded coin/start)
    first = s.cmd("capture_game_tick", addr=0xF00000, len=0x4000, nth=2, maxFrames=1200, timeout=40)
    if not first.get("registers"):
        raise SystemExit("playback never reached gameplay (coin/start not effective?)")
    print("gameplay starts: pc=%04X frame=%d" % (first["pc"], first["frame"]))
    idx = 0
    (OUT/("t%03d.regs.bin" % idx)).write_bytes(regsA_bytes(first["registers"]))
    (OUT/("t%03d.wram.bin" % idx)).write_bytes(bytes.fromhex(first["hex"]))
    for k in range(NCAP):
        A = s.cmd("capture_game_tick", addr=0xF00000, len=0x4000, nth=STEP, maxFrames=300, timeout=40)
        if not A.get("registers"):
            print("gameplay ended at capture %d (.inp exhausted / back to attract)" % k); break
        idx += 1
        (OUT/("t%03d.regs.bin" % idx)).write_bytes(regsA_bytes(A["registers"]))
        (OUT/("t%03d.wram.bin" % idx)).write_bytes(bytes.fromhex(A["hex"]))
        if k % 10 == 0:
            print("  capture %3d: frame=%d" % (idx, A["frame"]))
    print("TOTAL captures:", idx + 1)
finally:
    s.stop()
