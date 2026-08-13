#!/usr/bin/env python3
"""Freeze the game producer and drain one legacy-Mesen renderer checkpoint.

This is a checkpoint diagnostic, not production or gameplay evidence.  It parks
the paused SA-1 at its exact 65816 PC, leaves the 5A22/NMI consumer active, then
advances one video frame at a time and saves the first state where renderer
ownership, queues, and all three image generations are coherent and idle.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
sys.path.insert(0, "/home/chad/Mesen2/python")

import capture_mesen211_transitions as capture  # noqa: E402
import mesen_mcp.session as _session  # noqa: E402

_session.validate_mesen_build = lambda *_args, **_kwargs: None
from mesen_mcp import McpSession  # noqa: E402


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--rom", type=Path, required=True)
    parser.add_argument("--state", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--emulator", type=Path, required=True)
    parser.add_argument("--port", type=int, default=43250)
    parser.add_argument("--max-frames", type=int, default=3000)
    parser.add_argument("--checkpoint-step", type=int, default=100)
    return parser.parse_args()


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def coherent_idle(row: dict[str, object]) -> bool:
    generations = (
        row["snapshot_generation"],
        row["direct_generation"],
        row["rendered_generation"],
    )
    return (
        row["renderer_busy"] == 0
        and row["render_queue_primary"] == 0
        and row["render_queue_secondary"] == 0
        and len(set(generations)) == 1
    )


def main() -> int:
    args = parse_args()
    if args.max_frames <= 0 or args.checkpoint_step <= 0:
        raise SystemExit("frame counts must be positive")
    for path in (args.rom, args.state, args.emulator):
        if not path.is_file():
            raise FileNotFoundError(path)
    output = args.output.resolve()
    if output.exists():
        raise SystemExit(f"refusing existing output: {output}")
    output.mkdir(parents=True)
    capture.configure_dotnet8()

    rows: list[dict[str, object]] = []
    interventions: list[dict[str, object]] = []
    idle_row: dict[str, object] | None = None
    with McpSession(
        rom=args.rom.resolve(),
        mesen=args.emulator.resolve(),
        cwd=ROOT,
        port=args.port,
        boot_wait=6.0,
        socket_timeout=300.0,
        stderr_log=output / "emulator.stderr.log",
    ) as m:
        m.pause()
        m.load_state(args.state.resolve())
        m.pause()
        start = capture.snapshot(m)
        start["relative_frame"] = 0
        rows.append(start)
        interventions.append(
            capture.park_sa1_at_current_pc(
                m,
                "park the checkpoint producer while the 5A22 renderer drains",
            )
        )
        frozen_tick = start["tick"]

        for relative in range(1, args.max_frames + 1):
            response = m.set_input(0, 1)
            m.pause()
            advanced = int(response.get("framesAdvanced", response.get("frames", 0)))
            if advanced != 1:
                raise RuntimeError(f"one-frame advance failed: {response!r}")
            row = capture.snapshot(m)
            row["relative_frame"] = relative
            if row["tick"] != frozen_tick:
                raise RuntimeError(
                    "SA-1 producer freeze failed: "
                    f"tick changed from {frozen_tick} to {row['tick']} "
                    f"at relative frame {relative}"
                )
            if relative % args.checkpoint_step == 0:
                row["checkpoint"] = capture.save_checkpoint(
                    m, output / f"frame-{relative:06d}.mss"
                )
            rows.append(row)
            if coherent_idle(row):
                idle_row = row
                idle_row["checkpoint"] = capture.save_checkpoint(
                    m, output / "coherent-idle.mss"
                )
                idle_row["screenshot"] = capture.take_screenshot(
                    m, output / "coherent-idle.png"
                )
                break

    report = {
        "schema": 1,
        "scope": (
            "legacy-Mesen checkpoint renderer drain with producer frozen; "
            "diagnostic only, not gameplay, fresh boot, performance, or pixel authority"
        ),
        "rom": str(args.rom.resolve()),
        "rom_sha256": sha256(args.rom),
        "state": str(args.state.resolve()),
        "state_sha256": sha256(args.state),
        "emulator": str(args.emulator.resolve()),
        "runtime_memory_writes": interventions,
        "coherent_idle_reached": idle_row is not None,
        "start": rows[0],
        "end": rows[-1],
        "sampled_boundaries": rows,
        "acceptance_authority": "none",
    }
    target = output / "results.json"
    target.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    print(
        json.dumps(
            {
                "coherent_idle_reached": idle_row is not None,
                "frames": len(rows) - 1,
                "result": str(target),
            },
            sort_keys=True,
        )
    )
    return 0 if idle_row is not None else 1


if __name__ == "__main__":
    raise SystemExit(main())
