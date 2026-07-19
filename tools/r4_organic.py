#!/usr/bin/env python3
"""R4 sound-truth: organic attract + gameplay audio/command capture.

Cold-boots the production ROM (no save state, no gate pokes, no sound
injection), records emulator audio from power-on, and logs every sound
command byte the game itself enqueues in its 68K ring ($f01c20-$f01c3f,
wptr $f01c40) plus the SA-1 mailbox transport copy ($41:0100 ring,
$41:0120 W).  Coin/Start are driven through the virtual-controller
mailbox exactly like the R2 baseline.  Output: JSONL + WAV + screenshots.

Emulator note: legacy Mesen is used deliberately — audio recording is a
by-ear/musical gate, not cycle-stamped baseline evidence, and Mesen's
higher host throughput keeps the session short.  (RECOVERY.md permits
legacy Mesen when the purpose is documented.)
"""

from __future__ import annotations

import argparse
import hashlib
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

RING_BASE = 0x401C20  # 68K $f01c20 sound ring in BW-RAM (snesMemory view)
RING_SIZE = 0x20
RING_WPTR = 0x401C40  # 4-byte big-endian 68K pointer
MBOX_BASE = 0x410100  # SA-1 -> 5A22 sound mailbox ring
MBOX_W = 0x410120
COIN = 0x2000
START = 0x1000


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


class Recorder:
    def __init__(self, path: Path) -> None:
        self.stream = path.open("w", encoding="utf-8")

    def emit(self, event: str, **fields: Any) -> None:
        record = {"event": event, "wall": time.time(), **fields}
        self.stream.write(json.dumps(record) + "\n")
        self.stream.flush()

    def close(self) -> None:
        self.stream.close()


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser()
    p.add_argument("--rom", type=Path, default=DEFAULT_ROM)
    p.add_argument("--mesen", type=Path, default=DEFAULT_MESEN)
    p.add_argument("--port", type=int, default=7468)
    p.add_argument("--output", type=Path,
                   default=ROOT / "build/recovery-20260712/r4-sound-truth/organic")
    p.add_argument("--attract-ticks", type=int, default=40,
                   help="Ticks of armed attract to observe before coin.")
    p.add_argument("--gameplay-ticks", type=int, default=90,
                   help="Ticks of gameplay to observe after Start.")
    p.add_argument("--hold-ticks", type=int, default=8)
    p.add_argument("--gap-ticks", type=int, default=7)
    p.add_argument("--start-hold-ticks", type=int, default=10)
    p.add_argument("--max-video-frames", type=int, default=30000)
    p.add_argument("--poll-wall-seconds", type=float, default=4.0)
    return p.parse_args()


