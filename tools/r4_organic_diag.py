#!/usr/bin/env python3
"""R4 diagnostic: why does the port enqueue no organic sound commands?

Two discriminators in one session:

A. STATE ALIGNMENT — screenshots at ticks ~700/800/900 of attract to compare
   against MAME's frame-805 title screen (is the attract sequencer reaching
   the music-trigger state at all?).

B. ESCAPE INVOLVEMENT — save a state at tick ~950, then drive a coin twice:
   once with production escapes armed, once with the accelerator gates
   ($072E/$071A/$073A) disarmed (pure interpretation).  If $19 is enqueued
   only when disarmed, a native escape covers the enqueue path unfaithfully.

Ring evidence = the 68K ring wptr at $40:1c40 plus ring bytes, as in
tools/r4_organic.py.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, "/home/chad/Mesen2/python")

import mesen_mcp.session as _session

_session.validate_mesen_build = lambda *_args, **_kwargs: None
from mesen_mcp import McpSession

DEFAULT_ROM = ROOT / "build/interp.sfc"
DEFAULT_MESEN = Path("/home/chad/Mesen2/bin/linux-x64/Release/Mesen")
COIN = 0x2000


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser()
    p.add_argument("--rom", type=Path, default=DEFAULT_ROM)
    p.add_argument("--mesen", type=Path, default=DEFAULT_MESEN)
    p.add_argument("--port", type=int, default=7472)
    p.add_argument("--output", type=Path,
                   default=ROOT / "build/recovery-20260712/r4-sound-truth/diag")
    return p.parse_args()


def main() -> int:
    args = parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    log_path = args.output / "diag.jsonl"
    log = log_path.open("w")

    def emit(event: str, **fields: Any) -> None:
        log.write(json.dumps({"event": event, "wall": time.time(), **fields}) + "\n")
        log.flush()

    os.environ["DOTNET_ROOT"] = "/home/chad/.dotnet8"
    os.environ["PATH"] = "/home/chad/.dotnet8:" + os.environ.get("PATH", "")

    def le16(b: bytes) -> int:
        return b[0] | (b[1] << 8)

    with McpSession(rom=args.rom.resolve(), mesen=args.mesen, cwd=ROOT,
                    port=args.port, boot_wait=6.0, socket_timeout=300.0,
                    stderr_log=args.output / "emulator.stderr.log") as m:

        def tick16() -> int:
            return le16(m.read_memory("Sa1Memory", 0x0760, 2))

        def wptr() -> int:
            return int.from_bytes(m.read_memory("snesMemory", 0x401C40, 4), "big")

        def ring() -> str:
            return m.read_memory("snesMemory", 0x401C20, 0x20).hex()

        def gates() -> dict:
            return {"loop": le16(m.read_memory("Sa1Memory", 0x072E, 2)),
                    "escape": le16(m.read_memory("Sa1Memory", 0x071A, 2)),
                    "choke": le16(m.read_memory("Sa1Memory", 0x073A, 2)),
                    "latch": le16(m.read_memory("Sa1Memory", 0x0768, 2))}

        def shot(label: str) -> None:
            s = m.take_screenshot(format="path")
            src = Path(s["path"])
            if src.is_file():
                import shutil
                shutil.copy2(src, args.output / f"{label}.png")
            emit("screenshot", label=label, **s)

        total = 0
        last = tick16()

        def ticks_now() -> int:
            nonlocal total, last
            t = tick16()
            total += (t - last) & 0xFFFF
            last = t
            return total

        # boot to arm
        m.resume()
        while True:
            time.sleep(4.0)
            g = gates()
            if g["latch"] != 0 or g["loop"] != 0:
                emit("armed", gates=g, frame=m.get_state().get("frameCount"))
                break
        total = 0
        last = tick16()

        # A: attract-state screenshots at ~700/800/900
        for target in (700, 800, 900):
            while ticks_now() < target:
                time.sleep(4.0)
            m.pause()
            shot(f"attract_tick{target}")
            emit("attract_probe", tick=total, wptr=f"{wptr():08x}",
                 task_mask=le16(m.read_memory("snesMemory", 0x400002, 2)))
            m.resume()

        # B: save state at ~950
        while ticks_now() < 950:
            time.sleep(4.0)
        m.pause()
        state_path = args.output / "attract_t950.mss"
        m.save_state(state_path)
        emit("state_saved", tick=total, path=str(state_path))

        def coin_probe(label: str, disarm: bool) -> dict:
            """From the saved state: optionally disarm gates, coin, watch the ring."""
            m.load_state(state_path)
            m.pause()
            if disarm:
                for addr in (0x072E, 0x071A, 0x073A):
                    m.write_memory("Sa1Memory", addr, "0000")
            g0 = gates()
            w0, r0 = wptr(), ring()
            m.resume()
            # coin down 10 ticks, up, then observe 60 ticks
            t0 = tick16()
            m.write_memory("snesMemory", 0x410002, COIN.to_bytes(2, "little").hex())
            while ((tick16() - t0) & 0xFFFF) < 10:
                time.sleep(2.0)
            m.write_memory("snesMemory", 0x410002, "0000")
            while ((tick16() - t0) & 0xFFFF) < 70:
                time.sleep(2.0)
            m.pause()
            w1, r1 = wptr(), ring()
            res = {"label": label, "gates": g0, "wptr_before": f"{w0:08x}",
                   "wptr_after": f"{w1:08x}", "ring_before": r0, "ring_after": r1,
                   "enqueued": w1 != w0}
            emit("coin_probe", **res)
            m.resume()
            return res

        armed_res = coin_probe("escapes_armed", disarm=False)
        disarmed_res = coin_probe("gates_disarmed", disarm=True)

        verdict = {
            "armed_enqueued": armed_res["enqueued"],
            "disarmed_enqueued": disarmed_res["enqueued"],
        }
        emit("verdict", **verdict)
        print(json.dumps(verdict, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
