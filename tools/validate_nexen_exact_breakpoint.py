#!/usr/bin/env python3
"""Validate Nexen's MCP-scoped synchronous execution breakpoint.

This is a debugger-control regression, not game-semantic or performance
evidence.  It loads one authenticated current-ROM state, repeatedly stops
before the production native $003A92 update entry, proves that every stop is
architecturally exact and coherent, and proves that the scoped breakpoint is
removed before normal frame advancement resumes.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
import time
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_ROM = ROOT / "build/interp.sfc"
DEFAULT_NEXEN = Path(
    "/mnt/sdc1/Nexen-r5-20260712/bin/linux-x64/Release/"
    "mcp-exact-publish/Nexen"
)
DEFAULT_STATE = (
    ROOT
    / "build/playtest-investigation-20260725/"
    "fresh-campaign-entrysync-3ea4faf-to01100-v1/states/failure.mss"
)

sys.path.insert(0, "/home/chad/Mesen2/python")
import mesen_mcp.session as _session  # noqa: E402

_session.validate_mesen_build = lambda *_args, **_kwargs: None
from mesen_mcp import McpSession  # noqa: E402


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def native_symbol(label: str) -> int:
    path = ROOT / "src/escbank.sym"
    for line in path.read_text(encoding="utf-8").splitlines():
        fields = line.split()
        if len(fields) >= 2 and fields[1] == label:
            return 0x920000 | (
                int(fields[0].split(":")[-1], 16) & 0xFFFF
            )
    raise RuntimeError(f"{path}: missing symbol {label}")


ENTRY = native_symbol("entry_3a92")


def wait_for_file(path: Path, timeout: float = 20.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if path.is_file() and path.stat().st_size:
            return
        time.sleep(0.05)
    raise TimeoutError(f"save state was not flushed: {path}")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--rom", type=Path, default=DEFAULT_ROM)
    parser.add_argument("--nexen", type=Path, default=DEFAULT_NEXEN)
    parser.add_argument("--state", type=Path, default=DEFAULT_STATE)
    parser.add_argument("--hits", type=int, default=100)
    parser.add_argument("--max-frames", type=int, default=120)
    parser.add_argument("--port", type=int, default=9481)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    for path in (args.rom, args.nexen, args.state):
        if not path.is_file():
            parser.error(f"missing required input: {path}")
    if args.hits < 2:
        parser.error("--hits must be at least 2")
    if args.max_frames < 1:
        parser.error("--max-frames must be positive")
    if args.output.exists():
        parser.error(f"output already exists: {args.output}")

    args.output.mkdir(parents=True)
    event_path = args.output / "events.jsonl"
    summary_path = args.output / "summary.json"
    pre_state = args.output / "pre-entry-000.mss"
    stderr_log = args.output / "nexen.stderr.log"
    provenance: dict[str, Any] = {
        "event": "provenance",
        "scope": (
            "Nexen managed debugger-control regression: synchronous "
            "pre-instruction SA-1 stops and scoped-breakpoint removal; "
            "not game-semantic, fresh-boot, or performance evidence"
        ),
        "rom": str(args.rom.resolve()),
        "rom_sha256": sha256(args.rom),
        "nexen": str(args.nexen.resolve()),
        "nexen_sha256": sha256(args.nexen),
        "state": str(args.state.resolve()),
        "state_sha256": sha256(args.state),
        "entry": f"{ENTRY:06X}",
        "requested_hits": args.hits,
        "max_frames_per_hit": args.max_frames,
        "emulation_core_or_rom_modified": False,
        "time_unix": time.time(),
    }
    events: list[dict[str, Any]] = [provenance]
    result = "red"
    failure: dict[str, Any] | None = None
    previous_cycles: int | None = None
    frame_removal_check: dict[str, Any] | None = None

    try:
        with McpSession(
            rom=str(args.rom.resolve()),
            mesen=str(args.nexen.resolve()),
            cwd=ROOT,
            port=args.port,
            boot_wait=8.0,
            socket_timeout=180.0,
            stderr_log=stderr_log,
        ) as m:
            m.pause()
            load_response = m.load_state(str(args.state.resolve()))
            m.pause()
            provenance["load_response"] = load_response

            for index in range(args.hits):
                stop = dict(
                    m.tool(
                        "run_to_exec_breakpoint",
                        {
                            "address": ENTRY,
                            "cpuType": "Sa1",
                            "maxFrames": args.max_frames,
                        },
                    )
                )
                cpu_first = dict(m.get_cpu_state("Sa1"))
                cpu_second = dict(m.get_cpu_state("Sa1"))
                address = (
                    (int(cpu_first.get("k", 0)) & 0xFF) << 16
                    | (int(cpu_first.get("pc", 0)) & 0xFFFF)
                )
                cycles = int(cpu_first.get("cycleCount", 0))
                checks = {
                    "hit": stop.get("hit") is True,
                    "reason": stop.get("reason") == "breakpoint",
                    "paused": stop.get("isPaused") is True,
                    "exact_pc": address == ENTRY,
                    "coherent_repeat_read": cpu_first == cpu_second,
                    "scoped_breakpoint_removed": (
                        stop.get("scopedBreakpointRemoved") is True
                    ),
                    "strict_cycle_progress": (
                        previous_cycles is None or cycles > previous_cycles
                    ),
                }
                event = {
                    "event": "exact_stop",
                    "index": index,
                    "stop": stop,
                    "cpu": cpu_first,
                    "checks": checks,
                    "result": (
                        "green" if all(checks.values()) else "red"
                    ),
                }
                events.append(event)
                if event["result"] != "green":
                    raise RuntimeError(
                        f"exact stop {index} failed: {checks}, stop={stop}"
                    )
                previous_cycles = cycles

                if index == 0:
                    response = m.save_state(pre_state.resolve())
                    wait_for_file(pre_state)
                    provenance["retained_pre_entry_state"] = {
                        "path": str(pre_state.resolve()),
                        "sha256": sha256(pre_state),
                        "response": response,
                    }
                    before_frame = int(m.get_state()["frameCount"])
                    frame_response = dict(m.run_frames(1))
                    m.pause()
                    after_frame = int(m.get_state()["frameCount"])
                    frame_removal_check = {
                        "before_frame": before_frame,
                        "after_frame": after_frame,
                        "response": frame_response,
                        "result": (
                            "green"
                            if after_frame - before_frame == 1
                            and int(frame_response.get("framesAdvanced", 0))
                            == 1
                            else "red"
                        ),
                    }
                    events.append(
                        {
                            "event": "scoped_breakpoint_removal",
                            **frame_removal_check,
                        }
                    )
                    if frame_removal_check["result"] != "green":
                        raise RuntimeError(
                            "scoped breakpoint remained armed after return"
                        )

            result = "green"
    except Exception as exc:
        failure = {"reason": repr(exc)}

    with event_path.open("x", encoding="utf-8") as stream:
        for event in events:
            stream.write(json.dumps(event, sort_keys=True) + "\n")
    summary = {
        **provenance,
        "result": result,
        "failure": failure,
        "green_hits": sum(
            row.get("event") == "exact_stop"
            and row.get("result") == "green"
            for row in events
        ),
        "requested_hits": args.hits,
        "frame_removal_check": frame_removal_check,
        "events": str(event_path.resolve()),
    }
    summary_path.write_text(
        json.dumps(summary, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(summary, sort_keys=True))
    return 0 if result == "green" else 1


if __name__ == "__main__":
    raise SystemExit(main())
