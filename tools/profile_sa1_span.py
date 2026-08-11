#!/usr/bin/env python3
"""Profile a non-nested SA-1 native span with cycle-stamped execution hooks.

This is checkpointed local-span attribution, never end-to-end FPS evidence.
The entry and exit addresses are instructions; the measured interval includes
the entry instruction and stops immediately before the exit instruction.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import statistics
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

import validate_gameplay_controls as controls
import validate_render_helpers as base


def integer(value: str) -> int:
    return int(value, 0)


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def summarize(values: list[int]) -> dict[str, float | int | None]:
    return {
        "count": len(values),
        "minimum": min(values, default=None),
        "median": statistics.median(values) if values else None,
        "mean": statistics.fmean(values) if values else None,
        "maximum": max(values, default=None),
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--rom", type=Path, required=True)
    parser.add_argument("--state", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--entry", type=integer, required=True)
    parser.add_argument("--exit", dest="exit_address", type=integer, required=True)
    parser.add_argument("--nexen", type=Path, default=controls.DEFAULT_NEXEN)
    parser.add_argument("--port", type=int, default=7981)
    parser.add_argument("--frames", type=int, default=240)
    parser.add_argument("--chunk-frames", type=int, default=60)
    parser.add_argument("--buttons", type=integer, default=0x82)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    for path in (args.rom, args.state, args.nexen):
        if not path.is_file() or path.stat().st_size == 0:
            raise FileNotFoundError(path)
    if args.output.exists():
        raise SystemExit(f"refusing existing output: {args.output}")
    if args.frames <= 0 or args.chunk_frames <= 0:
        raise SystemExit("--frames and --chunk-frames must be positive")
    args.output.mkdir(parents=True)

    events: list[dict[str, int | str]] = []
    # ``mesen_mcp.McpSession`` only connects to an already-running server;
    # that made this otherwise useful profiler fail before launching Nexen.
    # Reuse the project launcher used by the exact Stage-3 validators.
    with base.McpSession(
        rom=str(args.rom.resolve()),
        mesen=str(args.nexen.resolve()),
        cwd=ROOT,
        port=args.port,
        boot_wait=8.0,
        socket_timeout=300.0,
        stderr_log=args.output / "nexen.stderr.log",
    ) as session:
        session.pause()
        session.load_state(args.state.resolve())
        session.pause()
        initial = controls.snapshot(session, "initial")
        controls.require_healthy("initial", initial)
        handles = {
            session.add_exec_hook(args.entry, cpu_type="Sa1"): "entry",
            session.add_exec_hook(args.exit_address, cpu_type="Sa1"): "exit",
        }
        session.drain_notifications(timeout=0.05)
        session.tool(
            "set_input", {"port": 0, "buttons": args.buttons, "hold": True}
        )
        remaining = args.frames
        while remaining:
            count = min(args.chunk_frames, remaining)
            result = session.run_frames(count)
            advanced = int(result.get("framesAdvanced", 0))
            if advanced <= 0:
                raise RuntimeError(f"no frame progress: {result!r}")
            remaining -= advanced
            for notification in session.drain_notifications(timeout=0.10):
                if notification.get("method") != "notifications/mesen/hookFired":
                    continue
                params = notification.get("params", {})
                label = handles.get(int(params.get("handle", -1)))
                if label is None:
                    continue
                events.append(
                    {
                        "label": label,
                        "address": int(params.get("address", 0)),
                        "cycle": int(params.get("cycleCount", 0)),
                        "frame": int(params.get("frame", 0)),
                    }
                )
        session.pause()
        final = controls.snapshot(session, "final")
        controls.require_healthy("final", final)

    spans: list[dict[str, int]] = []
    active: dict[str, int | str] | None = None
    unmatched_exits = 0
    replaced_entries = 0
    for event in events:
        if event["label"] == "entry":
            replaced_entries += int(active is not None)
            active = event
        elif active is None:
            unmatched_exits += 1
        else:
            spans.append(
                {
                    "entry_cycle": int(active["cycle"]),
                    "exit_cycle": int(event["cycle"]),
                    "cycles": int(event["cycle"]) - int(active["cycle"]),
                    "entry_frame": int(active["frame"]),
                    "exit_frame": int(event["frame"]),
                }
            )
            active = None

    raw_path = args.output / "hooks.jsonl"
    raw_path.write_text(
        "".join(json.dumps(event, sort_keys=True) + "\n" for event in events)
    )
    result = {
        "scope": "checkpointed SA-1 native-span cycle attribution; not FPS",
        "rom": str(args.rom.resolve()),
        "rom_sha256": sha256(args.rom),
        "state": str(args.state.resolve()),
        "state_sha256": sha256(args.state),
        "nexen": str(args.nexen.resolve()),
        "nexen_sha256": sha256(args.nexen),
        "entry": f"{args.entry:06X}",
        "exit": f"{args.exit_address:06X}",
        "frames": args.frames,
        "buttons": args.buttons,
        "event_count": len(events),
        "unmatched_exits": unmatched_exits,
        "replaced_entries": replaced_entries,
        "unfinished_entry": active is not None,
        "cycles": summarize([span["cycles"] for span in spans]),
        "spans": spans,
        "initial": initial,
        "final": final,
        "hooks": {"path": str(raw_path), "sha256": sha256(raw_path)},
    }
    result_path = args.output / "results.json"
    result_path.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
    print(
        json.dumps(
            {
                "cycles": result["cycles"],
                "replaced_entries": replaced_entries,
                "unmatched_exits": unmatched_exits,
                "unfinished_entry": active is not None,
                "results": str(result_path),
            },
            sort_keys=True,
        ),
        flush=True,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
