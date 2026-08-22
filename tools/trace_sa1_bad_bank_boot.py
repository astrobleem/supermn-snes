#!/usr/bin/env python3
"""Stop a fresh Mesen boot on the first SA-1 fetch from a suspicious bank.

This is a bounded boot-control diagnostic.  It does not apply input, does not
load a save state, and does not claim gameplay or renderer acceptance.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import sys
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, "/home/chad/Mesen2/python")

import mesen_mcp.session as _session

_session.validate_mesen_build = lambda *_args, **_kwargs: None
from mesen_mcp import McpSession


DEFAULT_MESEN = ROOT / "tools" / "mesen211_mcp_controller.sh"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--rom", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--mesen", type=Path, default=DEFAULT_MESEN)
    parser.add_argument("--port", type=int, default=7650)
    parser.add_argument("--bank", type=lambda value: int(value, 0), default=0xE2)
    parser.add_argument("--max-frames", type=int, default=7000)
    return parser.parse_args()


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def configure_dotnet8() -> None:
    dotnet8 = "/home/chad/.dotnet8"
    dotnet10 = "/home/chad/.dotnet10"
    os.environ["DOTNET_ROOT"] = dotnet8
    path = [
        item
        for item in os.environ.get("PATH", "").split(":")
        if item and item not in (dotnet8, dotnet10)
    ]
    os.environ["PATH"] = ":".join([dotnet8, dotnet10, *path])


def le16(data: bytes) -> int:
    return int.from_bytes(data, "little")


def cpu_address(cpu: dict[str, Any]) -> int:
    return ((int(cpu.get("k", 0)) & 0xFF) << 16) | (int(cpu.get("pc", 0)) & 0xFFFF)


def read68k_opcode(m: McpSession) -> dict[str, Any]:
    pc_low = le16(bytes(m.read_memory("Sa1Memory", 0x0040, 2)))
    pc_high = le16(bytes(m.read_memory("Sa1Memory", 0x0042, 2)))
    pc = ((pc_high & 0xFFFF) << 16) | pc_low
    if pc_high == 0x00F0:
        mem_type = "snesMemory"
        address = 0x400000 + pc_low
    else:
        mem_type = "snesMemory"
        address = 0xC10000 + pc
    raw = bytes(m.read_memory(mem_type, address, 2))
    return {
        "pc": pc,
        "memory_type": mem_type,
        "mapped_address": address,
        "raw": raw.hex(),
        "opcode_be": int.from_bytes(raw, "big"),
    }


def snapshot(m: McpSession) -> dict[str, Any]:
    state = dict(m.get_state())
    snes = dict(m.get_cpu_state("Snes"))
    sa1 = dict(m.get_cpu_state("Sa1"))
    sa1_pc = cpu_address(sa1)
    snes_pc = cpu_address(snes)
    sp = int(sa1.get("sp", 0)) & 0xFFFF
    stack_start = max(0, sp - 0x20)
    stack_len = min(0x80, 0x800 - stack_start)
    return {
        "emulator": state,
        "snes_cpu": snes,
        "sa1_cpu": sa1,
        "snes_pc": snes_pc,
        "sa1_pc": sa1_pc,
        "pc68k": read68k_opcode(m),
        "interp_dp_0000_00ff": bytes(m.read_memory("Sa1Memory", 0x0000, 0x0100)).hex(),
        "interp_private_0700_07ff": bytes(m.read_memory("Sa1Memory", 0x0700, 0x0100)).hex(),
        "sa1_stack_window": {
            "start": stack_start,
            "bytes": bytes(m.read_memory("Sa1Memory", stack_start, stack_len)).hex(),
        },
        "sa1_disassembly": m.disassemble(sa1_pc, count=24, cpu_type="Sa1"),
        "snes_disassembly": m.disassemble(snes_pc, count=16, cpu_type="Snes"),
        "sa1_trace": m.trace_log(count=96, cpu_type="Sa1"),
        "snes_trace": m.trace_log(count=48, cpu_type="Snes"),
    }


def hook_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        dict(row["params"])
        for row in rows
        if row.get("method") == "notifications/mesen/hookFired"
        and isinstance(row.get("params"), dict)
    ]


def main() -> int:
    args = parse_args()
    if not args.rom.is_file():
        raise FileNotFoundError(args.rom)
    if not args.mesen.is_file():
        raise FileNotFoundError(args.mesen)
    if args.output.exists():
        raise SystemExit(f"output already exists: {args.output}")
    args.output.mkdir(parents=True)
    configure_dotnet8()

    result: dict[str, Any] = {
        "scope": "fresh-power SA-1 suspicious-bank exec diagnostic; not gameplay evidence",
        "rom": str(args.rom.resolve()),
        "rom_sha256": sha256(args.rom),
        "mesen": str(args.mesen.resolve()),
        "bank": args.bank,
        "max_frames": args.max_frames,
    }

    with McpSession(
        rom=args.rom.resolve(),
        mesen=args.mesen.resolve(),
        cwd=ROOT,
        port=args.port,
        boot_wait=0.0,
        socket_timeout=120.0,
        stderr_log=args.output / "emulator.stderr.log",
    ) as m:
        m.pause()
        result["initial"] = snapshot(m)
        start = (args.bank & 0xFF) << 16
        end = start | 0xFFFF
        hook = m.add_exec_hook(start, end_address=end, cpu_type="Sa1")
        result["hook"] = {"handle": hook, "start": start, "end": end, "cpu": "Sa1"}
        m.drain_notifications(timeout=0.05)
        run = dict(m.run_until(max_frames=args.max_frames, hook_handle=hook))
        m.pause()
        events = hook_rows(m.drain_notifications(timeout=0.20))
        result["run_until"] = run
        result["events"] = events[:64]
        result["event_count_retained"] = len(events)
        result["hook_diag"] = dict(m.hook_diag())
        result["final"] = snapshot(m)
        shot_response = m.take_screenshot(format="path")
        screenshot = args.output / "bad-bank.png"
        shutil.copy2(Path(shot_response["path"]), screenshot)
        state = args.output / "bad-bank.mss"
        save_response = m.save_state(state.resolve())
        result["artifacts"] = {
            "screenshot": {
                "path": str(screenshot),
                "sha256": sha256(screenshot),
                "response": shot_response,
            },
            "state": {
                "path": str(state),
                "sha256": sha256(state),
                "response": save_response,
            },
        }

    result_path = args.output / "results.json"
    result_path.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
    final = result["final"]
    print(
        json.dumps(
            {
                "result": "hit" if result["events"] else "no_hit",
                "rom_sha256": result["rom_sha256"],
                "sa1_pc": final["sa1_pc"],
                "pc68k": final["pc68k"]["pc"],
                "opcode_be": final["pc68k"]["opcode_be"],
                "frame": final["emulator"].get("frameCount"),
                "results": str(result_path),
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
