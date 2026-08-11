#!/usr/bin/env python3
"""Trace one-entry-at-a-time from a retained organic campaign boundary.

This is a forensic continuation only.  It does not turn the ordinary retained
state into a fresh-boot or resumable release checkpoint; it records the first
entry where the exact stop is lost and the interpreter diagnostic that remains.
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


def u16(data: bytes, offset: int) -> int:
    return int.from_bytes(data[offset : offset + 2], "little")


def u32(data: bytes, offset: int) -> int:
    return int.from_bytes(data[offset : offset + 4], "little")


def diag(m: McpSession) -> dict[str, Any]:
    iram = bytes(m.read_memory("Sa1Memory", 0, 0xB0))
    ring = bytes(m.read_memory("Sa1Memory", 0x0400, 0x0200))
    contexts = bytes(m.read_memory("snesMemory", 0x40000A, 16 * 4))
    floors = bytes(m.read_memory("snesMemory", 0xC10882, 16 * 4))
    cpu = dict(m.get_cpu_state("Sa1"))
    return {
        "cpu": cpu,
        "m68k": campaign.register_snapshot(m),
        "virtual_pc": u32(iram, 0x40),
        "opcode": u16(iram, 0x44),
        "pc_ring_pointer": u16(iram, 0x48),
        "step": u16(iram, 0x4C),
        "halt": u16(iram, 0x4E),
        "irq_countdown": u16(iram, 0xAC),
        "gates": {
            f"{address:04X}": u16(bytes(m.read_memory("Sa1Memory", address, 2)), 0)
            for address in (0x071A, 0x073A, 0x072E, 0x0734, 0x0736, 0x073C)
        },
        "pc_ring_sha256": campaign.digest(ring),
        "pc_ring_hex": ring.hex(),
        "task_contexts": [
            int.from_bytes(contexts[index * 4 : index * 4 + 4], "big")
            for index in range(16)
        ],
        "task_floors": [
            int.from_bytes(floors[index * 4 : index * 4 + 4], "big")
            for index in range(16)
        ],
        "task5_margin": (
            int.from_bytes(contexts[5 * 4 : 6 * 4], "big")
            - int.from_bytes(floors[5 * 4 : 6 * 4], "big")
        ),
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--rom", type=Path, required=True)
    parser.add_argument("--state", type=Path, required=True)
    parser.add_argument("--nexen", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--entries", type=int, default=80)
    parser.add_argument("--frames", type=int, default=320)
    parser.add_argument(
        "--buttons",
        type=lambda value: int(value, 0),
        help=(
            "optional held port-0 mask to install after state load and before "
            "the first observed entry (for example 0x02 for Button 1)"
        ),
    )
    parser.add_argument(
        "--mode",
        choices=("native-on", "native-off", "both"),
        default="both",
    )
    parser.add_argument("--port", type=int, default=9350)
    return parser.parse_args()


def run_variant(args: argparse.Namespace, mode: str, port: int) -> dict[str, Any]:
    out = args.output / mode
    out.mkdir()
    proc = subprocess.Popen(
        [
            "env",
            "DOTNET_ROOT=/home/chad/.dotnet10",
            str(args.nexen),
            "--mcp",
            f"--mcp-port={port}",
            str(args.rom),
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    try:
        time.sleep(2.0)
        with McpSession(
            rom=str(args.rom),
            mesen=str(args.nexen),
            port=port,
            boot_wait=1.0,
            socket_timeout=300.0,
        ) as m:
            m.load_state(str(args.state))
            if mode == "native-off":
                m.write_memory("Sa1Memory", 0x071A, "0000")
                m.write_memory("Sa1Memory", 0x073A, "0000")
            input_response = None
            if args.buttons is not None:
                input_response = campaign.set_held_input(m, args.buttons)
            rows: list[dict[str, Any]] = []
            for entry in range(1, args.entries + 1):
                before = diag(m)
                result = dict(
                    m.tool(
                        "run_to_exact_exec_stop",
                        {
                            "address": campaign.ENTRY_3A92_NATIVE,
                            "cpuType": "Sa1",
                            "maxFrames": args.frames,
                            "occurrences": 1,
                        },
                    )
                )
                after = diag(m)
                row = {
                    "entry": entry,
                    "before": before,
                    "run": result,
                    "after": after,
                }
                rows.append(row)
                (out / f"entry-{entry:03d}.json").write_text(
                    json.dumps(row, indent=2, sort_keys=True) + "\n",
                    encoding="utf-8",
                )
                if result.get("reason") != "breakpoint" or not result.get("hit"):
                    break
            return {
                "mode": mode,
                "buttons": args.buttons,
                "input_response": input_response,
                "entries_requested": args.entries,
                "rows": rows,
                "first_failed_entry": next(
                    (row["entry"] for row in rows if row["run"].get("reason") != "breakpoint"),
                    None,
                ),
            }
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()


def main() -> int:
    args = parse_args()
    args.output.mkdir(parents=True, exist_ok=False)
    if args.mode == "both":
        variants = {
            "native-off": run_variant(args, "native-off", args.port),
            "native-on": run_variant(args, "native-on", args.port + 1),
        }
    else:
        variants = {args.mode: run_variant(args, args.mode, args.port)}
    summary = {
        "result": "green",
        "classification": "pre-failure-entry-trace",
        "scope": "forensic continuation from retained post-update boundary; not fresh-boot proof",
        "rom": str(args.rom),
        "state": str(args.state),
        "variants": variants,
    }
    (args.output / "summary.json").write_text(
        json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(
        json.dumps(
            {
                mode: {
                    "entries": len(value["rows"]),
                    "first_failed_entry": value["first_failed_entry"],
                    "terminal": value["rows"][-1]["after"] if value["rows"] else None,
                }
                for mode, value in variants.items()
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
