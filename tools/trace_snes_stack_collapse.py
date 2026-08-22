#!/usr/bin/env python3
"""Retain the S-CPU instruction tail between a clean NMI RTI and next entry."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, "/home/chad/Mesen2/python")
import mesen_mcp.session as _session  # noqa: E402

_session.validate_mesen_build = lambda *_args, **_kwargs: None
from mesen_mcp import McpSession  # noqa: E402


def cpu(m: McpSession) -> dict:
    state = dict(m.get_cpu_state("Snes"))
    return {
        key: state.get(key)
        for key in ("k", "pc", "sp", "ps", "a", "x", "y", "d", "dbr", "stopState")
    }


def nmi_window(m: McpSession) -> dict:
    return {
        "entry_7f8f00": bytes(
            m.read_memory("snesMemory", 0x7F8F00, 0x20)
        ).hex(),
        "rom_e98f00": bytes(
            m.read_memory("snesMemory", 0xE98F00, 0x20)
        ).hex(),
    }


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--rom", type=Path, required=True)
    parser.add_argument("--state", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--emulator", type=Path, required=True)
    parser.add_argument("--port", type=int, default=9390)
    parser.add_argument(
        "--frames",
        type=int,
        default=0,
        help=(
            "when nonzero, retain the rolling S-CPU instruction tail across this "
            "many video frames instead of stopping at one RTI/entry pair"
        ),
    )
    parser.add_argument(
        "--pretrace-frames",
        type=int,
        default=0,
        help="advance this many video frames before enabling the instruction trace",
    )
    parser.add_argument(
        "--stop-address",
        type=lambda text: int(text, 0),
        help="after pretrace, stop on the first exact S-CPU execution address",
    )
    parser.add_argument(
        "--stop-opcode",
        type=lambda text: int(text, 0),
        help="optional byte-exact opcode filter for --stop-address",
    )
    parser.add_argument(
        "--stop-write-start",
        type=lambda text: int(text, 0),
        help="stop on the first S-CPU write in this inclusive address range",
    )
    parser.add_argument(
        "--stop-write-end",
        type=lambda text: int(text, 0),
        help="inclusive end for --stop-write-start (defaults to the start)",
    )
    args = parser.parse_args()
    if args.output.exists():
        raise SystemExit(f"output exists: {args.output}")
    args.output.mkdir(parents=True)
    dotnet8, dotnet10 = "/home/chad/.dotnet8", "/home/chad/.dotnet10"
    selected = dotnet8 if args.emulator.name == "mesen211_mcp_controller.sh" else dotnet10
    os.environ["DOTNET_ROOT"] = selected
    os.environ["PATH"] = ":".join(
        [selected, dotnet8, dotnet10]
        + [x for x in os.environ.get("PATH", "").split(":") if x and x not in (dotnet8, dotnet10)]
    )
    rows = []
    with McpSession(
        rom=args.rom.resolve(), mesen=args.emulator.resolve(), cwd=ROOT,
        port=args.port, boot_wait=0.0, socket_timeout=120.0,
        stderr_log=args.output / "emulator.stderr.log",
    ) as m:
        m.pause()
        m.load_state(args.state.resolve())
        m.pause()
        loaded_window = nmi_window(m)
        pretrace = None
        if args.stop_write_start is not None:
            if args.frames < 1:
                raise ValueError("--stop-write-start requires a positive --frames bound")
            if args.pretrace_frames:
                raise ValueError("--stop-write-start observes from load; omit --pretrace-frames")
            end = args.stop_write_end
            if end is None:
                end = args.stop_write_start
            m.trace_log(1, "Snes")
            rows.append({
                "label": "write_watch_start",
                "frame": int(m.get_state().get("frameCount", 0)),
                "cpu": cpu(m),
                "nmi_window": loaded_window,
            })
            hook = m.add_write_hook(args.stop_write_start, end, cpu_type="Snes")
            stop = dict(m.run_until(max_frames=args.frames, hook_handle=hook))
            m.pause()
            notifications = m.drain_notifications()
            m.remove_hook(hook)
            rows.append({
                "label": "write_watch_stop",
                "frame": int(m.get_state().get("frameCount", 0)),
                "stop": stop,
                "notifications": notifications,
                "cpu": cpu(m),
                "nmi_window": nmi_window(m),
            })
        elif args.pretrace_frames:
            if args.pretrace_frames < 1:
                raise ValueError("--pretrace-frames must be positive")
            pretrace = dict(m.run_frames(args.pretrace_frames))
            m.pause()
        if args.stop_write_start is None:
            m.trace_log(1, "Snes")
        if args.stop_write_start is not None:
            pass
        elif args.stop_address is not None:
            if args.frames < 1:
                raise ValueError("--stop-address requires a positive --frames bound")
            rows.append({
                "label": "trace_start",
                "frame": int(m.get_state().get("frameCount", 0)),
                "pretrace": pretrace,
                "cpu": cpu(m),
                "busy_1f22": int(m.read_memory("snesMemory", 0x7E1F22, 1)[0]),
            })
            hook_args = {}
            if args.stop_opcode is not None:
                hook_args = {
                    "match_value": args.stop_opcode,
                    "match_value_mask": 0xFF,
                }
            hook = m.add_exec_hook(
                args.stop_address, cpu_type="Snes", **hook_args
            )
            stop = dict(m.run_until(max_frames=args.frames, hook_handle=hook))
            m.pause()
            m.remove_hook(hook)
            rows.append({
                "label": "exact_stop",
                "frame": int(m.get_state().get("frameCount", 0)),
                "stop": stop,
                "cpu": cpu(m),
                "busy_1f22": int(m.read_memory("snesMemory", 0x7E1F22, 1)[0]),
            })
        elif args.frames:
            if args.frames < 1:
                raise ValueError("--frames must be positive")
            rows.append({
                "label": "initial",
                "frame": int(m.get_state().get("frameCount", 0)),
                "cpu": cpu(m),
                "busy_1f22": int(m.read_memory("snesMemory", 0x7E1F22, 1)[0]),
            })
            advance = dict(m.run_frames(args.frames))
            m.pause()
            rows.append({
                "label": "final",
                "frame": int(m.get_state().get("frameCount", 0)),
                "advance": advance,
                "cpu": cpu(m),
                "busy_1f22": int(m.read_memory("snesMemory", 0x7E1F22, 1)[0]),
            })
        else:
            for label, address in (("clean_rti", 0x7F8F3F), ("next_nmi_entry", 0x7F8F00)):
                stop = dict(m.tool("run_to_exact_exec_stop", {
                    "address": address, "cpuType": "Snes", "maxFrames": 3,
                    "occurrences": 1,
                }))
                m.pause()
                rows.append({
                    "label": label,
                    "frame": int(m.get_state().get("frameCount", 0)),
                    "stop": stop,
                    "cpu": cpu(m),
                    "busy_1f22": int(m.read_memory("snesMemory", 0x7E1F22, 1)[0]),
                })
        trace = m.trace_log(1000, "Snes")
        final_state = dict(m.save_state((args.output / "final.mss").resolve()))
    report = {
        "scope": "retained-state S-CPU stack-collapse instruction tail",
        "rom": str(args.rom.resolve()),
        "rom_sha256": sha256(args.rom),
        "state": str(args.state.resolve()),
        "state_sha256": sha256(args.state),
        "frames_requested": args.frames,
        "pretrace_frames_requested": args.pretrace_frames,
        "stop_address": args.stop_address,
        "stop_opcode": args.stop_opcode,
        "stop_write_start": args.stop_write_start,
        "stop_write_end": args.stop_write_end,
        "loaded_nmi_window": loaded_window,
        "rows": rows,
        "trace": trace,
        "final_state": final_state,
    }
    path = args.output / "results.json"
    path.write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps({"result": str(path), "rows": rows, "trace_rows": len(trace.get("rows", []))}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
