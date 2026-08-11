#!/usr/bin/env python3
"""Retain organic MAME entry fixtures for the Stage-3 hot state handlers.

The supported World-set longplay reaches the vertically scrolling Stage 3.
For each selected handler this tool optionally fast-forwards the untouched MAME
playback, captures several consecutive organic entry states, and retains:

* every 68000 D/A register, SP/USP, SR/CCR/X, and the stacked return;
* the complete mapped 16 KiB $F0 work-RAM window;
* a MAME pre-entry save state for deterministic replay.

These are inputs to ``validate_stage3_hot_handlers.py``.  They are oracle
fixtures, not end-to-end performance evidence.

MAME 0.287 can keep executing an already decoded opcode page without observing
a tap installed after the fast-forward.  Use ``--start-frame 0`` when capturing
a target that may execute before the desired Stage-3 window; the retained movie
can still run unattended until the target is reached.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import sys
import time
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MAME_TRACE = ROOT / "tools" / "mame-trace"
MAME_MCP = Path("/home/chad/mame-mcp")
PLAYBACK_DIR = ROOT / "inp"
DEFAULT_PLAYBACK = "superman_play.inp"
MAPPED_WORK_SIZE = 0x4000
TARGETS = (0x027952, 0x0279D2, 0x02F3BA)
EXPECTED_RETURNS = {
    0x027952: {0x0278F2, 0x0278FC},
    0x0279D2: {0x0278F2, 0x0278FC},
    0x02F3BA: {0x02E44C},
}
REG_NAMES = [f"D{index}" for index in range(8)] + [
    f"A{index}" for index in range(7)
]

sys.path.insert(0, str(MAME_MCP))
from mame_mcp.session import MameSession  # noqa: E402
from mame_0287 import MAME, environment as mame_environment, identity as mame_identity  # noqa: E402


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def be32(data: bytes, offset: int) -> int:
    return int.from_bytes(data[offset : offset + 4], "big")


def copy_oracle_config(output: Path) -> tuple[Path, Path, Path]:
    cfg = output / "mame-cfg"
    nvram = output / "mame-nvram"
    states = output / "mame-states"
    cfg.mkdir()
    nvram.mkdir()
    states.mkdir()
    source_cfg = MAME_TRACE / "record_env" / "cfg" / "superman.cfg"
    if source_cfg.is_file():
        shutil.copy2(source_cfg, cfg / source_cfg.name)
    return cfg, nvram, states


def launch_session(
    output: Path,
    playback: str,
    cfg: Path,
    nvram: Path,
    states: Path,
) -> MameSession:
    # The generic Snap launcher follows its mutable ``current`` revision.
    # Keep retained oracle fixtures on the project-pinned 0.287 payload and
    # give its child process the matching library search path.
    os.environ.update(mame_environment())
    session = MameSession(
        mame=str(MAME),
        system="superman",
        rompath=str(MAME_TRACE / "roms"),
        workdir=str(MAME_TRACE),
        state_directory=str(states),
        extra_args=[
            "-playback",
            playback,
            "-input_directory",
            str(PLAYBACK_DIR),
            "-cfg_directory",
            str(cfg),
            "-nvram_directory",
            str(nvram),
            "-video",
            "none",
            "-sound",
            "none",
            "-nothrottle",
        ],
    )
    session.launch(boot_wait=25)
    return session


def fast_forward(session: MameSession, start_frame: int) -> int:
    frame = 0
    while frame < start_frame - 10:
        step = min(800, start_frame - 10 - frame)
        captured = session.cmd(
            "capture_game_tick",
            addr=0xF00000,
            len=4,
            nth=step,
            maxFrames=step + 600,
            timeout=180,
        )
        if not captured.get("registers"):
            raise RuntimeError(
                f"playback ended while fast-forwarding at frame {frame}: "
                f"{captured!r}"
            )
        frame = int(captured["frame"])
    return frame


def capture_target(
    session: MameSession,
    target: int,
    count: int,
    output: Path,
    max_frames: int,
) -> list[dict]:
    events: list[dict] = []
    for ordinal in range(count):
        captured = session.cmd(
            "capture_at_pc",
            pc=target,
            addr=0xF00000,
            len=MAPPED_WORK_SIZE,
            nth=1,
            maxFrames=max_frames,
            timeout=300,
        )
        if not captured.get("registers"):
            raise RuntimeError(
                f"MAME did not reach ${target:06X} fixture {ordinal}: "
                f"{captured!r}"
            )
        registers = captured["registers"]
        work = bytes.fromhex(captured["hex"])
        sp = int(registers["SP"]) & 0xFFFFFF
        if (sp >> 16) != 0xF0 or (sp & 0xFFFF) > MAPPED_WORK_SIZE - 4:
            raise RuntimeError(
                f"${target:06X} fixture {ordinal} has unmapped SP ${sp:06X}"
            )
        return_pc = be32(work, sp & 0xFFFF) & 0xFFFFFF
        if (
            target in EXPECTED_RETURNS
            and return_pc not in EXPECTED_RETURNS[target]
        ):
            raise RuntimeError(
                f"${target:06X} fixture {ordinal} return ${return_pc:06X} "
                f"is not one of "
                f"{sorted(f'${value:06X}' for value in EXPECTED_RETURNS[target])}"
            )
        stem = f"case-{target:06x}-{ordinal:02d}"
        work_path = output / f"{stem}.work.bin"
        state_name = stem
        work_path.write_bytes(work)
        state_response = session.save_state(state_name)
        event = {
            "event": "fixture",
            "name": stem,
            "target": f"{target:06X}",
            "ordinal": ordinal,
            "frame": int(captured.get("frame", 0)),
            "return_pc": f"{return_pc:06X}",
            "regs": {
                name: int(registers[name]) & 0xFFFFFFFF for name in REG_NAMES
            }
            | {"A7": sp},
            "usp": int(registers.get("USP", sp)) & 0xFFFFFFFF,
            "sr": int(registers.get("SR", 0)) & 0xFFFF,
            "work_file": work_path.name,
            "work_sha256": hashlib.sha256(work).hexdigest(),
            "mame_state_name": state_name,
            "mame_state_response": state_response,
        }
        (output / f"{stem}.json").write_text(
            json.dumps(event, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        events.append(event)
        print(json.dumps(event, sort_keys=True), flush=True)
    return events


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument(
        "--start-frame",
        type=int,
        default=40000,
        help=(
            "Movie frame to approach before installing the capture tap. Use "
            "0 for targets that may already have executed; MAME 0.287 can "
            "otherwise keep an already decoded opcode page cached."
        ),
    )
    parser.add_argument("--count", type=int, default=6)
    parser.add_argument(
        "--capture-max-frames",
        type=int,
        default=12000,
        help="Maximum video frames to wait for each retained target hit.",
    )
    parser.add_argument("--playback", default=DEFAULT_PLAYBACK)
    parser.add_argument(
        "--targets",
        help=(
            "Comma-separated MC68000 PCs (default: 027952,0279D2,02F3BA). "
            "Known default targets retain strict caller-return checks; custom "
            "targets retain their observed mapped return without assuming it."
        ),
    )
    args = parser.parse_args()
    if (
        args.start_frame < 0
        or args.count <= 0
        or args.capture_max_frames <= 0
    ):
        parser.error(
            "--start-frame must be non-negative; --count and "
            "--capture-max-frames must be positive"
        )
    playback_path = PLAYBACK_DIR / args.playback
    if not playback_path.is_file():
        parser.error(f"missing playback: {playback_path}")
    output = args.output.resolve()
    targets = (
        tuple(int(value.strip(), 16) for value in args.targets.split(","))
        if args.targets
        else TARGETS
    )
    if not targets or any(not 0 <= target <= 0xFFFFFF for target in targets):
        parser.error("--targets must contain one or more 24-bit hexadecimal PCs")
    output.mkdir(parents=True, exist_ok=False)
    cfg, nvram, states = copy_oracle_config(output)
    provenance = {
        "event": "provenance",
        "scope": (
            "organic MAME 0.287 Stage-3 handler entry fixtures; exact "
            "D/A/SR/USP, mapped 16 KiB work RAM, and pre-entry MAME states; "
            "not fps"
        ),
        "mame": mame_identity(),
        "playback": str(playback_path.resolve()),
        "playback_sha256": sha256(playback_path),
        "program_image_sha256": sha256(ROOT / "data/superman_m68k.bin"),
        "start_frame": args.start_frame,
        "count_per_target": args.count,
        "targets": [f"{target:06X}" for target in targets],
        "time": time.time(),
    }
    print(json.dumps(provenance, sort_keys=True), flush=True)
    events: list[dict] = [provenance]
    for target in targets:
        session = launch_session(
            output, args.playback, cfg, nvram, states
        )
        try:
            reached = fast_forward(session, args.start_frame)
            event = {
                "event": "fast_forward",
                "target": f"{target:06X}",
                "reached_frame": reached,
            }
            events.append(event)
            print(json.dumps(event, sort_keys=True), flush=True)
            events.extend(
                capture_target(
                    session,
                    target,
                    args.count,
                    output,
                    args.capture_max_frames,
                )
            )
        finally:
            session.stop()
    summary = {
        "event": "summary",
        "fixtures": sum(event.get("event") == "fixture" for event in events),
        "targets": len(targets),
        "result": "green",
        "time": time.time(),
    }
    events.append(summary)
    print(json.dumps(summary, sort_keys=True), flush=True)
    (output / "capture.jsonl").write_text(
        "".join(json.dumps(event, sort_keys=True) + "\n" for event in events),
        encoding="utf-8",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
