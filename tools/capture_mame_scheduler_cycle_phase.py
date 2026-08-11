#!/usr/bin/env python3
"""Capture a cycle-stamped original-MAME scheduler/task timing ledger.

This replays the retained controller movie from a cold MAME power-on.  It is
an oracle input for migrating all accelerated scheduler and task boundaries to
one MC68000 clock.  The capture uses read-only program taps and neither pauses
nor mutates arcade state.  It is not a SNES comparison, rate result, or proof
that the virtual-clock repair is complete.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
from pathlib import Path
from typing import Any

from mame_0287 import MAME, environment as mame_environment
from mame_0287 import identity as mame_identity


ROOT = Path(__file__).resolve().parents[1]
MAME_TRACE = ROOT / "tools" / "mame-trace"
MAME_MOVIE = ROOT / "inp" / "superman_play.inp"
MAME_CFG = MAME_TRACE / "record_env" / "cfg" / "superman.cfg"
CAPTURE_LUA = MAME_TRACE / "capture_scheduler_cycle_phase.lua"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        try:
            row = json.loads(line)
        except json.JSONDecodeError as error:
            raise RuntimeError(f"{path}:{line_number}: invalid JSONL") from error
        if not isinstance(row, dict):
            raise RuntimeError(f"{path}:{line_number}: expected JSON object")
        rows.append(row)
    return rows


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--tick-min", type=int, default=14743)
    parser.add_argument("--tick-max", type=int, default=14747)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--timeout", type=float, default=600.0)
    args = parser.parse_args()
    if not 1 <= args.tick_min <= args.tick_max <= 0xFFFF:
        parser.error("tick range must be within 1..65535")
    if args.output.exists():
        parser.error(f"output already exists: {args.output}")
    if any(char.isspace() for char in str(args.output.resolve())):
        parser.error("--output cannot contain whitespace: MAME debugger paths are unquoted")
    for label, path in (
        ("MAME", MAME),
        ("MAME movie", MAME_MOVIE),
        ("MAME cfg", MAME_CFG),
        ("cycle capture Lua", CAPTURE_LUA),
    ):
        if not path.is_file():
            parser.error(f"missing {label}: {path}")
    return args


def main() -> int:
    args = parse_args()
    oracle = mame_identity()
    output = args.output.resolve()
    output.mkdir(parents=True)
    cfg_dir = output / "cfg"
    nvram_dir = output / "nvram"
    state_dir = output / "states"
    for directory in (cfg_dir, nvram_dir, state_dir):
        directory.mkdir()
    shutil.copy2(MAME_CFG, cfg_dir / MAME_CFG.name)

    metadata_path = output / "scheduler-cycles.jsonl"
    command = [
        str(MAME),
        "superman",
        "-rompath",
        str(MAME_TRACE / "roms"),
        "-input_directory",
        str(MAME_MOVIE.parent),
        "-playback",
        MAME_MOVIE.name,
        "-video",
        "none",
        "-sound",
        "none",
        "-nothrottle",
        "-skip_gameinfo",
        "-debug",
        "-debugger",
        "none",
        "-autoboot_script",
        str(CAPTURE_LUA),
        "-autoboot_delay",
        "0",
        "-state_directory",
        str(state_dir),
        "-nvram_directory",
        str(nvram_dir),
        "-cfg_directory",
        str(cfg_dir),
    ]
    environment = mame_environment(
        os.environ,
        SDL_VIDEODRIVER="dummy",
        SDL_AUDIODRIVER="dummy",
        SCHEDULER_CYCLE_OUT=str(output),
        SCHEDULER_CYCLE_TICK_MIN=str(args.tick_min),
        SCHEDULER_CYCLE_TICK_MAX=str(args.tick_max),
    )
    completed = subprocess.run(
        command,
        cwd=ROOT,
        env=environment,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=args.timeout,
        check=False,
    )
    stdout_path = output / "mame.stdout.log"
    stderr_path = output / "mame.stderr.log"
    stdout_path.write_text(completed.stdout, encoding="utf-8")
    stderr_path.write_text(completed.stderr, encoding="utf-8")
    if completed.returncode != 0:
        raise RuntimeError(
            f"MAME exited {completed.returncode}; see {stderr_path}"
        )
    if not metadata_path.is_file():
        raise RuntimeError("MAME completed without scheduler cycle metadata")

    rows = read_jsonl(metadata_path)
    if not rows or rows[-1].get("event") != "summary":
        raise RuntimeError("cycle metadata has no terminating summary")
    events = [row for row in rows if row.get("event") != "summary"]
    ordinals = [int(row.get("ordinal", -1)) for row in events]
    if ordinals != list(range(1, len(events) + 1)):
        raise RuntimeError("cycle metadata ordinal sequence is not contiguous")
    cycles = [int(row.get("cycles", -1)) for row in events]
    if any(value < 0 for value in cycles) or cycles != sorted(cycles):
        raise RuntimeError("cycle metadata is missing or non-monotonic")
    boundaries = [
        int(row["tick"])
        for row in events
        if row.get("event") == "boundary" and row.get("label") == "game_tick"
    ]
    expected_boundaries = list(range(args.tick_min, args.tick_max + 1))
    if boundaries != expected_boundaries:
        raise RuntimeError(
            f"boundary mismatch: expected {expected_boundaries}, observed {boundaries}"
        )
    labels = sorted({str(row.get("label")) for row in events if "label" in row})
    summary = {
        "scope": (
            "uninterrupted power-on original-code MAME 0.287 controller-movie "
            "cycle-stamped scheduler/task seam capture; debugger totalcycles "
            "plus read-only program taps; not a SNES comparison, FPS, repair, "
            "or full-playthrough claim"
        ),
        "runtime_architectural_mutations": [],
        "mame": oracle,
        "movie": {"path": str(MAME_MOVIE.resolve()), "sha256": sha256(MAME_MOVIE)},
        "lua": {"path": str(CAPTURE_LUA.resolve()), "sha256": sha256(CAPTURE_LUA)},
        "capture": {
            "tick_min": args.tick_min,
            "tick_max": args.tick_max,
            "boundaries": boundaries,
            "events": len(events),
            "labels": labels,
            "metadata": {"path": str(metadata_path), "sha256": sha256(metadata_path)},
            "stdout": {"path": str(stdout_path), "sha256": sha256(stdout_path)},
            "stderr": {"path": str(stderr_path), "sha256": sha256(stderr_path)},
        },
        "command": command,
    }
    summary_path = output / "summary.json"
    summary_path.write_text(
        json.dumps(summary, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(json.dumps({"result": "green", "summary": str(summary_path)}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
