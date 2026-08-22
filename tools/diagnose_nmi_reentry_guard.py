#!/usr/bin/env python3
"""Record successive NMI entries, stack pointers, and the private busy flag."""

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
    p.add_argument("--port", type=int, default=9392)
    p.add_argument("--entries", type=int, default=12)
    args = p.parse_args()
    if args.output.exists():
        raise SystemExit(f"output exists: {args.output}")
    args.output.mkdir(parents=True)
    os.environ["DOTNET_ROOT"] = "/home/chad/.dotnet10"
    os.environ["PATH"] = f"/home/chad/.dotnet10:{os.environ['PATH']}"
    rows = []
    with McpSession(
        rom=args.rom.resolve(), mesen=args.emulator.resolve(), cwd=ROOT,
        port=args.port, boot_wait=0.0, socket_timeout=120.0,
        stderr_log=args.output / "emulator.stderr.log",
    ) as m:
        m.pause(); m.load_state(args.state.resolve()); m.pause()
        for index in range(args.entries):
            stop = dict(m.tool("run_to_exact_exec_stop", {
                "address": 0x7F8F00, "cpuType": "Snes", "maxFrames": 3,
                "occurrences": 1,
            }))
            m.pause()
            cpu = dict(m.get_cpu_state("Snes"))
            rows.append({
                "index": index,
                "frame": int(m.get_state().get("frameCount", 0)),
                "sp": int(cpu.get("sp", -1)),
                "pc": (int(cpu.get("k", 0)) << 16) | int(cpu.get("pc", 0)),
                "busy_1f22": int(m.read_memory("snesMemory", 0x7E1F22, 1)[0]),
                "stop": stop,
            })
            if not stop.get("hit"):
                break
    report = {"scope": "successive retained-state NMI reentry guard diagnostic", "rows": rows}
    path = args.output / "results.json"
    path.write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps({"result": str(path), "rows": rows}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
