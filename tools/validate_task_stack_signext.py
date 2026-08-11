#!/usr/bin/env python3
"""Regression for the task-0 stack-bank corruption near movie tick 7482.

The retained pre-failure checkpoint was produced by an uninterrupted
fresh-boot controller replay.  Two ticks later, the stale native $0046DE
``LINK A6,#-6`` body used to save task 0's stack in bank $F1.  The arcade and
interpreted paths both retain bank $F0.

This validator runs the identical checkpoint with production translation
enabled and disabled, watches the exact saved-SP bank-byte writes, retains
full work RAM and post-run states, and compares the task table and player
record with the MAME 0.287 tick-7482 work-RAM oracle.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
EVIDENCE = ROOT / "build/playtest-investigation-20260725"
DEFAULT_ROM = ROOT / "build/interp.sfc"
DEFAULT_STATE = (
    EVIDENCE
    / "task0-stack-pre7480-snes-on-current-v1"
    / "states/snes-tick-07480.mss"
)
DEFAULT_MAME_WORK = (
    EVIDENCE
    / "task0-stack-postfix-mame-reference-v1"
    / "mame-tick-07482.work.bin"
)
DEFAULT_NEXEN = Path(
    "/mnt/sdc1/Nexen-r5-20260712/"
    "bin/linux-x64/Release/linux-x64/publish/Nexen"
)
TASK_CONTEXT_START = 0x000A
TASK_CONTEXT_SIZE = 16 * 4
TASK0_BANK_BYTE = 0x000B
PLAYER_START = 0x12A2
PLAYER_SIZE = 0x80


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--rom", type=Path, default=DEFAULT_ROM)
    parser.add_argument("--state", type=Path, default=DEFAULT_STATE)
    parser.add_argument("--mame-work", type=Path, default=DEFAULT_MAME_WORK)
    parser.add_argument("--nexen", type=Path, default=DEFAULT_NEXEN)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--port", type=int, default=9500)
    parser.add_argument("--timeout", type=float, default=180.0)
    args = parser.parse_args()
    for label, path in (
        ("ROM", args.rom),
        ("checkpoint", args.state),
        ("MAME work RAM", args.mame_work),
        ("Nexen", args.nexen),
    ):
        if not path.is_file():
            parser.error(f"missing {label}: {path}")
    if args.output.exists():
        parser.error(f"output already exists: {args.output}")
    return args


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def be16(data: bytes, offset: int) -> int:
    return int.from_bytes(data[offset : offset + 2], "big")


def player_from_work(work: bytes) -> dict[str, Any]:
    raw = work[PLAYER_START : PLAYER_START + PLAYER_SIZE]

    def byte(offset: int) -> int:
        return raw[0x60 + offset]

    def word(offset: int) -> int:
        return be16(raw, 0x60 + offset)

    return {
        "health": word(-0x4E),
        "previous_input": byte(-0x43),
        "input": byte(-0x44),
        "action": byte(-0x23),
        "flags": byte(-0x24),
        "animation": word(-0x1A),
        "animation_step": word(-0x18),
        "x": word(-0x1E),
        "y": word(-0x22),
        "locals_sha256": hashlib.sha256(raw).hexdigest(),
    }


def run_arm(
    args: argparse.Namespace,
    label: str,
    xlat_gate: str,
    port: int,
) -> dict[str, Any]:
    output = args.output / label
    command = [
        sys.executable,
        str(ROOT / "tools/trace_player_native_tick.py"),
        "--rom",
        str(args.rom.resolve()),
        "--state",
        str(args.state.resolve()),
        "--output",
        str(output.resolve()),
        "--preserve-input",
        "--ticks",
        "2",
        "--watch-work-write",
        hex(TASK0_BANK_BYTE),
        "--xlat-gate",
        xlat_gate,
        "--choke-gate",
        "preserve",
        "--scheduler-gates",
        "preserve",
        "--loop-gate",
        "preserve",
        "--nexen",
        str(args.nexen.resolve()),
        "--port",
        str(port),
        "--timeout",
        str(args.timeout),
    ]
    completed = subprocess.run(
        command,
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    trace_path = output / "trace.json"
    trace = json.loads(trace_path.read_text(encoding="utf-8"))
    work_path = output / "end.work.bin"
    work = work_path.read_bytes()
    if len(work) != 0x10000:
        raise AssertionError(f"{label}: bad work-RAM size {len(work)}")
    writes = [
        int(row["value"])
        for row in trace["events"]
        if row.get("label") == "work_F0000B_write"
    ]
    if writes != [0xF0, 0xF0]:
        raise AssertionError(
            f"{label}: task-0 saved-SP bank writes {writes}, expected [240, 240]"
        )
    start, end = trace["boundaries"][0], trace["boundaries"][-1]
    if ((int(end["tick"]) - int(start["tick"])) & 0xFFFF) != 2:
        raise AssertionError(f"{label}: did not advance exactly two game ticks")
    if int(end["halt"]) != 0:
        raise AssertionError(f"{label}: interpreter halt {end['halt']}")
    return {
        "label": label,
        "xlat_gate": xlat_gate,
        "trace": str(trace_path),
        "trace_sha256": sha256(trace_path),
        "state": trace["final_state_response"]["path"],
        "state_sha256": trace["final_state_sha256"],
        "work": str(work_path),
        "work_sha256": sha256(work_path),
        "video_frames": int(end["frame"]) - int(start["frame"]),
        "tick_start": int(start["tick"]),
        "tick_end": int(end["tick"]),
        "writes": writes,
        "m68k_end": end["m68k"],
        "player": player_from_work(work),
        "task_context_hex": work[
            TASK_CONTEXT_START : TASK_CONTEXT_START + TASK_CONTEXT_SIZE
        ].hex(),
        "stdout": completed.stdout.strip(),
        "stderr": completed.stderr.strip(),
    }


def main() -> int:
    args = parse_args()
    args.output = args.output.resolve()
    args.output.mkdir(parents=True)
    mame_work = args.mame_work.read_bytes()
    if len(mame_work) != 0x10000:
        raise AssertionError(f"bad MAME work-RAM size {len(mame_work)}")
    mame_player = player_from_work(mame_work)
    mame_tasks = mame_work[
        TASK_CONTEXT_START : TASK_CONTEXT_START + TASK_CONTEXT_SIZE
    ]

    arms = [
        run_arm(args, "native-on-production", "preserve", args.port),
        run_arm(args, "native-xlat-off", "off", args.port + 1),
    ]
    for arm in arms:
        if arm["player"] != mame_player:
            raise AssertionError(
                f"{arm['label']}: player mismatch\n"
                f"MAME={mame_player}\nSNES={arm['player']}"
            )
        if bytes.fromhex(arm["task_context_hex"]) != mame_tasks:
            raise AssertionError(
                f"{arm['label']}: task-context table differs from MAME"
            )

    summary = {
        "scope": (
            "retained pre-failure fresh-replay checkpoint; identical two-tick "
            "production-on and translation-off Nexen runs; exact MAME 0.287 "
            "tick-7482 player/task oracle; focused checkpoint regression, "
            "not fresh-boot proof"
        ),
        "result": "green",
        "classification": "native_hle_stale_generated_signed_displacement",
        "rom": str(args.rom.resolve()),
        "rom_sha256": sha256(args.rom),
        "state": str(args.state.resolve()),
        "state_sha256": sha256(args.state),
        "mame_work": str(args.mame_work.resolve()),
        "mame_work_sha256": sha256(args.mame_work),
        "mame_player": mame_player,
        "mame_task_context_hex": mame_tasks.hex(),
        "nexen": str(args.nexen.resolve()),
        "nexen_sha256": sha256(args.nexen),
        "arms": arms,
    }
    summary_path = args.output / "summary.json"
    summary_path.write_text(
        json.dumps(summary, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(
        json.dumps(
            {
                "result": summary["result"],
                "classification": summary["classification"],
                "summary": str(summary_path),
                "arms": [
                    {
                        "label": arm["label"],
                        "video_frames": arm["video_frames"],
                        "writes": arm["writes"],
                    }
                    for arm in arms
                ],
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
