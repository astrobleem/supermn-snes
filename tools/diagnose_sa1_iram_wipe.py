#!/usr/bin/env python3
"""Catch the first event that erases the live SA-1 interpreter state.

The user-supplied v134 frozen state has an intact video supervisor but almost
completely zero SA-1 IRAM.  Start from a healthy exact-Mesen checkpoint, watch
the two distinct SA-1 control paths (ordinary IRQ wake versus reset), and keep
the last healthy state for a narrow replay.

This is a diagnostic soak, not a performance harness.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import time
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
MESEN_PYTHON = Path("/home/chad/Mesen2/python")
for path in (ROOT / "tools", MESEN_PYTHON):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

os.environ.setdefault("DOTNET_ROOT", "/home/chad/.dotnet8")
os.environ["PATH"] = (
    "/home/chad/.dotnet8:/home/chad/.dotnet10:" + os.environ.get("PATH", "")
)

import mesen_mcp.session as _session  # noqa: E402

_session.validate_mesen_build = lambda *_args, **_kwargs: None
from mesen_mcp import McpSession  # noqa: E402


DEFAULT_MESEN = Path("/home/chad/Mesen2/bin/linux-x64/Release/Mesen")
TICK = 0x0760
TASK_MASK = 0x400002
HALT = 0x004E
RESET_ENTRY = 0x008000
PC_ZERO = 0x000000
CCNT = 0x002200
IRAM_SENTINEL = 0x000600


def le16(data: bytes) -> int:
    return int.from_bytes(data, "little")


def hook_params(notes: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        note.get("params", {})
        for note in notes
        if note.get("method") == "notifications/mesen/hookFired"
    ]


def sample(session: McpSession) -> dict[str, Any]:
    iram = session.read_memory("Sa1Memory", 0, 0x800)
    return {
        "frame": int(session.get_state().get("frameCount", 0)),
        "tick": le16(iram[TICK : TICK + 2]),
        "task_mask": le16(session.read_memory("snesMemory", TASK_MASK, 2)),
        "halt": le16(iram[HALT : HALT + 2]),
        "iram_nonzero": sum(value != 0 for value in iram),
        "iram_sha256": hashlib.sha256(iram).hexdigest(),
        "sa1_cpu": session.get_cpu_state("Sa1"),
        "snes_cpu": session.get_cpu_state("Snes"),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--rom", type=Path, required=True)
    parser.add_argument("--state", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--frames", type=int, default=30000)
    parser.add_argument("--chunk", type=int, default=120)
    parser.add_argument("--checkpoint-every", type=int, default=1200)
    parser.add_argument(
        "--run-until-hook",
        action="store_true",
        help="pause promptly on a rare hook and retain the SA-1 trace tail",
    )
    parser.add_argument("--port", type=int, default=8870)
    parser.add_argument("--mesen", type=Path, default=DEFAULT_MESEN)
    args = parser.parse_args()
    if args.frames <= 0:
        raise SystemExit("--frames must be positive")
    if args.chunk <= 0:
        raise SystemExit("--chunk must be positive")
    if args.checkpoint_every <= 0:
        raise SystemExit("--checkpoint-every must be positive")

    args.output = args.output.resolve()
    args.output.mkdir(parents=True, exist_ok=True)
    log_path = args.output / "timeline.jsonl"
    event_path = args.output / "terminal-events.json"
    last_healthy_path = args.output / "last-healthy.mss"
    terminal_path = args.output / "terminal.mss"

    with (
        log_path.open("w", encoding="utf-8") as log,
        McpSession(
            rom=args.rom.resolve(),
            mesen=args.mesen.resolve(),
            cwd=ROOT,
            port=args.port,
            boot_wait=3.0,
            socket_timeout=120.0,
        ) as session,
    ):
        session.pause()
        session.load_state(args.state.resolve())
        session.pause()

        sentinel_handle = session.add_write_hook(
            IRAM_SENTINEL,
            end_address=IRAM_SENTINEL + 1,
            cpu_type="Sa1",
            match_value=0,
            match_value_mask=0xFF,
        )
        handles = {
            session.add_exec_hook(RESET_ENTRY, cpu_type="Sa1"): "reset_entry",
            sentinel_handle: "iram_clear_sentinel",
            session.add_write_hook(
                CCNT,
                cpu_type="Snes",
                match_value=0x20,
                match_value_mask=0x20,
            ): "ccnt_reset_bit",
        }
        pc_zero_handle = None
        if args.run_until_hook:
            # Stop on the *first* bad return to PC zero.  Leaving this hook
            # active in coarse mode floods notifications once the BRK/RTI
            # terminal begins, but run_until pauses before a second BRK and
            # preserves the instruction tail that led into it.
            pc_zero_handle = session.add_exec_hook(PC_ZERO, cpu_type="Sa1")
            handles[pc_zero_handle] = "pc_zero"
        session.drain_notifications(timeout=0.05)
        if args.run_until_hook:
            # The first call enables Mesen's rolling execution log.  The API
            # exposes at most 1,000 rows; read that tail only if a rare
            # terminal hook fires.
            session.trace_log(count=1, cpu_type="Sa1")

        start = sample(session)
        start["event"] = "start"
        start["rom_sha256"] = hashlib.sha256(args.rom.read_bytes()).hexdigest()
        start["state_sha256"] = hashlib.sha256(args.state.read_bytes()).hexdigest()
        log.write(json.dumps(start, sort_keys=True) + "\n")
        log.flush()
        session.save_state(last_healthy_path)

        start_frame = int(start["frame"])
        previous = start
        current = start
        terminal = False
        next_checkpoint = start_frame + args.checkpoint_every
        terminal_events: list[dict[str, Any]] = []
        wall_start = time.monotonic()

        while int(previous["frame"]) - start_frame < args.frames:
            remaining = args.frames - (int(previous["frame"]) - start_frame)
            run_count = min(args.chunk, remaining)
            if args.run_until_hook:
                run_result = session.run_until(
                    max_frames=run_count, hook_handle=pc_zero_handle
                )
            else:
                run_result = session.run_frames(run_count)
            session.pause()
            events = []
            for params in hook_params(session.drain_notifications(timeout=0.1)):
                handle = int(params.get("handle", -1))
                events.append({"label": handles.get(handle, "unknown"), **params})

            current = sample(session)
            row = {
                "event": "sample",
                "run_frames": run_count,
                "run_result": run_result,
                "wall_seconds": time.monotonic() - wall_start,
                "hook_events": events,
                **current,
            }
            log.write(json.dumps(row, sort_keys=True) + "\n")
            log.flush()
            print(
                json.dumps(
                    {
                        "frame": current["frame"],
                        "tick": current["tick"],
                        "task_mask": current["task_mask"],
                        "halt": current["halt"],
                        "iram_nonzero": current["iram_nonzero"],
                        "hooks": [event["label"] for event in events],
                        "wall_seconds": round(row["wall_seconds"], 3),
                    },
                    sort_keys=True,
                ),
                flush=True,
            )

            terminal = bool(events)
            terminal |= int(current["iram_nonzero"]) < 32
            terminal |= (
                int(previous["tick"]) != 0
                and int(current["tick"]) == 0
                and int(current["task_mask"]) == 0
            )
            if terminal:
                terminal_events = events
                session.save_state(terminal_path)
                if args.run_until_hook:
                    trace = session.trace_log(count=1000, cpu_type="Sa1")
                    (args.output / "sa1-trace-tail.json").write_text(
                        json.dumps(trace, indent=2, sort_keys=True) + "\n"
                    )
                break

            if int(current["frame"]) >= next_checkpoint:
                session.save_state(last_healthy_path)
                next_checkpoint = int(current["frame"]) + args.checkpoint_every
            previous = current

        verdict = {
            "verdict": "terminal_caught" if terminal_events or terminal else "no_terminal",
            "start": start,
            "end": current,
            "terminal_events": terminal_events,
            "last_healthy_state": str(last_healthy_path),
            "terminal_state": str(terminal_path) if terminal else None,
            "log": str(log_path),
        }
        event_path.write_text(json.dumps(verdict, indent=2, sort_keys=True) + "\n")
        print(json.dumps(verdict, sort_keys=True), flush=True)
        return 1 if terminal else 0


if __name__ == "__main__":
    raise SystemExit(main())
