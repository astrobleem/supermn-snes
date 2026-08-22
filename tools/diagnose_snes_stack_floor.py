#!/usr/bin/env python3
"""Stop when the 5A22 first writes a selected low-WRAM stack address."""

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


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--rom", type=Path, required=True)
    p.add_argument("--state", type=Path, required=True)
    p.add_argument("--output", type=Path, required=True)
    p.add_argument("--emulator", type=Path, required=True)
    p.add_argument("--port", type=int, default=9393)
    p.add_argument("--address", type=lambda value: int(value, 0), default=0x0700)
    args = p.parse_args()
    if args.output.exists():
        raise SystemExit(f"output exists: {args.output}")
    args.output.mkdir(parents=True)
    os.environ["DOTNET_ROOT"] = "/home/chad/.dotnet10"
    os.environ["PATH"] = f"/home/chad/.dotnet10:{os.environ['PATH']}"
    with McpSession(
        rom=args.rom.resolve(), mesen=args.emulator.resolve(), cwd=ROOT,
        port=args.port, boot_wait=0.0, socket_timeout=120.0,
        stderr_log=args.output / "emulator.stderr.log",
    ) as m:
        m.pause(); m.load_state(args.state.resolve()); m.pause()
        m.trace_log(1, "Snes")
        hook = m.add_write_hook(args.address, cpu_type="Snes")
        m.drain_notifications(timeout=0.05)
        stop = dict(m.run_until(max_frames=3, hook_handle=hook))
        m.pause()
        cpu = dict(m.get_cpu_state("Snes"))
        report = {
            "scope": "retained-state exact 5A22 stack-floor write stop",
            "address": args.address,
            "stop": stop,
            "frame": int(m.get_state().get("frameCount", 0)),
            "cpu": cpu,
            "disassembly": m.disassemble(
                ((int(cpu.get("k", 0)) & 0xFF) << 16) | int(cpu.get("pc", 0)),
                count=16, cpu_type="Snes",
            ),
            "trace": m.trace_log(1000, "Snes"),
        }
    path = args.output / "results.json"
    path.write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps({"result": str(path), "frame": report["frame"], "cpu": cpu, "stop": stop}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
