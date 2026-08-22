#!/usr/bin/env python3
"""Record exact 5A22 stack state at alternating NMI entry/RTI boundaries."""

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


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--rom", type=Path, required=True)
    p.add_argument("--state", type=Path, required=True)
    p.add_argument("--output", type=Path, required=True)
    p.add_argument("--emulator", type=Path, required=True)
    p.add_argument("--port", type=int, default=7778)
    p.add_argument("--pairs", type=int, default=32)
    args = p.parse_args()
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
        for pair in range(args.pairs):
            for phase, address in (("rti", 0x7F8F3F), ("entry", 0x7F8F00)):
                hook = m.add_exec_hook(address, cpu_type="Snes")
                hit = dict(m.run_until(max_frames=8, hook_handle=hook))
                m.pause()
                cpu = dict(m.get_cpu_state("Snes"))
                rows.append({
                    "pair": pair, "phase": phase,
                    "frame": int(m.get_state().get("frameCount", 0)),
                    "sp": int(cpu.get("sp", -1)), "ps": int(cpu.get("ps", -1)),
                    "pc": (int(cpu.get("k", 0)) << 16) | int(cpu.get("pc", 0)),
                    "hit": hit,
                })
                m.remove_hook(hook)
                if hit.get("reason") not in ("hookFired", "breakpoint"):
                    break
            else:
                continue
            break
        final_state = dict(m.save_state(args.output / "final.mss"))
    result = {
        "scope": "retained exact-hash NMI stack-boundary diagnostic",
        "rom": str(args.rom.resolve()),
        "rom_sha256": sha256(args.rom),
        "state": str(args.state.resolve()),
        "state_sha256": sha256(args.state),
        "pairs_requested": args.pairs,
        "rows": rows,
        "final_state": final_state,
    }
    (args.output / "results.json").write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps({
        "result": str(args.output / "results.json"),
        "row_count": len(rows),
        "last_row": rows[-1] if rows else None,
        "final_state": final_state,
    }))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
