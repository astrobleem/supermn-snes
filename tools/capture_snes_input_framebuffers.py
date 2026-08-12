#!/usr/bin/env python3
"""Capture every framebuffer while replaying real controller input from a state.

This is a same-emulator continuation diagnostic.  It loads one retained state,
records an emulator movie using only the MCP controller path, then replays that
movie one frame at a time while retaining every framebuffer and PPU snapshot.
This avoids legacy Mesen's zero-frame one-frame input command without skipping
intervening frames.  It never writes ROM, game RAM, renderer RAM, or gate state.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
sys.path.insert(0, "/home/chad/Mesen2/python")

import capture_mesen211_transitions as capture  # noqa: E402
from gameplay_acceptance_contract import unknown_diagnostic_gate  # noqa: E402
import mesen_mcp.session as _session  # noqa: E402

_session.validate_mesen_build = lambda *_args, **_kwargs: None
from mesen_mcp import McpSession  # noqa: E402


BUTTONS = {
    "neutral": 0,
    "right": McpSession.BTN_RIGHT,
    "left": McpSession.BTN_LEFT,
    "up": McpSession.BTN_UP,
    "down": McpSession.BTN_DOWN,
    "b": McpSession.BTN_B,
    "b+right": McpSession.BTN_B | McpSession.BTN_RIGHT,
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--rom", type=Path, required=True)
    parser.add_argument("--state", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--emulator", type=Path, required=True)
    parser.add_argument("--port", type=int, default=9270)
    parser.add_argument("--buttons", choices=sorted(BUTTONS), required=True)
    parser.add_argument("--frames", type=int, required=True)
    parser.add_argument("--checkpoint-step", type=int, default=30)
    parser.add_argument(
        "--movie",
        type=Path,
        help="reuse an already recorded CurrentState input movie",
    )
    parser.add_argument(
        "--movie-frames",
        type=int,
        help="actual emulated frames in --movie (required with --movie)",
    )
    return parser.parse_args()


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def configure_dotnet(emulator: Path) -> None:
    selected = (
        "/home/chad/.dotnet10"
        if emulator.name == "Nexen"
        else "/home/chad/.dotnet8"
    )
    other = (
        "/home/chad/.dotnet8"
        if selected.endswith("dotnet10")
        else "/home/chad/.dotnet10"
    )
    os.environ["DOTNET_ROOT"] = selected
    existing = [
        item
        for item in os.environ.get("PATH", "").split(":")
        if item and item not in (selected, other)
    ]
    os.environ["PATH"] = ":".join([selected, other, *existing])


def advance_one(m: McpSession) -> dict[str, Any]:
    before = int(m.get_state().get("frameCount", 0))
    responses: list[dict[str, Any]] = []
    for _attempt in range(8):
        response = m.run_frames(1)
        m.pause()
        after = int(m.get_state().get("frameCount", 0))
        responses.append(response)
        if after == before + 1:
            return {"before": before, "after": after, "responses": responses}
        if after != before:
            raise RuntimeError(
                f"one-frame movie playback advanced {after - before} frames: "
                f"{responses}"
            )
    raise RuntimeError(f"one-frame movie playback made no progress: {responses}")


def main() -> int:
    args = parse_args()
    if args.frames <= 0 or args.checkpoint_step <= 0:
        raise SystemExit("frame counts must be positive")
    if (args.movie is None) != (args.movie_frames is None):
        raise SystemExit("--movie and --movie-frames must be supplied together")
    if args.movie_frames is not None and args.movie_frames <= 0:
        raise SystemExit("--movie-frames must be positive")
    for label, path in (
        ("ROM", args.rom),
        ("state", args.state),
        ("emulator", args.emulator),
    ):
        if not path.is_file():
            raise FileNotFoundError(f"{label} not found: {path}")
    rom = args.rom.resolve()
    if rom.stat().st_size != 0x400000:
        raise SystemExit("expected a 4 MiB production ROM")
    if int.from_bytes(rom.read_bytes()[0x77E0:0x77E2], "little") != 0:
        raise SystemExit("refusing non-production ROM: TESTFLAG is set")

    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=False)
    configure_dotnet(args.emulator)
    button_mask = BUTTONS[args.buttons]
    rows: list[dict[str, Any]] = []
    provenance = {
        "scope": (
            "same-emulator retained-state controller movie and frame-exact "
            "framebuffer replay; controller input only; no runtime memory writes"
        ),
        "rom": str(rom),
        "rom_sha256": sha256(rom),
        "state": str(args.state.resolve()),
        "state_sha256": sha256(args.state),
        "emulator": str(args.emulator.resolve()),
        "emulator_sha256": sha256(args.emulator),
        "buttons": args.buttons,
        "button_mask": button_mask,
        "frames": args.frames,
        "checkpoint_step": args.checkpoint_step,
        "runtime_memory_writes": [],
    }

    if args.movie is not None:
        movie_path = args.movie.resolve()
        if not movie_path.is_file():
            raise FileNotFoundError(f"movie not found: {movie_path}")
        recorded_frames = int(args.movie_frames)
        provenance["movie"] = {
            "path": str(movie_path),
            "sha256": sha256(movie_path),
            "recorded_frames": recorded_frames,
            "reused": True,
        }
    else:
        movie_path = output / "input.mmo"
        with McpSession(
            rom=rom,
            mesen=args.emulator.resolve(),
            cwd=ROOT,
            port=args.port,
            boot_wait=6.0,
            socket_timeout=300.0,
            stderr_log=output / "record-emulator.stderr.log",
        ) as m:
            m.pause()
            m.load_state(args.state.resolve())
            m.pause()
            record_start_frame = int(m.get_state().get("frameCount", 0))
            initial_shot = capture.take_screenshot(
                m, output / "record-initial.png"
            )
            record_response = m.record_movie(
                movie_path,
                author="supermn-snes framebuffer gate",
                description=(
                    f"{args.buttons} controller continuation from authenticated state"
                ),
                from_="CurrentState",
            )
            input_response = m.set_input(button_mask, args.frames)
            m.pause()
            record_end_frame = int(m.get_state().get("frameCount", 0))
            stop_response = m.stop_movie()
        capture.wait_for_file(movie_path)
        recorded_frames = record_end_frame - record_start_frame
        if recorded_frames <= 0:
            raise RuntimeError("controller movie made no emulated-frame progress")
        provenance["movie"] = {
            "path": str(movie_path),
            "sha256": sha256(movie_path),
            "record_start_frame": record_start_frame,
            "record_end_frame": record_end_frame,
            "recorded_frames": recorded_frames,
            "requested_frames": args.frames,
            "reused": False,
            "initial_screenshot": initial_shot,
            "record_response": record_response,
            "input_response": input_response,
            "stop_response": stop_response,
        }

    with McpSession(
        rom=rom,
        mesen=args.emulator.resolve(),
        cwd=ROOT,
        port=args.port,
        boot_wait=6.0,
        socket_timeout=300.0,
        stderr_log=output / "playback-emulator.stderr.log",
    ) as m:
        m.pause()
        play_response = m.play_movie(movie_path)
        m.pause()
        start_frame = int(m.get_state().get("frameCount", 0))
        initial = capture.snapshot(m)
        initial["relative_frame"] = 0
        initial["screenshot"] = capture.take_screenshot(
            m, output / "frame-000000.png"
        )
        initial["checkpoint"] = capture.save_checkpoint(
            m, output / "frame-000000.mss"
        )
        rows.append(initial)

        for relative in range(1, recorded_frames + 1):
            advance = advance_one(m)
            row = capture.snapshot(m)
            row["relative_frame"] = relative
            row["input_advance"] = advance
            row["screenshot"] = capture.take_screenshot(
                m, output / f"frame-{relative:06d}.png"
            )
            if relative % args.checkpoint_step == 0:
                row["checkpoint"] = capture.save_checkpoint(
                    m, output / f"frame-{relative:06d}.mss"
                )
            rows.append(row)
        movie_state_before_stop = m.movie_state()
        playback_stop_response = m.stop_movie()

    report = {
        "schema": 1,
        "provenance": provenance,
        "start_video_frame": start_frame,
        "end_video_frame": rows[-1]["frame"],
        "play_response": play_response,
        "movie_state_before_stop": movie_state_before_stop,
        "playback_stop_response": playback_stop_response,
        "captures": rows,
        "acceptance_gate": unknown_diagnostic_gate(
            "framebuffer_capture",
            "Capture success is evidence availability, not visual correctness.",
        ),
    }
    report_path = output / "results.json"
    report_path.write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(
        json.dumps(
            {
                "result": "captured",
                "frames": len(rows),
                "start_video_frame": start_frame,
                "end_video_frame": rows[-1]["frame"],
                "report": str(report_path),
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
