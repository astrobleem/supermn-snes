#!/usr/bin/env python3
"""Use the interpreter's diagnostic single-step mailbox to expose the bad PC.

The source state is the retained ordinary post-update campaign boundary.  The
test flag is a diagnostic IRAM control only; the result is not production
behavior or fresh-boot evidence.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import time
from pathlib import Path
from typing import Any

import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
sys.path.insert(0, "/home/chad/Mesen2/python")
import mesen_mcp.session as _session  # type: ignore  # noqa: E402

_session.validate_mesen_build = lambda *_a, **_k: None
from mesen_mcp import McpSession  # type: ignore  # noqa: E402

import replay_mame_controller_campaign as campaign  # noqa: E402


TEST_IDLE = 0xD15F
INEXT = 0xD0D3


def u16(data: bytes, offset: int) -> int:
    return int.from_bytes(data[offset : offset + 2], "little")


def u32(data: bytes, offset: int) -> int:
    return int.from_bytes(data[offset : offset + 4], "little")


def diag(m: McpSession) -> dict[str, Any]:
    iram = bytes(m.read_memory("Sa1Memory", 0, 0xB0))
    cpu = dict(m.get_cpu_state("Sa1"))
    return {
        "cpu": cpu,
        "m68k": campaign.register_snapshot(m),
        "virtual_pc": u32(iram, 0x40),
        "opcode": u16(iram, 0x44),
        "step": u16(iram, 0x4C),
        "halt": u16(iram, 0x4E),
        "pc_ring_pointer": u16(iram, 0x48),
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--rom", type=Path, required=True)
    parser.add_argument("--state", type=Path, required=True)
    parser.add_argument("--nexen", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--entries", type=int, default=2000)
    parser.add_argument("--max-frames", type=int, default=120)
    parser.add_argument("--mode", choices=("native-on", "native-off"), default="native-on")
    parser.add_argument("--port", type=int, default=9360)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    args.output.mkdir(parents=True, exist_ok=False)
    proc = subprocess.Popen(
        [
            "env",
            "DOTNET_ROOT=/home/chad/.dotnet10",
            str(args.nexen),
            "--mcp",
            f"--mcp-port={args.port}",
            str(args.rom),
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    rows: list[dict[str, Any]] = []
    failure: dict[str, Any] | None = None
    try:
        time.sleep(2.0)
        with McpSession(
            rom=str(args.rom),
            mesen=str(args.nexen),
            port=args.port,
            boot_wait=1.0,
            socket_timeout=300.0,
        ) as m:
            m.load_state(str(args.state))
            if args.mode == "native-off":
                m.write_memory("Sa1Memory", 0x071A, "0000")
                m.write_memory("Sa1Memory", 0x073A, "0000")
            # Test mode makes each interpreted instruction return to test_idle
            # with $4E=1 (or $DEAD/$CAFE), instead of spinning permanently.
            m.write_memory("Sa1Memory", 0x007E, "0100")
            m.write_memory("Sa1Memory", 0x004E, "0000")
            m.write_memory("Sa1Memory", 0x00A0, "0100")
            first_hook = m.add_exec_hook(TEST_IDLE, cpu_type="Sa1")
            first_run = dict(m.run_until(max_frames=args.max_frames, hook_handle=first_hook))
            m.remove_hook(first_hook)
            if first_run.get("reason") != "hookFired":
                failure = {"phase": "initial", "run": first_run, "diag": diag(m)}
            else:
                rows.append({"step": 0, "run": first_run, "diag": diag(m)})
            for step in range(1, args.entries + 1):
                if failure is not None or rows[-1]["diag"]["halt"] in (0xDEAD, 0xCAFE):
                    break
                before = diag(m)
                m.write_memory("Sa1Memory", 0x004E, "0000")
                m.write_memory("Sa1Memory", 0x00A0, "0100")
                hook = m.add_exec_hook(TEST_IDLE, cpu_type="Sa1")
                run = dict(m.run_until(max_frames=args.max_frames, hook_handle=hook))
                m.remove_hook(hook)
                after = diag(m)
                row = {"step": step, "before": before, "run": run, "diag": after}
                rows.append(row)
                (args.output / f"step-{step:05d}.json").write_text(
                    json.dumps(row, indent=2, sort_keys=True) + "\n", encoding="utf-8"
                )
                if run.get("reason") != "hookFired":
                    failure = {"phase": "step", "step": step, "run": run, "diag": after}
                    break
            result = {
                "result": "green" if any(row["diag"]["halt"] == 0xDEAD for row in rows) else "red",
                "classification": "single-step-interpreter-trace",
                "scope": "diagnostic continuation from retained campaign boundary; test mode enabled",
                "mode": args.mode,
                "rom": str(args.rom),
                "state": str(args.state),
                "rows": len(rows),
                "failure": failure,
                "terminal": rows[-1] if rows else None,
            }
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()
    (args.output / "summary.json").write_text(
        json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(json.dumps({"result": result["result"], "rows": result["rows"], "terminal": result["terminal"].get("diag") if result["terminal"] else None}, sort_keys=True))
    return 0 if result["result"] == "green" else 1


if __name__ == "__main__":
    raise SystemExit(main())
