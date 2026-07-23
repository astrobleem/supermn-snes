#!/usr/bin/env python3
"""Capture organic audio from a gameplay checkpoint and screen it for gaps.

The production ROM and an existing gameplay save state are loaded, the real
controller is left idle, and audio is recorded while the emulator runs
normally.  No sound command, gate, or game-state injection is performed.
This is checkpointed audio/transport evidence, not cold-boot or FPS evidence.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import shutil
import sys
import time
import wave
from array import array
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, "/home/chad/Mesen2/python")

import mesen_mcp.session as _session

_session.validate_mesen_build = lambda *_args, **_kwargs: None
from mesen_mcp import McpSession


DEFAULT_NEXEN = Path(
    "/mnt/sdc1/Nexen-r5-20260712/"
    "bin/linux-x64/Release/linux-x64/publish/Nexen"
)
RING_BASE = 0x401C20
RING_SIZE = 0x20
RING_WPTR = 0x401C40
MBOX_BASE = 0x410100
MBOX_W = 0x410120


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--rom", type=Path, default=ROOT / "build/interp.sfc")
    parser.add_argument("--state", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--nexen", type=Path, default=DEFAULT_NEXEN)
    parser.add_argument("--port", type=int, default=7630)
    parser.add_argument("--video-frames", type=int, default=3600)
    parser.add_argument("--timeout", type=float, default=300.0)
    parser.add_argument("--poll-seconds", type=float, default=0.25)
    return parser.parse_args()


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def le16(data: bytes) -> int:
    return int.from_bytes(data, "little")


def take_screenshot(m: McpSession, target: Path) -> dict[str, Any]:
    response = m.take_screenshot(format="path")
    shutil.copy2(Path(response["path"]), target)
    return {
        "path": str(target),
        "sha256": sha256(target),
        "response": response,
    }


def sound_snapshot(m: McpSession) -> dict[str, Any]:
    def r16(address: int, memory_type: str = "Sa1Memory") -> int:
        return le16(m.read_memory(memory_type, address, 2))

    state = m.get_state()
    tad = bytes(m.read_memory("snesWorkRam", 0x1F00, 0x20))
    queue = bytes(m.read_memory("snesWorkRam", 0x0068, 2))
    ring = bytes(m.read_memory("snesMemory", RING_BASE, RING_SIZE))
    mailbox = bytes(m.read_memory("snesMemory", MBOX_BASE, RING_SIZE))
    return {
        "frame": int(state.get("frameCount", 0)),
        "tick": r16(0x0760),
        "halt": r16(0x004E),
        "pc68k": int.from_bytes(
            m.read_memory("Sa1Memory", 0x0040, 4), "little"
        ) & 0xFFFFFF,
        "gates": {
            "loop": r16(0x072E),
            "escape": r16(0x071A),
            "choke": r16(0x073A),
            "swin": r16(0x073C),
            "select": r16(0x0736),
            "cadence": r16(0x0734),
            "latch": r16(0x0768),
        },
        "ring": ring.hex(),
        "ring_wptr": int.from_bytes(
            m.read_memory("snesMemory", RING_WPTR, 4), "big"
        ),
        "mailbox": mailbox.hex(),
        "mailbox_w": m.read_memory("snesMemory", MBOX_W, 1)[0],
        "tad": {
            "raw": tad.hex(),
            "flags": tad[0x00],
            "audio_mode": tad[0x01],
            "state": tad[0x02],
            "previous_command": tad[0x05],
            "next_song": tad[0x0C],
            "next_command": tad[0x0D],
            "next_command_parameters": list(tad[0x0E:0x10]),
            "sound_tick_cursor": le16(tad[0x14:0x16]),
            "drained_count": tad[0x16],
            "last_arcade_command": tad[0x17],
            "observed_w": le16(tad[0x19:0x1B]),
            "sound_tick_calls": le16(tad[0x1C:0x1E]),
            "sfx_queue": queue[0],
            "sfx_pan": queue[1],
        },
    }


def new_ring_commands(previous_wptr: int, snapshot: dict[str, Any]) -> list[int]:
    current_wptr = int(snapshot["ring_wptr"])
    if not (
        0xF01C20 <= previous_wptr < 0xF01C40
        and 0xF01C20 <= current_wptr < 0xF01C40
    ):
        return []
    previous = previous_wptr - 0xF01C20
    current = current_wptr - 0xF01C20
    count = (current - previous) % RING_SIZE
    ring = bytes.fromhex(snapshot["ring"])
    return [ring[(previous + index) % RING_SIZE] for index in range(count)]


def quiet_runs(
    envelope: list[float],
    start: int,
    end: int,
    threshold: float,
    minimum_bins: int,
    bins_per_second: int,
) -> list[dict[str, float]]:
    runs: list[dict[str, float]] = []
    run_start: int | None = None
    for index in range(start, end + 1):
        quiet = index < end and envelope[index] <= threshold
        if quiet and run_start is None:
            run_start = index
        elif not quiet and run_start is not None:
            if index - run_start >= minimum_bins:
                runs.append(
                    {
                        "start_s": round(run_start / bins_per_second, 3),
                        "end_s": round(index / bins_per_second, 3),
                        "duration_s": round(
                            (index - run_start) / bins_per_second, 3
                        ),
                    }
                )
            run_start = None
    return runs


def analyze_wav(path: Path) -> dict[str, Any]:
    bins_per_second = 100
    with wave.open(str(path), "rb") as wav:
        channels = wav.getnchannels()
        sample_width = wav.getsampwidth()
        sample_rate = wav.getframerate()
        frame_count = wav.getnframes()
        raw = wav.readframes(frame_count)

    if sample_width != 2:
        raise RuntimeError(f"expected 16-bit PCM WAV, got {sample_width * 8}-bit")
    samples = array("h")
    samples.frombytes(raw)
    if sys.byteorder != "little":
        samples.byteswap()

    bin_frames = max(1, sample_rate // bins_per_second)
    bin_samples = bin_frames * channels
    envelope = []
    peak = 0
    for offset in range(0, len(samples) - bin_samples + 1, bin_samples):
        chunk = samples[offset : offset + bin_samples]
        if chunk:
            peak = max(peak, max(abs(value) for value in chunk))
            envelope.append(
                math.sqrt(sum(value * value for value in chunk) / len(chunk))
                / 32768.0
            )

    maximum_rms = max(envelope, default=0.0)
    threshold = max(maximum_rms * 0.02, 1e-4)
    active = [index for index, value in enumerate(envelope) if value > threshold]
    active_start = active[0] if active else 0
    active_end = active[-1] + 1 if active else 0
    gaps_200ms = quiet_runs(
        envelope,
        active_start,
        active_end,
        threshold,
        20,
        bins_per_second,
    )
    gaps_750ms = quiet_runs(
        envelope,
        active_start,
        active_end,
        threshold,
        75,
        bins_per_second,
    )
    return {
        "path": str(path),
        "sha256": sha256(path),
        "channels": channels,
        "sample_width_bits": sample_width * 8,
        "sample_rate": sample_rate,
        "frame_count": frame_count,
        "duration_s": round(frame_count / sample_rate, 3),
        "peak": round(peak / 32768.0, 6),
        "maximum_10ms_rms": round(maximum_rms, 6),
        "quiet_threshold": round(threshold, 8),
        "active_start_s": round(active_start / bins_per_second, 3),
        "active_end_s": round(active_end / bins_per_second, 3),
        "active_duration_s": round(
            (active_end - active_start) / bins_per_second, 3
        ),
        "internal_quiet_runs_200ms": gaps_200ms,
        "internal_quiet_runs_750ms": gaps_750ms,
    }


def main() -> int:
    args = parse_args()
    if args.video_frames <= 0 or args.timeout <= 0 or args.poll_seconds <= 0:
        raise SystemExit("frame, timeout, and poll arguments must be positive")
    for path in (args.rom, args.state, args.nexen):
        if not path.is_file():
            raise FileNotFoundError(path)
    rom_data = args.rom.read_bytes()
    if len(rom_data) != 0x400000:
        raise SystemExit("expected a 4 MiB production ROM")
    if int.from_bytes(rom_data[0x77E0:0x77E2], "little") != 0:
        raise SystemExit("refusing non-production ROM: TESTFLAG is set")
    args.output.mkdir(parents=True, exist_ok=False)

    wav_path = args.output / "gameplay.wav"
    stderr_path = args.output / "nexen.stderr.log"
    samples: list[dict[str, Any]] = []
    commands: list[dict[str, Any]] = []
    stop_reason = "exception"

    with McpSession(
        rom=args.rom.resolve(),
        mesen=args.nexen.resolve(),
        cwd=ROOT,
        port=args.port,
        boot_wait=6.0,
        socket_timeout=max(120.0, args.timeout),
        stderr_log=stderr_path,
    ) as m:
        m.pause()
        m.load_state(args.state.resolve())
        m.pause()
        m.tool("set_input", {"port": 0, "buttons": 0, "hold": True})
        start = sound_snapshot(m)
        samples.append(start)
        start_shot = take_screenshot(m, args.output / "start.png")
        previous_wptr = int(start["ring_wptr"])
        start_frame = int(start["frame"])
        deadline = time.monotonic() + args.timeout

        m.record_audio(wav_path)
        m.resume()
        try:
            while time.monotonic() < deadline:
                time.sleep(args.poll_seconds)
                sample = sound_snapshot(m)
                for command in new_ring_commands(previous_wptr, sample):
                    commands.append(
                        {
                            "frame": sample["frame"],
                            "tick": sample["tick"],
                            "command": command,
                            "command_hex": f"{command:02X}",
                        }
                    )
                previous_wptr = int(sample["ring_wptr"])
                if sample["tad"] != samples[-1]["tad"] or commands:
                    samples.append(sample)
                advanced = (int(sample["frame"]) - start_frame) & 0xFFFFFFFF
                if advanced >= args.video_frames:
                    stop_reason = "target_video_frames"
                    break
                if int(sample["halt"]):
                    stop_reason = "halt"
                    break
            else:
                stop_reason = "timeout"
        finally:
            m.pause()
            m.stop_audio()

        end = sound_snapshot(m)
        if end != samples[-1]:
            samples.append(end)
        end_shot = take_screenshot(m, args.output / "end.png")

    audio = analyze_wav(wav_path)
    verdict = {
        "target_window_completed": stop_reason == "target_video_frames",
        "no_halt": int(end["halt"]) == 0,
        "music_active": audio["active_duration_s"] >= audio["duration_s"] * 0.95,
        "no_internal_silence_750ms": not audio["internal_quiet_runs_750ms"],
    }
    result = {
        "scope": (
            "checkpointed organic gameplay audio; controller idle; no sound, "
            "gate, or game-state injection; not cold-boot or FPS evidence"
        ),
        "rom": str(args.rom.resolve()),
        "rom_sha256": sha256(args.rom),
        "state": str(args.state.resolve()),
        "state_sha256": sha256(args.state),
        "nexen": str(args.nexen.resolve()),
        "nexen_sha256": sha256(args.nexen),
        "requested_video_frames": args.video_frames,
        "stop_reason": stop_reason,
        "video_frames_advanced": (
            int(end["frame"]) - int(start["frame"])
        ) & 0xFFFFFFFF,
        "ticks_advanced": (int(end["tick"]) - int(start["tick"])) & 0xFFFF,
        "start": start,
        "end": end,
        "sound_state_changes": samples,
        "organic_commands": commands,
        "audio": audio,
        "screenshots": {"start": start_shot, "end": end_shot},
        "verdict": verdict,
    }
    result_path = args.output / "results.json"
    result_path.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
    print(json.dumps({"results": str(result_path), **verdict}, sort_keys=True))
    return 0 if all(verdict.values()) else 1


if __name__ == "__main__":
    raise SystemExit(main())
