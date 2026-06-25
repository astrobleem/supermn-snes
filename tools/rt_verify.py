#!/usr/bin/env python3
# Prove record->playback is deterministic in the bridge config (so a fresh recording will play
# back, unlike the original .inp made in a different MAME env). RECORD: drive_to_gameplay +
# a few inputs, clean-exit to finalize. RESTORE cfg/nvram. PLAYBACK: replay, confirm gameplay.
import sys, time, shutil
import os
from pathlib import Path
sys.path.insert(0, "/home/chad/mame-mcp")
from mame_mcp.session import MameSession, MameError
HERE = Path("/home/chad/supermn-snes/tools/mame-trace")
SNAP = Path(os.environ.get('SUPERMN_SCRATCH', '/tmp/supermn-scratch') + '/cfgsnap')

def snap():
    if SNAP.exists(): shutil.rmtree(SNAP)
    SNAP.mkdir(parents=True)
    for d in ("cfg", "nvram"):
        if (HERE/d).exists(): shutil.copytree(HERE/d, SNAP/d)
def restore():
    for d in ("cfg", "nvram"):
        if (SNAP/d).exists():
            if (HERE/d).exists(): shutil.rmtree(HERE/d)
            shutil.copytree(SNAP/d, HERE/d)

snap()
# ---- RECORD ----
rec = MameSession(mame="mame", system="superman", rompath=str(HERE/"roms"), workdir=str(HERE),
                  state_directory=str(HERE/"sta"),
                  extra_args=["-record", "rt.inp", "-input_directory", str(HERE)])
rec.launch(boot_wait=25)
res = rec.drive_to_gameplay()
print("RECORD drive_to_gameplay:", res)
for _ in range(3):
    rec.send_input("P1 Right", 1); rec.run_frames(10)
rec.send_input("P1 Right", 0); rec.run_frames(4)
try: rec.exec_lua("manager.machine:exit()")      # clean exit finalizes the .inp
except Exception: pass                            # MAME exits before replying -> malformed rsp
time.sleep(3); rec.stop()
inp = HERE/"rt.inp"
print("recorded rt.inp:", inp.stat().st_size if inp.exists() else "MISSING", "bytes")
restore()
# ---- PLAYBACK ----
pb = MameSession(mame="mame", system="superman", rompath=str(HERE/"roms"), workdir=str(HERE),
                 state_directory=str(HERE/"sta"),
                 extra_args=["-playback", "rt.inp", "-input_directory", str(HERE)])
pb.launch(boot_wait=25)
traj = []
for b in range(30):                               # ~450 frames, past boot+coin+start
    pb.run_frames(15)
    r = pb.get_regs(); pc = (r.get("PC") or r.get("CURPC", 0)) & 0xFFFFFF
    traj.append((b*15, pc))
cap = pb.cmd("capture_game_tick", addr=0xF00000, len=2, nth=2, maxFrames=400, timeout=20)
reached = bool(cap.get("registers"))
pb.stop()
print("PLAYBACK PC trajectory:", [("f%d" % f, hex(p)) for f, p in traj[::3]])
print("PLAYBACK GAME_TICK reached:", reached, "(pc=%s frame=%s)" % (cap.get("pc"), cap.get("frame")))
print("VERDICT:", "DETERMINISTIC ROUND-TRIP OK -- re-record will play back" if reached else
      "playback did NOT reach gameplay (recorded inputs did not start the game)")
