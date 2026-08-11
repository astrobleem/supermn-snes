#!/usr/bin/env python3
"""Find a credited-prompt tick/RNG target from a same-ROM paused state.

This is a bounded bootstrap-calibration probe. It loads an explicitly named
state, applies no input or debugger memory mutation, and advances one neutral
video frame at a time until the requested instrumentation tick is passed.
It is not gameplay, timing acceptance, or checkpoint-resumability evidence.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
os.environ["DOTNET_ROOT"] = "/home/chad/.dotnet10"
sys.path.insert(0, str(ROOT / "tools"))

import validate_fresh_one_credit_prompt as fresh  # noqa: E402


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def sample(m: fresh.McpSession, delta_frames: int) -> dict[str, int]:
    credits = bytes(m.read_memory("snesMemory", 0x401C62, 2))
    rng = bytes(m.read_memory("snesMemory", 0x40170E, 2))
    tick = bytes(
        m.read_memory("Sa1Memory", fresh.campaign.TICK_IRAM, 2)
    )
    request_ack = bytes(m.read_memory("snesMemory", 0x003300, 4))
    return {
        "delta_frames": delta_frames,
        "video_frame": int(m.get_state().get("frameCount", 0)),
        "credits": int.from_bytes(credits, "big"),
        "tick_0760": int.from_bytes(tick, "little"),
        "rng_f0170e": int.from_bytes(rng, "big"),
        "frame_request": int.from_bytes(request_ack[0:2], "little"),
        "frame_ack": int.from_bytes(request_ack[2:4], "little"),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--rom", type=Path, required=True)
    parser.add_argument("--state", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--nexen", type=Path, default=fresh.DEFAULT_NEXEN)
    parser.add_argument("--port", type=int, default=9364)
    parser.add_argument("--max-frames", type=int, default=400)
    parser.add_argument("--target-credits", type=int, default=8)
    parser.add_argument("--target-tick", type=int, default=168)
    parser.add_argument("--target-rng", type=lambda value: int(value, 0), default=2716)
    args = parser.parse_args()
    for name, path in (("ROM", args.rom), ("state", args.state), ("Nexen", args.nexen)):
        if not path.is_file():
            parser.error(f"missing {name}: {path}")
    if args.output.exists():
        parser.error(f"output exists: {args.output}")
    if args.max_frames < 1:
        parser.error("--max-frames must be positive")
    args.output.mkdir(parents=True)

    samples: list[dict[str, int]] = []
    result = "target_not_reached"
    with fresh.McpSession(
        rom=args.rom.resolve(),
        mesen=args.nexen.resolve(),
        cwd=ROOT,
        port=args.port,
        boot_wait=6.0,
        socket_timeout=300.0,
        stderr_log=args.output / "emulator.stderr.log",
    ) as m:
        m.pause()
        m.load_state(args.state.resolve())
        m.pause()
        previous: tuple[int, int, int, int, int] | None = None
        for delta in range(args.max_frames + 1):
            row = sample(m, delta)
            key = (
                row["credits"],
                row["tick_0760"],
                row["rng_f0170e"],
                row["frame_request"],
                row["frame_ack"],
            )
            if key != previous:
                samples.append(row)
                previous = key
            if (
                row["credits"] == args.target_credits
                and row["tick_0760"] == args.target_tick
                and row["rng_f0170e"] == args.target_rng
            ):
                result = "target_reached"
                break
            if row["tick_0760"] > args.target_tick:
                result = "target_tick_passed"
                break
            if delta == args.max_frames:
                break
            fresh.campaign.run_exact_frames(m, 0, 1)

    target_row = next(
        (
            row
            for row in samples
            if row["credits"] == args.target_credits
            and row["tick_0760"] == args.target_tick
            and row["rng_f0170e"] == args.target_rng
        ),
        None,
    )
    tick_rows = [row for row in samples if row["tick_0760"] == args.target_tick]
    report = {
        "scope": "same-ROM credited-state neutral-frame calibration only",
        "rom": {"path": str(args.rom.resolve()), "sha256": sha256(args.rom)},
        "state": {"path": str(args.state.resolve()), "sha256": sha256(args.state)},
        "target": {
            "credits": args.target_credits,
            "tick_0760": args.target_tick,
            "rng_f0170e": args.target_rng,
        },
        "result": result,
        "target_row": target_row,
        "target_tick_rows": tick_rows,
        "first": samples[0],
        "last": samples[-1],
        "samples": samples,
    }
    summary = args.output / "summary.json"
    summary.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    print(
        json.dumps(
            {
                "result": result,
                "target_row": target_row,
                "target_tick_rows": tick_rows,
                "summary": str(summary),
            },
            sort_keys=True,
        )
    )
    return 0 if result == "target_reached" else 1


if __name__ == "__main__":
    raise SystemExit(main())