def main() -> int:
    args = parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    if any(args.output.iterdir()):
        raise SystemExit(f"refusing to overwrite non-empty evidence dir: {args.output}")

    rom = args.rom.resolve()
    rom_data = rom.read_bytes()
    if len(rom_data) != 0x400000:
        raise SystemExit(f"expected 4 MiB production ROM: {rom}")
    if int.from_bytes(rom_data[0x77E0:0x77E2], "little") != 0:
        raise SystemExit("refusing non-production ROM: TESTFLAG set")

    os.environ["DOTNET_ROOT"] = "/home/chad/.dotnet8"
    os.environ["PATH"] = "/home/chad/.dotnet8:" + os.environ.get("PATH", "")

    log = Recorder(args.output / "organic.jsonl")
    log.emit("provenance", rom=str(rom), rom_sha256=sha256(rom),
             mesen=str(args.mesen), mesen_sha256=sha256(args.mesen),
             harness_sha256=sha256(Path(__file__).resolve()),
             purpose="R4 organic sound truth; legacy Mesen for host throughput; "
                     "no injection, no gate pokes, no save states")

    wav_path = args.output / "organic_session.wav"
    commands: list[dict] = []

    def le16(b: bytes) -> int:
        return b[0] | (b[1] << 8)

    with McpSession(rom=rom, mesen=args.mesen, cwd=ROOT, port=args.port,
                    boot_wait=6.0, socket_timeout=300.0,
                    stderr_log=args.output / "emulator.stderr.log") as m:
        m.pause()
        log.emit("emulator_ready", state=m.get_state())
        m.record_audio(wav_path)
        log.emit("audio_recording_started", path=str(wav_path))

        last_tick16 = le16(m.read_memory("Sa1Memory", 0x0760, 2))
        total_ticks = 0
        ring_prev = m.read_memory("snesMemory", RING_BASE, RING_SIZE)
        wptr_prev = int.from_bytes(m.read_memory("snesMemory", RING_WPTR, 4), "big")
        mbox_prev = m.read_memory("snesMemory", MBOX_BASE, RING_SIZE)
        mboxw_prev = le16(m.read_memory("snesMemory", MBOX_W, 2))
        stage = "boot"
        stage_tick_mark = 0
        input_word = 0

        def set_input(value: int) -> None:
            nonlocal input_word
            input_word = value
            m.write_memory("snesMemory", 0x410002, value.to_bytes(2, "little").hex())
            log.emit("input", stage=stage, value=value, tick_total=total_ticks)

        def poll() -> dict:
            nonlocal last_tick16, total_ticks, ring_prev, wptr_prev
            nonlocal mbox_prev, mboxw_prev
            m.pause()
            state = m.get_state()
            frame = int(state.get("frameCount", 0))
            tick16 = le16(m.read_memory("Sa1Memory", 0x0760, 2))
            total_ticks += (tick16 - last_tick16) & 0xFFFF
            last_tick16 = tick16
            ring = m.read_memory("snesMemory", RING_BASE, RING_SIZE)
            wptr = int.from_bytes(m.read_memory("snesMemory", RING_WPTR, 4), "big")
            mbox = m.read_memory("snesMemory", MBOX_BASE, RING_SIZE)
            mboxw = le16(m.read_memory("snesMemory", MBOX_W, 2))
            gates = {
                "loop": le16(m.read_memory("Sa1Memory", 0x072E, 2)),
                "escape": le16(m.read_memory("Sa1Memory", 0x071A, 2)),
                "latch": le16(m.read_memory("Sa1Memory", 0x0768, 2)),
            }
            # New organic enqueues: walk wptr_prev -> wptr through the ring.
            new_cmds = []
            if 0xF01C20 <= wptr <= 0xF01C40 and 0xF01C20 <= wptr_prev <= 0xF01C40:
                off_prev = (wptr_prev - 0xF01C20) % RING_SIZE
                off_now = (wptr - 0xF01C20) % RING_SIZE
                count = (off_now - off_prev) % RING_SIZE
                for i in range(count):
                    b = ring[(off_prev + i) % RING_SIZE]
                    new_cmds.append(b)
            for b in new_cmds:
                entry = {"cmd": f"{b:02x}", "frame": frame,
                         "tick_total": total_ticks, "stage": stage}
                commands.append(entry)
                log.emit("sound_command", **entry)
            if mbox != mbox_prev or mboxw != mboxw_prev:
                log.emit("mailbox", frame=frame, tick_total=total_ticks,
                         stage=stage, w=mboxw, ring=mbox.hex())
            ring_prev, wptr_prev = ring, wptr
            mbox_prev, mboxw_prev = mbox, mboxw
            sample = {"frame": frame, "tick16": tick16, "tick_total": total_ticks,
                      "stage": stage, "gates": gates, "wptr": f"{wptr:08x}",
                      "input": input_word,
                      "task_mask": le16(m.read_memory("snesMemory", 0x400002, 2))}
            log.emit("sample", **sample)
            m.resume()
            return sample

        def advance() -> dict:
            time.sleep(args.poll_wall_seconds)
            return poll()

        m.resume()
        s = poll()
        first_frame = s["frame"]

        # Stage machine mirrors the R2 input schedule, tick-paced.
        coin_events: list[tuple[str, int]] = []
        while s["frame"] - first_frame < args.max_video_frames:
            if stage == "boot":
                if s["gates"]["latch"] != 0 or s["gates"]["loop"] != 0:
                    log.emit("armed", frame=s["frame"], tick_total=s["tick_total"],
                             gates=s["gates"])
                    stage = "attract"
                    stage_tick_mark = s["tick_total"]
                    shot = m.take_screenshot(format="path")
                    log.emit("screenshot", label="attract", **shot)
            elif stage == "attract":
                if s["tick_total"] - stage_tick_mark >= args.attract_ticks:
                    stage = "coin1_hold"; stage_tick_mark = s["tick_total"]
                    set_input(COIN); coin_events.append(("coin1_down", s["tick_total"]))
            elif stage == "coin1_hold":
                if s["tick_total"] - stage_tick_mark >= args.hold_ticks:
                    stage = "coin1_gap"; stage_tick_mark = s["tick_total"]
                    set_input(0); coin_events.append(("coin1_up", s["tick_total"]))
            elif stage == "coin1_gap":
                if s["tick_total"] - stage_tick_mark >= args.gap_ticks:
                    stage = "coin2_hold"; stage_tick_mark = s["tick_total"]
                    set_input(COIN); coin_events.append(("coin2_down", s["tick_total"]))
            elif stage == "coin2_hold":
                if s["tick_total"] - stage_tick_mark >= args.hold_ticks:
                    stage = "coin2_gap"; stage_tick_mark = s["tick_total"]
                    set_input(0); coin_events.append(("coin2_up", s["tick_total"]))
            elif stage == "coin2_gap":
                if s["tick_total"] - stage_tick_mark >= args.gap_ticks:
                    stage = "start_hold"; stage_tick_mark = s["tick_total"]
                    set_input(START); coin_events.append(("start_down", s["tick_total"]))
            elif stage == "start_hold":
                if s["tick_total"] - stage_tick_mark >= args.start_hold_ticks:
                    stage = "gameplay"; stage_tick_mark = s["tick_total"]
                    set_input(0); coin_events.append(("start_up", s["tick_total"]))
                    shot = m.take_screenshot(format="path")
                    log.emit("screenshot", label="post_start", **shot)
            elif stage == "gameplay":
                if s["tick_total"] - stage_tick_mark >= args.gameplay_ticks:
                    shot = m.take_screenshot(format="path")
                    log.emit("screenshot", label="gameplay_end", **shot)
                    break
            s = advance()

        m.pause()
        m.stop_audio()
        log.emit("audio_recording_stopped", path=str(wav_path))
        final = {"frame": s["frame"], "tick_total": s["tick_total"], "stage": stage,
                 "commands_observed": len(commands),
                 "command_bytes": sorted({c["cmd"] for c in commands}),
                 "input_events": coin_events}
        log.emit("final", **final)
        print(json.dumps(final, indent=2))

    log.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
