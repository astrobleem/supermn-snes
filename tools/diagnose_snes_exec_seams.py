#!/usr/bin/env python3
"""Reload one state and exact-stop independently at selected 5A22 seams."""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, "/home/chad/Mesen2/python")
import mesen_mcp.session as _session  # noqa: E402

_session.validate_mesen_build = lambda *_args, **_kwargs: None
from mesen_mcp import McpSession  # noqa: E402

SEAMS = (
    ("nmi_rti", 0x7F8F3F),
    ("tad_process", 0x7F9167),
    ("tad_process_return_i8_rtl", 0x7F91AE),
    ("tad_process_command_rtl", 0x7F91E1),
    ("tad_process_null_rtl", 0x7F91EA),
    ("tad_waiting_return_rtl", 0x7F923F),
    ("tad_loading_return_rtl", 0x7F9267),
    ("vf_tick", 0x7F8918),
    ("vid_obj_fast", 0x7FA400),
    ("vid_obj_packed", 0x7FAF68),
    ("obj_slot_record_cached", 0x7FA760),
    ("obj_slot_fast_hash", 0x7F9C40),
    ("obj_tile_queue", 0x7FAC0C),
    ("obj_queue_restart_cached", 0x7FA791),
    ("obj_slot_fast_full_reset_ext", 0x7FA047),
    ("obj_cache_restart", 0x7F9C05),
    ("reference_vid_obj", 0x7F8189),
    ("reference_voi_restart", 0x7F818C),
    ("reference_obj_place", 0x7F82E4),
)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--rom", type=Path, required=True)
    parser.add_argument("--state", type=Path, required=True)
    parser.add_argument("--extra-state", type=Path, action="append", default=[])
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--emulator", type=Path, required=True)
    parser.add_argument("--port", type=int, default=9395)
    parser.add_argument("--max-frames", type=int, default=2)
    parser.add_argument("--initial-only", action="store_true")
    args = parser.parse_args()
    if args.output.exists():
        raise SystemExit(f"output exists: {args.output}")
    args.output.mkdir(parents=True)
    os.environ["DOTNET_ROOT"] = "/home/chad/.dotnet10"
    os.environ["PATH"] = f"/home/chad/.dotnet10:{os.environ['PATH']}"
    rows = []
    initial = {}
    with McpSession(
        rom=args.rom.resolve(), mesen=args.emulator.resolve(), cwd=ROOT,
        port=args.port, boot_wait=0.0, socket_timeout=120.0,
        stderr_log=args.output / "emulator.stderr.log",
    ) as mesen:
        initial_rows = []
        for state_path in (args.state, *args.extra_state):
            mesen.pause(); mesen.load_state(state_path.resolve()); mesen.pause()
            initial_cpu = dict(mesen.get_cpu_state("Snes"))
            initial_sp = int(initial_cpu.get("sp", 0)) & 0xFFFF
            initial_rows.append({
                "state": str(state_path),
                "frame": int(mesen.get_state().get("frameCount", 0)),
                "cpu": initial_cpu,
                "stack_start": initial_sp,
                "stack": mesen.read_memory(
                    "snesMemory", initial_sp, min(64, 0x10000 - initial_sp)
                ).hex(),
            })
        initial = initial_rows[0]
        if args.initial_only:
            result = {
                "scope": "retained-state initial 5A22 stack snapshot",
                "initial": initial,
                "initial_rows": initial_rows,
                "rows": [],
            }
            path = args.output / "results.json"
            path.write_text(json.dumps(result, indent=2) + "\n")
            print(json.dumps({"result": str(path), "initial": initial}))
            return 0
        for label, address in SEAMS:
            mesen.pause(); mesen.load_state(args.state.resolve()); mesen.pause()
            stop = dict(mesen.tool("run_to_exact_exec_stop", {
                "address": address, "cpuType": "Snes",
                "maxFrames": args.max_frames, "occurrences": 1,
            }))
            mesen.pause()
            cpu = dict(mesen.get_cpu_state("Snes"))
            rows.append({
                "label": label, "address": address,
                "frame": int(mesen.get_state().get("frameCount", 0)),
                "sp": int(cpu.get("sp", -1)),
                "pc": (int(cpu.get("k", 0)) << 16) | int(cpu.get("pc", 0)),
                "hit": stop.get("reason") == "breakpoint" and stop.get("hit") is True,
                "stop": stop,
            })
    result = {
        "scope": "retained-state independent exact 5A22 seam stops",
        "initial": initial,
        "rows": rows,
    }
    path = args.output / "results.json"
    path.write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps({"result": str(path), "rows": [
        {k: row[k] for k in ("label", "frame", "sp", "pc", "hit")} for row in rows
    ]}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
