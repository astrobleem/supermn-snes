#!/usr/bin/env python3
"""Capture a deterministic held/thrown crate branch in pinned MAME 0.287."""

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
MAME_TRACE = ROOT / "tools/mame-trace"
BRANCH_LUA = MAME_TRACE / "branch_crate_carry.lua"
MAME_CFG = MAME_TRACE / "record_env/cfg/superman.cfg"
WORK_SIZE = 0x10000


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--state", type=Path, required=True)
    parser.add_argument("--base-tick", type=int, default=3213)
    parser.add_argument(
        "--held-mask", type=lambda value: int(value, 0), default=0xA0
    )
    parser.add_argument("--stop-tick", type=int, default=3300)
    parser.add_argument("--dump-stride", type=int, default=1)
    parser.add_argument("--throw-tick", type=int, default=0)
    parser.add_argument("--switch-tick", type=int, default=0)
    parser.add_argument("--switch-mask", type=lambda value: int(value, 0))
    parser.add_argument("--timeout", type=float, default=180.0)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    for label, path in (
        ("MAME state", args.state),
        ("branch Lua", BRANCH_LUA),
        ("MAME config", MAME_CFG),
        ("MAME ROM directory", MAME_TRACE / "roms"),
    ):
        if not path.exists():
            parser.error(f"missing {label}: {path}")
    if args.output.exists():
        parser.error(f"output already exists: {args.output}")
    if not 0 <= args.held_mask <= 0xFFFF:
        parser.error("--held-mask must fit in 16 bits")
    if not 0 < args.base_tick < args.stop_tick:
        parser.error("--stop-tick must exceed positive --base-tick")
    if (
        args.throw_tick
        and not args.base_tick < args.throw_tick <= args.stop_tick
    ):
        parser.error("--throw-tick must be zero or inside the branch")
    if args.switch_tick and not (
        args.base_tick < args.switch_tick <= args.stop_tick
    ):
        parser.error("--switch-tick must be zero or inside the branch")
    if (args.switch_tick == 0) != (args.switch_mask is None):
        parser.error(
            "--switch-tick and --switch-mask must be supplied together"
        )
    if args.switch_mask is not None and not 0 <= args.switch_mask <= 0xFFFF:
        parser.error("--switch-mask must fit in 16 bits")
    if args.dump_stride <= 0 or args.timeout <= 0:
        parser.error("--dump-stride and --timeout must be positive")

    mame = mame_identity()
    output = args.output.resolve()
    cfg = output / "cfg"
    nvram = output / "nvram"
    states = output / "states"
    state_game = states / "superman"
    for path in (output, cfg, nvram, states, state_game):
        path.mkdir()
    shutil.copy2(MAME_CFG, cfg / "superman.cfg")
    retained_state = state_game / "crate-branch-base.sta"
    shutil.copy2(args.state.resolve(), retained_state)
    source_state_hash = sha256(args.state.resolve())
    if sha256(retained_state) != source_state_hash:
        raise RuntimeError("retained MAME state copy failed authentication")

    command = [
        str(MAME),
        "superman",
        "-rompath",
        str(MAME_TRACE / "roms"),
        "-video",
        "none",
        "-sound",
        "none",
        "-nothrottle",
        "-skip_gameinfo",
        "-autoboot_script",
        str(BRANCH_LUA),
        "-autoboot_delay",
        "0",
        "-state",
        "crate-branch-base",
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
        CRATE_BRANCH_OUT=str(output),
        CRATE_BRANCH_BASE_TICK=str(args.base_tick),
        CRATE_BRANCH_MASK=str(args.held_mask),
        CRATE_BRANCH_STOP_TICK=str(args.stop_tick),
        CRATE_BRANCH_DUMP_STRIDE=str(args.dump_stride),
        CRATE_BRANCH_THROW_TICK=str(args.throw_tick),
        CRATE_BRANCH_SWITCH_TICK=str(args.switch_tick),
        CRATE_BRANCH_SWITCH_MASK=str(args.switch_mask or 0),
        CRATE_BRANCH_MAME_VERSION=mame["version"],
        CRATE_BRANCH_MAME_SHA256=mame["sha256"],
        CRATE_BRANCH_MAME_REVISION=mame["snap_revision"],
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

    events_path = output / "events.jsonl"
    rows: list[dict[str, Any]] = [
        json.loads(line)
        for line in events_path.read_text(encoding="utf-8").splitlines()
    ]
    provenance = [
        row for row in rows if row.get("event") == "provenance"
    ]
    summaries = [row for row in rows if row.get("event") == "summary"]
    expected_ticks = set(range(args.base_tick + 1, args.stop_tick + 1))
    event_ticks = {
        kind: {
            int(row["tick"])
            for row in rows
            if row.get("event") == kind
        }
        for kind in ("entry", "tick_start", "completion")
    }
    checks = {
        "single_provenance": len(provenance) == 1,
        "single_green_summary": (
            len(summaries) == 1
            and summaries[0].get("result") == "green"
        ),
        "pinned_runtime_identity": (
            len(provenance) == 1
            and provenance[0].get("mame_version") == mame["version"]
            and provenance[0].get("mame_sha256") == mame["sha256"]
            and provenance[0].get("mame_snap_revision")
            == mame["snap_revision"]
        ),
        "all_entry_ticks": event_ticks["entry"] == expected_ticks,
        "all_tick_start_ticks": (
            event_ticks["tick_start"] == expected_ticks
        ),
        "all_completion_ticks": (
            event_ticks["completion"] == expected_ticks
        ),
        "no_pending_irq_overrun": not any(
            row.get("event") == "pending_irq_overrun" for row in rows
        ),
    }
    dumped_work = sorted(output.glob("*.work.bin"))
    checks["all_work_dumps_sized"] = bool(dumped_work) and all(
        path.stat().st_size == WORK_SIZE for path in dumped_work
    )
    summary = {
        "result": "green" if all(checks.values()) else "red",
        "checks": checks,
        "mame": mame,
        "mame_rom_set": str(
            (MAME_TRACE / "roms/superman.zip").resolve()
        ),
        "mame_rom_set_sha256": sha256(
            MAME_TRACE / "roms/superman.zip"
        ),
        "command": command,
        "source_state": str(args.state.resolve()),
        "source_state_sha256": source_state_hash,
        "retained_state": str(retained_state),
        "retained_state_sha256": sha256(retained_state),
        "branch_lua": str(BRANCH_LUA),
        "branch_lua_sha256": sha256(BRANCH_LUA),
        "capture_tool": str(Path(__file__).resolve()),
        "capture_tool_sha256": sha256(Path(__file__).resolve()),
        "events": str(events_path),
        "events_sha256": sha256(events_path),
        "stdout": str(stdout_path),
        "stdout_sha256": sha256(stdout_path),
        "stderr": str(stderr_path),
        "stderr_sha256": sha256(stderr_path),
        "base_tick": args.base_tick,
        "stop_tick": args.stop_tick,
        "held_mask": args.held_mask,
        "throw_tick": args.throw_tick,
        "switch_tick": args.switch_tick,
        "switch_mask": args.switch_mask or 0,
        "work_dump_count": len(dumped_work),
        "work_manifest": {
            path.name: {
                "size": path.stat().st_size,
                "sha256": sha256(path),
            }
            for path in dumped_work
        },
    }
    summary_path = output / "summary.json"
    summary_path.write_text(
        json.dumps(summary, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(
        json.dumps(
            {
                "result": summary["result"],
                "checks": checks,
                "summary": str(summary_path),
            },
            sort_keys=True,
        )
    )
    return 0 if summary["result"] == "green" else 1


if __name__ == "__main__":
    raise SystemExit(main())
