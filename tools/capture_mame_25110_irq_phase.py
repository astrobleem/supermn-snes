#!/usr/bin/env python3
"""Capture the original arcade's cycle-stamped Stage-3 IRQ phase.

This replays the retained controller movie from a cold MAME power-on.  The
Lua script installs read taps and enables MAME's debugger trace only for the
requested tick window.  It neither pauses execution nor writes emulated game
state, so the resulting cycle/PC observations are an original-code oracle.

This is intentionally an oracle capture, not a SNES comparison, FPS result,
or full-playthrough claim.  Pair it with ``validate_stage3_irq_order.py`` for
the MAME/native-off/native-on state comparison.
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
CAPTURE_LUA = MAME_TRACE / "capture_25110_irq_phase.lua"


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
    parser.add_argument("--tick-min", type=int, default=14744)
    parser.add_argument("--tick-max", type=int, default=14747)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--timeout", type=float, default=300.0)
    args = parser.parse_args()
    if not 1 <= args.tick_min <= args.tick_max <= 0xFFFF:
        parser.error("tick range must be within 1..65535")
    if args.output.exists():
        parser.error(f"output already exists: {args.output}")
    if any(char.isspace() for char in str(args.output.resolve())):
        parser.error("--output cannot contain whitespace: MAME debugger trace paths are unquoted")
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
    trace_dir = output / "trace"
    cfg_dir = output / "cfg"
    nvram_dir = output / "nvram"
    state_dir = output / "states"
    for directory in (trace_dir, cfg_dir, nvram_dir, state_dir):
        directory.mkdir()
    shutil.copy2(MAME_CFG, cfg_dir / MAME_CFG.name)

    trace_path = trace_dir / "m68k.log"
    metadata_path = output / "meta.jsonl"
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
        COLLISION_IRQ_TRACE_OUT=str(trace_path),
        COLLISION_IRQ_META_OUT=str(metadata_path),
        COLLISION_IRQ_TICK_MIN=str(args.tick_min),
        COLLISION_IRQ_TICK_MAX=str(args.tick_max),
        COLLISION_IRQ_TRACE_CYCLES="1",
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
    if not metadata_path.is_file() or not trace_path.is_file():
        raise RuntimeError("MAME completed without the required metadata or debugger trace")

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
    trace = trace_path.read_text(encoding="utf-8")
    if "interrupted at" not in trace:
        raise RuntimeError("debugger trace has no recorded level-6 interruption")

    summary = {
        "scope": (
            "uninterrupted power-on original-code MAME 0.287 controller-movie "
            "Stage-3 IRQ phase capture; debugger trace plus read-only program taps; "
            "not a SNES comparison, FPS, or full-playthrough claim"
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
            "metadata": {"path": str(metadata_path), "sha256": sha256(metadata_path)},
            "debugger_trace": {"path": str(trace_path), "sha256": sha256(trace_path)},
            "stdout": {"path": str(stdout_path), "sha256": sha256(stdout_path)},
            "stderr": {"path": str(stderr_path), "sha256": sha256(stderr_path)},
        },
        "command": command,
    }
    summary_path = output / "summary.json"
    summary_path.write_text(
        json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(json.dumps({"result": "green", "summary": str(summary_path)}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
