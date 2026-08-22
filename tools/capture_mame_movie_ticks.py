#!/usr/bin/env python3
"""Capture original-arcade work RAM at selected controller-movie ticks.

This is the MAME counterpart to ``capture_snes_movie_ticks.py``.  It runs the
retained input movie without debugger pauses, asks the reusable Lua tap for
exact tick boundaries, and authenticates every 64 KiB dump and reference
player state.  The output is a focused oracle, not a playthrough claim.
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
EVIDENCE = ROOT / "build" / "playtest-investigation-20260725"
DEFAULT_TIMELINE = (
    EVIDENCE
    / "full-playback-completion-timeline-v2"
    / "timeline.jsonl"
)
MAME_TRACE = ROOT / "tools" / "mame-trace"
MAME_MOVIE = ROOT / "inp" / "superman_play.inp"
MAME_CFG = MAME_TRACE / "record_env" / "cfg" / "superman.cfg"
CAPTURE_LUA = MAME_TRACE / "capture_organic_player_damage.lua"
WORK_SIZE = 0x10000


def parse_ticks(value: str) -> list[int]:
    ticks = sorted({int(item, 0) for item in value.split(",") if item.strip()})
    if not ticks or any(tick <= 0 or tick > 0xFFFF for tick in ticks):
        raise argparse.ArgumentTypeError(
            "ticks must be comma-separated values in 1..65535"
        )
    return ticks


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--ticks", type=parse_ticks, required=True)
    parser.add_argument(
        "--save-tick",
        type=int,
        default=0,
        help=(
            "also retain a MAME save state at this requested tick; zero "
            "disables save-state capture"
        ),
    )
    parser.add_argument("--timeline", type=Path, default=DEFAULT_TIMELINE)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--timeout", type=float, default=300.0)
    parser.add_argument(
        "--snapshots",
        action="store_true",
        help="retain a MAME PNG at every requested tick",
    )
    parser.add_argument(
        "--video-shadows",
        action="store_true",
        help="retain raw $B00000/$D00000/$E00000 video shadow spans at every tick",
    )
    parser.add_argument(
        "--boundary",
        choices=("completion_0818", "tick_start"),
        default="completion_0818",
        help=(
            "capture at the paired $0818 completion (default) or the real "
            "$003A92 tick-start boundary"
        ),
    )
    parser.add_argument(
        "--watch-pc",
        type=lambda value: int(value, 0),
        help=(
            "also retain register/work snapshots when the original CPU "
            "fetches this 24-bit program address"
        ),
    )
    parser.add_argument(
        "--watch-address",
        type=lambda value: int(value, 0),
        help=(
            "also retain register/work snapshots when the original CPU "
            "writes the aligned word containing this 24-bit address"
        ),
    )
    parser.add_argument("--watch-tick-min", type=int, default=0)
    parser.add_argument("--watch-tick-max", type=int, default=0xFFFF)
    parser.add_argument("--watch-max-hits", type=int, default=64)
    args = parser.parse_args()
    for label, path in (
        ("MAME", MAME),
        ("MAME movie", MAME_MOVIE),
        ("capture Lua", CAPTURE_LUA),
        ("timeline", args.timeline),
    ):
        if not path.is_file():
            parser.error(f"missing {label}: {path}")
    if args.output.exists():
        parser.error(f"output already exists: {args.output}")
    if args.timeout <= 0:
        parser.error("--timeout must be positive")
    if args.save_tick and args.save_tick not in args.ticks:
        parser.error("--save-tick must be zero or one of --ticks")
    if args.watch_pc is not None and not 0 <= args.watch_pc <= 0xFFFFFF:
        parser.error("--watch-pc must be in 0..0xffffff")
    if (
        args.watch_address is not None
        and not 0 <= args.watch_address <= 0xFFFFFF
    ):
        parser.error("--watch-address must be in 0..0xffffff")
    if not 0 <= args.watch_tick_min <= args.watch_tick_max <= 0xFFFF:
        parser.error("watch tick range must be within 0..65535")
    if not 1 <= args.watch_max_hits <= 4096:
        parser.error("--watch-max-hits must be in 1..4096")
    return args


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def be16(data: bytes, offset: int) -> int:
    return int.from_bytes(data[offset : offset + 2], "big")


def timeline_rows(
    path: Path, requested: set[int], boundary: str
) -> dict[int, dict[str, Any]]:
    rows: dict[int, dict[str, Any]] = {}
    expected_event = "tick" if boundary == "completion_0818" else "tick_start"
    with path.open(encoding="utf-8") as stream:
        for line in stream:
            row = json.loads(line)
            tick = int(row.get("tick", -1))
            if row.get("event") == expected_event and tick in requested:
                if boundary == "completion_0818":
                    valid = (
                        row.get("boundary_kind") == "completion_0818"
                        and int(row.get("tick_start_ordinal", -1)) == tick
                        and int(row.get("completion_ordinal", -1)) == tick
                    )
                else:
                    valid = row.get("boundary_kind") in (None, "tick_start_3a92")
                if not valid:
                    raise RuntimeError(
                        f"timeline tick {tick} is not a valid {boundary} "
                        "boundary"
                    )
                rows[tick] = row
    missing = sorted(requested - set(rows))
    if missing:
        raise RuntimeError(f"timeline lacks requested ticks: {missing}")
    return rows


def main() -> int:
    args = parse_args()
    mame = mame_identity()
    output = args.output.resolve()
    output.mkdir(parents=True)
    cfg = output / "cfg"
    nvram = output / "nvram"
    states = output / "states"
    snapshots = output / "snapshots"
    for path in (cfg, nvram, states, snapshots):
        path.mkdir()
    if MAME_CFG.is_file():
        shutil.copy2(MAME_CFG, cfg / MAME_CFG.name)

    requested = set(args.ticks)
    references = timeline_rows(args.timeline, requested, args.boundary)
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
        "-snapshot_directory",
        str(snapshots),
    ]
    environment = mame_environment(
        os.environ,
        SDL_VIDEODRIVER="dummy",
        SDL_AUDIODRIVER="dummy",
        ORGANIC_DAMAGE_OUT=str(output),
        ORGANIC_DAMAGE_TICKS=",".join(str(tick) for tick in args.ticks),
        ORGANIC_DAMAGE_SNAPSHOT_TICKS=(
            ",".join(str(tick) for tick in args.ticks)
            if args.snapshots
            else ""
        ),
        ORGANIC_DAMAGE_VIDEO_SHADOWS="1" if args.video_shadows else "0",
        ORGANIC_DAMAGE_BOUNDARY=args.boundary,
        ORGANIC_DAMAGE_SAVE_TICK=str(args.save_tick),
        ORGANIC_DAMAGE_HEALTH_MIN="0",
        ORGANIC_DAMAGE_HEALTH_MAX="0",
        ORGANIC_DAMAGE_WATCH_PC=(
            str(args.watch_pc) if args.watch_pc is not None else ""
        ),
        ORGANIC_DAMAGE_WATCH_ADDRESS=(
            str(args.watch_address)
            if args.watch_address is not None
            else ""
        ),
        ORGANIC_DAMAGE_WATCH_TICK_MIN=str(args.watch_tick_min),
        ORGANIC_DAMAGE_WATCH_TICK_MAX=str(args.watch_tick_max),
        ORGANIC_DAMAGE_WATCH_PC_MAX_HITS=str(args.watch_max_hits),
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

    capture_log = output / "capture.jsonl"
    rows = [
        json.loads(line)
        for line in capture_log.read_text(encoding="utf-8").splitlines()
    ]
    boundaries = {
        int(row["tick"]): row
        for row in rows
        if row.get("event") == "boundary"
    }
    if set(boundaries) != requested:
        raise RuntimeError(
            f"captured ticks {sorted(boundaries)}, "
            f"expected {sorted(requested)}"
        )

    snapshot_paths: dict[int, Path] = {}
    if args.snapshots:
        generated = sorted(
            (snapshots / "superman").glob("*.png"),
            key=lambda path: int(path.stem),
        )
        if len(generated) != len(args.ticks):
            raise RuntimeError(
                f"MAME retained {len(generated)} snapshots, "
                f"expected {len(args.ticks)}"
            )
        snapshot_paths = dict(zip(args.ticks, generated, strict=True))

    captures: list[dict[str, Any]] = []
    for tick in args.ticks:
        path = output / f"mame-tick-{tick:05d}.work.bin"
        work = path.read_bytes()
        if len(work) != WORK_SIZE:
            raise RuntimeError(f"{path}: expected {WORK_SIZE} bytes")
        observed = {
            "health": be16(work, 0x12B4),
            "previous_input": work[0x12BF],
            "input": work[0x12BE],
            "flags": work[0x12DE],
            "player_x": be16(work, 0x12E4),
            "player_y": be16(work, 0x12E0),
            "action": work[0x12DF],
            "animation": be16(work, 0x12E8),
            "animation_step": be16(work, 0x12EA),
        }
        reference = {
            name: int(references[tick][name])
            for name in ("health", "player_x", "player_y", "action")
        }
        observed_reference = {
            name: observed[name]
            for name in ("health", "player_x", "player_y", "action")
        }
        if observed_reference != reference:
            raise RuntimeError(
                f"tick {tick}: player {observed_reference}, expected {reference}"
            )
        boundary = boundaries[tick]
        if args.boundary == "completion_0818":
            valid_boundary = (
                boundary.get("boundary_kind") == "completion_0818"
                and int(boundary.get("tick_start_ordinal", -1)) == tick
                and int(boundary.get("completion_ordinal", -1)) == tick
            )
        else:
            # The reusable Lua tap names its real $003A92 boundary
            # ``tick_start``.  Older retained timeline exports omit the field
            # or spell the same seam ``tick_start_3a92``.
            valid_boundary = boundary.get("boundary_kind") in (
                "tick_start",
                "tick_start_3a92",
            )
        if not valid_boundary:
            raise RuntimeError(
                f"tick {tick}: capture was not made at {args.boundary}"
            )
        capture = {
                "tick": tick,
                "frame": int(boundary["frame"]),
                "path": str(path),
                "sha256": sha256(path),
                "size": len(work),
                "player": observed,
            }
        if tick in snapshot_paths:
            snapshot = snapshot_paths[tick]
            capture["snapshot"] = {
                "path": str(snapshot),
                "sha256": sha256(snapshot),
                "size": snapshot.stat().st_size,
            }
        if args.video_shadows:
            capture["video_shadows"] = {}
            for label, size in (
                ("b0", 0x1000),
                ("d0", 0x1000),
                ("e0", 0x4000),
            ):
                shadow = output / f"mame-tick-{tick:05d}.{label}.bin"
                if not shadow.is_file() or shadow.stat().st_size != size:
                    raise RuntimeError(
                        f"tick {tick}: invalid {label} shadow {shadow}"
                    )
                capture["video_shadows"][label] = {
                    "path": str(shadow),
                    "sha256": sha256(shadow),
                    "size": size,
                }
        captures.append(capture)

    saved_state_path = None
    if args.save_tick:
        state_prefix = (
            "organic-player-damage-completion-tick"
            if args.boundary == "completion_0818"
            else "organic-player-damage-pre-tick"
        )
        saved_state_path = (
            states
            / "superman"
            / f"{state_prefix}-{args.save_tick:05d}.sta"
        )
        if not saved_state_path.is_file():
            raise RuntimeError(
                "MAME did not retain requested state: "
                f"{saved_state_path}"
            )

    summary = {
        "scope": (
            "uninterrupted MAME 0.287 original-code controller-movie work-RAM "
            f"capture at {args.boundary} game ticks; "
            "focused oracle, not a playthrough"
        ),
        "result": "green",
        "mame": mame["path"],
        "mame_sha256": mame["sha256"],
        "mame_version": mame["version"],
        "mame_snap_revision": mame["snap_revision"],
        "mame_gnome_content_revision": mame[
            "gnome_content_revision"
        ],
        "mame_rom_set": str(MAME_TRACE / "roms/superman.zip"),
        "mame_rom_set_sha256": sha256(
            MAME_TRACE / "roms/superman.zip"
        ),
        "movie": str(MAME_MOVIE),
        "movie_sha256": sha256(MAME_MOVIE),
        "capture_lua": str(CAPTURE_LUA),
        "capture_lua_sha256": sha256(CAPTURE_LUA),
        "capture_tool": str(Path(__file__).resolve()),
        "capture_tool_sha256": sha256(Path(__file__).resolve()),
        "timeline": str(args.timeline.resolve()),
        "timeline_sha256": sha256(args.timeline),
        "ticks": args.ticks,
        "snapshots": args.snapshots,
        "video_shadows": args.video_shadows,
        "save_tick": args.save_tick,
        "saved_state": (
            {
                "path": str(saved_state_path),
                "sha256": sha256(saved_state_path),
            }
            if args.save_tick
            else None
        ),
        "program_watch": (
            {
                "pc": f"{args.watch_pc:06X}",
                "tick_min": args.watch_tick_min,
                "tick_max": args.watch_tick_max,
                "max_hits": args.watch_max_hits,
                "hits": sum(
                    row.get("event") == "generic_pc" for row in rows
                ),
            }
            if args.watch_pc is not None
            else None
        ),
        "memory_watch": (
            {
                "address": f"{args.watch_address:06X}",
                "tick_min": args.watch_tick_min,
                "tick_max": args.watch_tick_max,
                "hits": sum(
                    row.get("event") == "generic_write" for row in rows
                ),
            }
            if args.watch_address is not None
            else None
        ),
        "captures": captures,
        "capture_log": str(capture_log),
        "capture_log_sha256": sha256(capture_log),
        "stdout": str(stdout_path),
        "stdout_sha256": sha256(stdout_path),
        "stderr": str(stderr_path),
        "stderr_sha256": sha256(stderr_path),
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
                "ticks": args.ticks,
                "summary": str(summary_path),
            },
            sort_keys=True,
        ),
        flush=True,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
