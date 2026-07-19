#!/usr/bin/env python3
"""R4 sound-truth: per-track SNES-side recordings for the by-ear pass.

Boots the production ROM, waits for the sound layer to arm, then FREEZES the
68K interpreter at the $0818 idle loop via the built-in PC-freeze so the
attract demo cannot enqueue contaminating SFX.  Each of the 21 music tracks
is then triggered through the real mailbox path (poke the $41:0100 ring copy
+ $41:0120 W, pulse FRAME_REQ $3300 so the 5A22's sound_tick drains it) and
recorded to its own WAV.  TAD playback is SPC-timer-paced, so music plays
correctly while the interpreter is frozen; recording lengths are counted in
EMULATED frames, not wall time.

Injection here is deliberate and documented: transport correctness was proven
in P3; this run exists to produce per-track listening material.  Organic
trigger evidence is a separate run (tools/r4_organic.py).
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
import time
import os
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, "/home/chad/Mesen2/python")

import mesen_mcp.session as _session

_session.validate_mesen_build = lambda *_args, **_kwargs: None
from mesen_mcp import McpSession

DEFAULT_ROM = ROOT / "build/interp.sfc"
DEFAULT_MESEN = Path("/home/chad/Mesen2/bin/linux-x64/Release/Mesen")

# cmd byte -> (vgm track name, record seconds = rip total + 8)
TRACKS = [
    (0x05, "01_Attract_Mode", 24),
    (0x19, "02_Coin", 12),
    (0x06, "03_Main_BGM_1", 107),
    (0x08, "04_Boss_BGM_1", 29),
    (0x09, "05_Main_BGM_2", 40),
    (0x0A, "06_Boss_BGM_2", 32),
    (0x14, "07_Round_Clear", 15),
    (0x07, "08_Main_BGM_3", 100),
    (0x0B, "09_Boss_BGM_3", 47),
    (0x0C, "10_Boss_BGM_4", 28),
    (0x0D, "11_Boss_BGM_5", 48),
    (0x15, "12_Continue", 21),
    (0x0E, "13_Round_5-1", 33),
    (0x0F, "14_Round_5-2", 31),
    (0x10, "15_Round_5-3", 28),
    (0x11, "16_Round_5-4", 31),
    (0x12, "17_Boss_BGM_6", 30),
    (0x13, "18_Boss_BGM_7", 48),
    (0x16, "19_Ending", 83),
    (0x17, "20_Name_Entry", 24),
    (0x18, "21_Game_Over", 16),
]


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
        self.stream.write(json.dumps({"event": event, "wall": time.time(), **fields}) + "\n")
        self.stream.flush()


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser()
    p.add_argument("--rom", type=Path, default=DEFAULT_ROM)
    p.add_argument("--mesen", type=Path, default=DEFAULT_MESEN)
    p.add_argument("--port", type=int, default=7469)
    p.add_argument("--output", type=Path,
                   default=ROOT / "build/recovery-20260712/r4-sound-truth/snes-tracks")
    p.add_argument("--arm-timeout-frames", type=int, default=12000)
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

    log = Recorder(args.output / "tracks.jsonl")
    log.emit("provenance", rom=str(rom), rom_sha256=sha256(rom),
             mesen=str(args.mesen), mesen_sha256=sha256(args.mesen),
             harness_sha256=sha256(Path(__file__).resolve()),
             method="PC-freeze at $0818 + mailbox injection + FRAME_REQ pulse; "
                    "recording lengths in emulated frames")

    def le16(b: bytes) -> int:
        return b[0] | (b[1] << 8)

    with McpSession(rom=rom, mesen=args.mesen, cwd=ROOT, port=args.port,
                    boot_wait=6.0, socket_timeout=300.0,
                    stderr_log=args.output / "emulator.stderr.log") as m:

        def r16(addr: int, mt: str = "Sa1Memory") -> int:
            return le16(m.read_memory(mt, addr, 2))

        def frames() -> int:
            return int(m.get_state().get("frameCount", 0))

        def wait_frames(n: int, poll: float = 2.0) -> None:
            target = frames() + n
            while frames() < target:
                time.sleep(poll)

        # 1. wait for the sound layer to arm (production self-arming)
        m.resume()
        start_frame = frames()
        while True:
            time.sleep(4.0)
            latch = r16(0x0768)
            loop_gate = r16(0x072E)
            f = frames()
            if latch != 0 or loop_gate != 0:
                log.emit("armed", frame=f, latch=latch, loop=loop_gate)
                break
            if f - start_frame > args.arm_timeout_frames:
                raise SystemExit("sound layer never armed")

        # give the armed system a moment, then freeze the interp at $0818
        wait_frames(300)
        m.write_memory("Sa1Memory", 0x0716, "00")
        m.write_memory("Sa1Memory", 0x0710, (0x0818).to_bytes(2, "little").hex())
        deadline = time.monotonic() + 120
        while r16(0x0712) != 1:
            if time.monotonic() > deadline:
                raise SystemExit("PC-freeze never fired")
            time.sleep(1.0)
        log.emit("frozen", frame=frames(), pc68k=hex(r16(0x0710)))

        def read_w() -> int:
            return m.read_memory("snesMemory", 0x410120, 1)[0]

        def inject(cmd: int) -> None:
            w = read_w()
            if not (0x20 <= w <= 0x3F):
                raise SystemExit(f"mailbox W out of range: {w:#x}")
            m.write_memory("snesMemory", 0x4100E0 + w, f"{cmd:02x}")
            nw = w + 1
            if nw >= 0x40:
                nw = 0x20
            m.write_memory("snesMemory", 0x410120, f"{nw:02x}")
            # FRAME_REQ pulse -> the 5A22 runs one per-tick pass incl. sound_tick
            req = m.read_memory("Sa1Memory", 0x3300, 1)[0]
            m.write_memory("Sa1Memory", 0x3300, f"{(req + 1) & 0xFF:02x}")
            # confirm the drain (last-cmd debug cell in 5A22-private WRAM)
            deadline = time.monotonic() + 20
            while m.read_memory("snesWorkRam", 0x1F17, 1)[0] != cmd:
                if time.monotonic() > deadline:
                    log.emit("drain_timeout", cmd=f"{cmd:02x}",
                             last=m.read_memory("snesWorkRam", 0x1F17, 1).hex())
                    # one retry pulse
                    req = m.read_memory("Sa1Memory", 0x3300, 1)[0]
                    m.write_memory("Sa1Memory", 0x3300, f"{(req + 1) & 0xFF:02x}")
                    deadline = time.monotonic() + 20
                time.sleep(0.5)
            log.emit("injected", cmd=f"{cmd:02x}", frame=frames())

        # 2. stop whatever attract music is playing, settle
        inject(0x00)
        wait_frames(180)

        # 3. per-track record
        for cmd, name, secs in TRACKS:
            wav = args.output / f"{name}_cmd{cmd:02X}.wav"
            log.emit("track_start", name=name, cmd=f"{cmd:02x}", seconds=secs,
                     frame=frames())
            m.record_audio(wav)
            inject(cmd)
            wait_frames(secs * 60)
            m.stop_audio()
            inject(0x00)
            wait_frames(180)
            log.emit("track_done", name=name, wav=str(wav),
                     wav_sha256=sha256(wav) if wav.is_file() else None)
            print(f"DONE {name}", flush=True)

        log.emit("all_done", frame=frames())
        print("ALL-DONE", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
