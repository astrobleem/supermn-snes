#!/usr/bin/env python3
"""Capture original-arcade IRQ/scheduler/task ordering for movie ticks.

The retained MAME input movie is replayed from power-on without debugger
pauses.  The Lua oracle records lightweight program-read observations at the
IRQ, scheduler, and initialized coroutine resume PCs.  Because a 68000
prefetch tap may fire while the architectural PC still names the scheduler,
the raw current PC is retained for every event and no event class is guessed
away by this wrapper.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
from pathlib import Path

from mame_0287 import MAME, environment as mame_environment
from mame_0287 import identity as mame_identity


ROOT = Path(__file__).resolve().parents[1]
MAME_TRACE = ROOT / "tools" / "mame-trace"
MAME_MOVIE = ROOT / "inp" / "superman_play.inp"
MAME_CFG = MAME_TRACE / "record_env" / "cfg" / "superman.cfg"
CAPTURE_LUA = MAME_TRACE / "capture_scheduler_order.lua"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--tick-min", type=int, required=True)
    parser.add_argument("--tick-max", type=int, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--timeout", type=float, default=300.0)
    args = parser.parse_args()
    if not 0 <= args.tick_min <= args.tick_max <= 0xFFFF:
        parser.error("tick range must be within 0..65535")
    if args.output.exists():
        parser.error(f"output already exists: {args.output}")
    for label, path in (
        ("MAME", MAME),
        ("MAME movie", MAME_MOVIE),
        ("capture Lua", CAPTURE_LUA),
    ):
        if not path.is_file():
            parser.error(f"missing {label}: {path}")
    return args


def main() -> int:
    args = parse_args()
    mame_oracle = mame_identity()
    output = args.output.resolve()
    output.mkdir(parents=True)
    cfg = output / "cfg"
    nvram = output / "nvram"
    states = output / "states"
    for path in (cfg, nvram, states):
        path.mkdir()
    if MAME_CFG.is_file():
        shutil.copy2(MAME_CFG, cfg / MAME_CFG.name)

    version = mame_oracle["version"]
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
        "-autoboot_script",
        str(CAPTURE_LUA),
        "-autoboot_delay",
        "0",
        "-state_directory",
        str(states),
        "-nvram_directory",
        str(nvram),
        "-cfg_directory",
        str(cfg),
    ]
    environment = mame_environment(
        os.environ,
        SDL_VIDEODRIVER="dummy",
        SDL_AUDIODRIVER="dummy",
        SCHEDULER_ORDER_OUT=str(output),
        SCHEDULER_ORDER_TICK_MIN=str(args.tick_min),
        SCHEDULER_ORDER_TICK_MAX=str(args.tick_max),
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
    (output / "mame.stdout.log").write_text(
        completed.stdout, encoding="utf-8"
    )
    (output / "mame.stderr.log").write_text(
        completed.stderr, encoding="utf-8"
    )
    if completed.returncode != 0:
        raise RuntimeError(
            f"MAME exited {completed.returncode}; see "
            f"{output / 'mame.stderr.log'}"
        )

    log_path = output / "scheduler.jsonl"
    rows = [
        json.loads(line)
        for line in log_path.read_text(encoding="utf-8").splitlines()
    ]
    boundaries = [
        int(row["tick"]) for row in rows if row.get("event") == "boundary"
    ]
    expected = list(range(args.tick_min, args.tick_max + 1))
    if boundaries != expected:
        raise RuntimeError(
            f"boundary mismatch: expected {expected}, observed {boundaries}"
        )
    summary = {
        "scope": (
            "uninterrupted power-on MAME 0.287 retained-movie "
            "IRQ/scheduler/task-fetch trace; read-only taps; not FPS"
        ),
        "mame": str(MAME),
        "mame_version": version,
        "mame_sha256": mame_oracle["sha256"],
        "mame_snap_revision": mame_oracle["snap_revision"],
        "mame_gnome_content_revision": (
            mame_oracle["gnome_content_revision"]
        ),
        "movie": str(MAME_MOVIE.resolve()),
        "movie_sha256": sha256(MAME_MOVIE),
        "lua": str(CAPTURE_LUA.resolve()),
        "lua_sha256": sha256(CAPTURE_LUA),
        "tick_min": args.tick_min,
        "tick_max": args.tick_max,
        "boundaries": boundaries,
        "events": sum(
            row.get("event") in {"task_fetch", "seam_fetch"} for row in rows
        ),
        "log": str(log_path),
        "log_sha256": sha256(log_path),
    }
    summary_path = output / "summary.json"
    summary_path.write_text(
        json.dumps(summary, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(
        json.dumps(
            {
                "result": "green",
                "summary": str(summary_path),
                "events": summary["events"],
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
