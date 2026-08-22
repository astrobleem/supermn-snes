#!/usr/bin/env python3
"""Record exact 5A22 coprocessor-IRQ entry/RTI stack boundaries from a state."""

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
    parser = argparse.ArgumentParser()
    parser.add_argument("--rom", type=Path, required=True)
    parser.add_argument("--state", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--emulator", type=Path, required=True)
    parser.add_argument("--port", type=int, default=9394)
    parser.add_argument("--pairs", type=int, default=32)
    args = parser.parse_args()
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
    ) as mesen:
        mesen.pause(); mesen.load_state(args.state.resolve()); mesen.pause()
        for pair in range(args.pairs):
            for phase, address in (("entry", 0x7F8F40), ("rti", 0x7F8F70)):
                stop = dict(mesen.tool("run_to_exact_exec_stop", {
                    "address": address, "cpuType": "Snes", "maxFrames": 2,
                    "occurrences": 1,
                }))
                mesen.pause()
                cpu = dict(mesen.get_cpu_state("Snes"))
                rows.append({
                    "pair": pair, "phase": phase,
                    "frame": int(mesen.get_state().get("frameCount", 0)),
                    "sp": int(cpu.get("sp", -1)),
                    "ps": int(cpu.get("ps", -1)),
                    "pc": (int(cpu.get("k", 0)) << 16) | int(cpu.get("pc", 0)),
                    "busy_1f22": mesen.read_memory("snesMemory", 0x1F22, 1)[0],
                    "stop": stop,
                })
                if stop.get("reason") != "breakpoint" or not stop.get("hit"):
                    break
            else:
                continue
            break
    result = {"scope": "retained-state exact 5A22 IRQ stack diagnostic", "rows": rows}
    path = args.output / "results.json"
    path.write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps({"result": str(path), "rows": rows}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
