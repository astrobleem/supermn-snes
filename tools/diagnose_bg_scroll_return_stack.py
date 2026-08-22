#!/usr/bin/env python3
"""Capture the exact JSL return record around the failing BG scroll helper."""

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


def snap(m: McpSession) -> dict:
    cpu = dict(m.get_cpu_state("Snes"))
    sp = int(cpu["sp"]) & 0xFFFF
    start = max(0, sp - 8)
    return {
        "frame": int(m.get_state().get("frameCount", 0)),
        "cpu": {k: cpu.get(k) for k in ("k", "pc", "sp", "ps", "a", "x", "y", "d", "dbr")},
        "stack_start": start,
        "stack": bytes(m.read_memory("snesMemory", start, min(40, 0x10000 - start))).hex(),
    }


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--rom", type=Path, required=True)
    p.add_argument("--state", type=Path, required=True)
    p.add_argument("--output", type=Path, required=True)
    p.add_argument("--emulator", type=Path, required=True)
    p.add_argument("--port", type=int, default=7788)
    args = p.parse_args()
    if args.output.exists():
        raise SystemExit(f"output exists: {args.output}")
    args.output.mkdir(parents=True)
    d8, d10 = "/home/chad/.dotnet8", "/home/chad/.dotnet10"
    selected = d8 if args.emulator.name == "mesen211_mcp_controller.sh" else d10
    os.environ["DOTNET_ROOT"] = selected
    os.environ["PATH"] = ":".join([selected, d8, d10] + [x for x in os.environ.get("PATH", "").split(":") if x and x not in (d8, d10)])
    rows = []
    with McpSession(rom=args.rom.resolve(), mesen=args.emulator.resolve(), cwd=ROOT,
                    port=args.port, boot_wait=0.0, socket_timeout=120.0,
                    stderr_log=args.output / "emulator.stderr.log") as m:
        m.pause(); m.load_state(args.state.resolve()); m.pause()
        for label, address, occurrences in (
            ("second_nmi_rti", 0x7F8F3F, 2),
            ("next_nmi_trampoline", 0x00942C, 1),
            ("next_nmi_handler", 0x7F8F00, 1),
        ):
            stop = dict(m.tool("run_to_exact_exec_stop", {
                "address": address, "cpuType": "Snes", "maxFrames": 4,
                "occurrences": occurrences,
            }))
            m.pause()
            rows.append({"label": label, "stop": stop, "snapshot": snap(m)})
            if stop.get("reason") != "breakpoint" or not stop.get("hit"):
                break
    result = {"scope": "exact-stop BG scroll JSL return-record diagnostic", "rows": rows}
    (args.output / "results.json").write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps(result))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
