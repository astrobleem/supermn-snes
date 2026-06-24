#!/usr/bin/env python3
"""Reusable any-frame lockstep extraction, built on the MAME MCP live session
(mame-mcp/mame_mcp/session.py). Loads a gameplay save state and pulls the
regsA/wramA/wramB triple at a target GAME_TICK via the bridge's capture_game_tick.

  python3 tools/mame_extract.py <state> <nth> [outdir]
    state  : MAME save-state name under tools/mame-trace/sta/superman/ (e.g. combat1000)
    nth    : capture at the Nth GAME_TICK after load (regsA/wramA); wramB = the next tick

Writes <outdir>/regsA.bin (D0-D7,A0-A6,A7,USP,SR big-endian longs), wramA.bin, wramB.bin
(16KB each). Fresh boot hangs at $0818 (see memory mame-fresh-boot-hang), so a gameplay
save state is required.

$AC (the 68K instr/tick the interp's IRQ is paced to): determine it EMPIRICALLY, not via a
MAME trace (a -debug noloop trace can't run after a state-load in MAME 0.287 -- execution
stalls). Run lockstep.py on the extracted triple; it prints "interp 68K instr count B0->B1
= N" (the tick length). Set $AC = N - 4 (the IRQ fires ~4 instrs before the $3A92 boundary).
For gameplay ticks this is ~0x2F60 and is stable across ticks. VALIDATED: combat1000 tick 3
round-trips through lockstep.py at $AC=0x2F60 with a 4-byte diff (all sound/sub-CPU residual,
no logic divergence) -- i.e. the interp reproduces MAME's next frame, confirming the triple.
"""
import sys, struct
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
sys.path.insert(0, "/home/chad/mame-mcp")
from mame_mcp.session import MameSession

HERE = Path(__file__).resolve().parent / "mame-trace"


def regsA_bytes(reg):
    """lockstep regsA layout: D0-D7, A0-A6, A7(=SP+60 to undo the GAME_TICK movem), USP, SR."""
    vals = [reg["D%d" % i] for i in range(8)] + [reg["A%d" % i] for i in range(7)]
    vals += [(reg["SP"] + 60) & 0xFFFFFFFF, reg["USP"], reg["SR"]]
    return b"".join(struct.pack(">I", v & 0xFFFFFFFF) for v in vals)


def extract(state, nth, outdir, mame="mame"):
    outdir = Path(outdir); outdir.mkdir(parents=True, exist_ok=True)
    sess = MameSession(mame=mame, system="superman", rompath=str(HERE / "roms"),
                       workdir=str(HERE), state_directory=str(HERE / "sta"))
    try:
        sess.launch(boot_wait=25)
        sess.load_state(state); sess.run_frames(4)            # let the load apply
        A = sess.cmd("capture_game_tick", addr=0xF00000, len=0x4000, nth=nth, timeout=60)
        B = sess.cmd("capture_game_tick", addr=0xF00000, len=0x4000, nth=1, timeout=60)
        if not A.get("registers") or not B.get("hex"):
            raise SystemExit("GAME_TICK not reached (state not gameplay, or nth too high)")
        r = A["registers"]
        (outdir / "regsA.bin").write_bytes(regsA_bytes(r))
        (outdir / "wramA.bin").write_bytes(bytes.fromhex(A["hex"]))
        (outdir / "wramB.bin").write_bytes(bytes.fromhex(B["hex"]))
        print("extracted %s tick=%d -> %s" % (state, nth, outdir))
        print("  A pc=%04X frame=%d a5=%06X entry_a7=%06X ; B frame=%d"
              % (A["pc"], A["frame"], r["A5"], (r["SP"] + 60) & 0xFFFFFF, B["frame"]))
    finally:
        sess.stop()


if __name__ == "__main__":
    if len(sys.argv) < 3:
        print(__doc__); sys.exit(1)
    extract(sys.argv[1], int(sys.argv[2]), sys.argv[3] if len(sys.argv) > 3 else ".")
