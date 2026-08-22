#!/usr/bin/env python3
"""Dump compact interpreter/register state from a Mesen/Nexen save state.

This is diagnostic-only.  It does not run gameplay, mutate RAM, or assert
acceptance; it loads a retained state and records enough 68K/interpreter state
to classify a stall without re-running a long scenario.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, "/home/chad/Mesen2/python")

import mesen_mcp.session as _session

_session.validate_mesen_build = lambda *_args, **_kwargs: None
from mesen_mcp import McpSession


DEFAULT_EMULATOR = ROOT / "tools" / "mesen211_mcp_controller.sh"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--rom", type=Path, required=True)
    parser.add_argument("--state", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--emulator", type=Path, default=DEFAULT_EMULATOR)
    parser.add_argument("--port", type=int, default=7660)
    parser.add_argument("--run-frames", type=int, default=0)
    return parser.parse_args()


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


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def le16(data: bytes) -> int:
    return data[0] | (data[1] << 8)


def le32(data: bytes) -> int:
    return le16(data[0:2]) | (le16(data[2:4]) << 16)


def cpu_address(cpu: dict[str, Any]) -> int:
    return ((int(cpu.get("k", 0)) & 0xFF) << 16) | (int(cpu.get("pc", 0)) & 0xFFFF)


def read68k_opcode(m: McpSession, pc: int) -> dict[str, Any]:
    pc_low = pc & 0xFFFF
    pc_high = (pc >> 16) & 0xFFFF
    if pc_high == 0x00F0:
        memory_type = "snesMemory"
        address = 0x400000 | pc_low
    elif pc_high < 0x0008:
        memory_type = "snesMemory"
        address = ((0xC1 + pc_high) << 16) | pc_low
    else:
        memory_type = "snesMemory"
        address = 0x400000 | pc_low
    raw = bytes(m.read_memory(memory_type, address, 8))
    return {
        "pc": pc,
        "memory_type": memory_type,
        "mapped_address": address,
        "raw8": raw.hex(),
        "opcode_be": int.from_bytes(raw[0:2], "big"),
    }


def reg_dump(dp: bytes) -> dict[str, int]:
    regs: dict[str, int] = {}
    for index, name in enumerate(
        ["D0", "D1", "D2", "D3", "D4", "D5", "D6", "D7"]
        + ["A0", "A1", "A2", "A3", "A4", "A5", "A6", "A7"]
    ):
        regs[name] = le32(dp[index * 4:index * 4 + 4])
    return regs


def main() -> int:
    args = parse_args()
    if args.output.exists():
        raise SystemExit(f"output already exists: {args.output}")
    args.output.mkdir(parents=True)
    configure_dotnet8()

    result: dict[str, Any] = {
        "scope": "saved-state 68K/interpreter register dump; diagnostic only",
        "rom": str(args.rom.resolve()),
        "rom_sha256": sha256(args.rom),
        "state": str(args.state.resolve()),
        "state_sha256": sha256(args.state),
        "emulator": str(args.emulator.resolve()),
    }

    with McpSession(
        rom=args.rom.resolve(),
        mesen=args.emulator.resolve(),
        cwd=ROOT,
        port=args.port,
        boot_wait=0.0,
        socket_timeout=120.0,
        stderr_log=args.output / "emulator.stderr.log",
    ) as m:
        m.pause()
        result["load_state"] = dict(m.load_state(args.state.resolve()))
        m.pause()
        if args.run_frames:
            result["run_frames"] = args.run_frames
            m.run_frames(args.run_frames)
            m.pause()
        state = dict(m.get_state())
        snes = dict(m.get_cpu_state("Snes"))
        sa1 = dict(m.get_cpu_state("Sa1"))
        dp = bytes(m.read_memory("Sa1Memory", 0x0000, 0x0100))
        regs = reg_dump(dp[0x00:0x40])
        pc = le32(dp[0x40:0x44]) & 0x00FFFFFF
        result["snapshot"] = {
            "frame": int(state.get("frameCount", 0)),
            "snes_pc": cpu_address(snes),
            "sa1_pc": cpu_address(sa1),
            "snes_cpu": snes,
            "sa1_cpu": sa1,
            "pc68k": read68k_opcode(m, pc),
            "regs": regs,
            "flags": {
                "Z": le16(dp[0x60:0x62]),
                "C": le16(dp[0x6E:0x70]),
                "N": le16(dp[0x70:0x72]),
                "V": le16(dp[0x72:0x74]),
                "X": le16(dp[0xA2:0xA4]),
            },
            "interp": {
                "halt": le16(dp[0x4E:0x50]),
                "cchip_command": dp[0x62],
                "cchip_index": dp[0x64],
                "cchip_phase": dp[0xA8],
                "tick": le16(bytes(m.read_memory("Sa1Memory", 0x0760, 2))),
                "test_mode": le16(dp[0x7E:0x80]),
                "dp_80_8f": dp[0x80:0x90].hex(),
            },
            "boot": {
                "activity": int(m.read_memory("snesWorkRam", 0x1F1B, 1)[0]),
                "pacing_arm": le16(bytes(m.read_memory("snesMemory", 0x410122, 2))),
                "task_mask": le16(bytes(m.read_memory("snesMemory", 0x400002, 2))),
            },
            "scheduler": {
                "sa1_00a0_00bf": bytes(
                    m.read_memory("Sa1Memory", 0x00A0, 0x20)
                ).hex(),
                "sa1_0700_075f": bytes(
                    m.read_memory("Sa1Memory", 0x0700, 0x60)
                ).hex(),
                "sa1_0760_077f": bytes(
                    m.read_memory("Sa1Memory", 0x0760, 0x20)
                ).hex(),
                "snes_410000_41000f": bytes(
                    m.read_memory("snesMemory", 0x410000, 0x10)
                ).hex(),
                "snes_410120_41013f": bytes(
                    m.read_memory("snesMemory", 0x410120, 0x20)
                ).hex(),
                "snes_400000_40001f": bytes(
                    m.read_memory("snesMemory", 0x400000, 0x20)
                ).hex(),
            },
            "cchip_shared_f000_f040": bytes(
                m.read_memory("snesMemory", 0x41F000, 0x40)
            ).hex(),
            "work_1c20_1c80": bytes(
                m.read_memory("snesMemory", 0x401C20, 0x60)
            ).hex(),
            "work_1b00_1b40": bytes(
                m.read_memory("snesMemory", 0x401B00, 0x40)
            ).hex(),
        }
        try:
            result["snapshot"]["sa1_bus_work_1c20_1c80"] = bytes(
                m.read_memory("Sa1Memory", 0x401C20, 0x60)
            ).hex()
        except Exception as exc:  # diagnostic only; older MCP builds may reject it
            result["snapshot"]["sa1_bus_work_1c20_1c80_error"] = repr(exc)
        try:
            result["snapshot"]["sa1_bwram_mapping_regs_2220_2225"] = bytes(
                m.read_memory("snesMemory", 0x2220, 6)
            ).hex()
        except Exception as exc:
            result["snapshot"]["sa1_bwram_mapping_regs_2220_2225_error"] = repr(exc)
        try:
            result["snapshot"]["snes_save_ram_1c20_1c80"] = bytes(
                m.read_memory("SnesSaveRam", 0x1C20, 0x60)
            ).hex()
        except Exception as exc:
            result["snapshot"]["snes_save_ram_1c20_1c80_error"] = repr(exc)

    out = args.output / "results.json"
    out.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
    snap = result["snapshot"]
    print(
        json.dumps(
            {
                "result": str(out),
                "rom_sha256": result["rom_sha256"],
                "frame": snap["frame"],
                "pc68k": snap["pc68k"]["pc"],
                "opcode_be": snap["pc68k"]["opcode_be"],
                "regs": {
                    key: snap["regs"][key]
                    for key in ("D0", "D1", "D2", "D7", "A0", "A1", "A5")
                },
                "cchip": snap["interp"],
                "boot_activity": snap["boot"]["activity"],
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
