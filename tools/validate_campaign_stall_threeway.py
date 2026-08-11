#!/usr/bin/env python3
"""Compare the retained fresh-campaign stall against MAME and both SNES gates.

The retained state is an ordinary paused state after the exact-stop harness
gave up; this is diagnostic evidence, not a resumable production checkpoint.
The tool records 68000 IRAM registers/CCR/stack residue, SA-1 scheduler state,
gates, work RAM, and liveness after a controlled neutral run in native-on and
native-off modes, then pairs those observations with the original MAME
controller movie boundary.
"""

from __future__ import annotations

import argparse
import hashlib
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


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def u16le(data: bytes, offset: int) -> int:
    return int.from_bytes(data[offset : offset + 2], "little")


def u32le(data: bytes, offset: int) -> int:
    return int.from_bytes(data[offset : offset + 4], "little")


def read_capture_row(path: Path, tick: int) -> dict[str, Any]:
    for line in path.read_text(encoding="utf-8").splitlines():
        row = json.loads(line)
        if row.get("tick") == tick or row.get("name") == f"mame-tick-{tick:05d}":
            return row
    raise RuntimeError(f"missing MAME capture row for tick {tick}: {path}")


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser()
    p.add_argument("--rom", type=Path, required=True)
    p.add_argument("--state", type=Path, required=True)
    p.add_argument("--mame-dir", type=Path, required=True)
    p.add_argument("--mame-tick", type=int, required=True)
    p.add_argument("--nexen", type=Path, required=True)
    p.add_argument("--output", type=Path, required=True)
    p.add_argument("--frames", type=int, default=120)
    p.add_argument("--port", type=int, default=9320)
    return p.parse_args()


def run_variant(
    args: argparse.Namespace,
    mode: str,
    port: int,
    out: Path,
) -> dict[str, Any]:
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
        m = McpSession(
            rom=str(args.rom),
            mesen=str(args.nexen),
            port=port,
            boot_wait=1.0,
            socket_timeout=300.0,
        )
        with m:
            m.load_state(str(args.state))
            if mode == "native-off":
                m.write_memory("Sa1Memory", 0x071A, "0000")
                m.write_memory("Sa1Memory", 0x073A, "0000")
            before = {
                "cpu": m.get_cpu_state("Sa1"),
                "m68k": campaign.register_snapshot(m),
                "iram": bytes(m.read_memory("Sa1Memory", 0, 0x0800)),
                "work": bytes(m.read_memory("snesMemory", 0x400000, 0x10000)),
                "gates": {
                    f"{address:04X}": u16le(
                        bytes(m.read_memory("Sa1Memory", address, 2)), 0
                    )
                    for address in (0x071A, 0x073A, 0x072E, 0x0734, 0x0736, 0x073C)
                },
                "halt": u16le(bytes(m.read_memory("Sa1Memory", 0x004E, 2)), 0),
                "virtual_pc": u32le(bytes(m.read_memory("Sa1Memory", 0x0040, 4)), 0),
                "opcode": u16le(bytes(m.read_memory("Sa1Memory", 0x0044, 2)), 0),
                "step": u16le(bytes(m.read_memory("Sa1Memory", 0x004C, 2)), 0),
                "pc_ring_pointer": u16le(bytes(m.read_memory("Sa1Memory", 0x0048, 2)), 0),
                "frame": int(m.get_state().get("frameCount", 0)),
            }
            response = m.run_frames(args.frames)
            after = {
                "cpu": m.get_cpu_state("Sa1"),
                "m68k": campaign.register_snapshot(m),
                "iram": bytes(m.read_memory("Sa1Memory", 0, 0x0800)),
                "work": bytes(m.read_memory("snesMemory", 0x400000, 0x10000)),
                "gates": {
                    f"{address:04X}": u16le(
                        bytes(m.read_memory("Sa1Memory", address, 2)), 0
                    )
                    for address in (0x071A, 0x073A, 0x072E, 0x0734, 0x0736, 0x073C)
                },
                "halt": u16le(bytes(m.read_memory("Sa1Memory", 0x004E, 2)), 0),
                "virtual_pc": u32le(bytes(m.read_memory("Sa1Memory", 0x0040, 4)), 0),
                "opcode": u16le(bytes(m.read_memory("Sa1Memory", 0x0044, 2)), 0),
                "step": u16le(bytes(m.read_memory("Sa1Memory", 0x004C, 2)), 0),
                "pc_ring_pointer": u16le(bytes(m.read_memory("Sa1Memory", 0x0048, 2)), 0),
                "frame": int(m.get_state().get("frameCount", 0)),
            }
            screenshot = dict(m.tool("take_screenshot", {"format": "path"}))
            work_path = out / f"{mode}.after.work.bin"
            work_path.write_bytes(after["work"])
            before_work_path = out / f"{mode}.before.work.bin"
            before_work_path.write_bytes(before["work"])
            iram_path = out / f"{mode}.after.iram.bin"
            iram_path.write_bytes(after["iram"])
            before_iram_path = out / f"{mode}.before.iram.bin"
            before_iram_path.write_bytes(before["iram"])
            return {
                "mode": mode,
                "before": before,
                "after": after,
                "response": response,
                "screenshot": screenshot,
                "work_path": str(work_path),
                "before_work_path": str(before_work_path),
                "iram_path": str(iram_path),
                "before_iram_path": str(before_iram_path),
                "work_sha256": sha256(after["work"]),
                "iram_sha256": sha256(after["iram"]),
                "stayed_ispin": (
                    int(after["cpu"].get("k", 0)) == 0
                    and int(after["cpu"].get("pc", -1)) == 0xD15A
                ),
                "stayed_same_halt": after["halt"] == before["halt"],
                "unsupported_opcode_halt": (
                    after["halt"] == 0xDEAD
                    and after["opcode"] == 0xF800
                    and after["virtual_pc"] == 0x001000B0
                ),
            }
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()


def strip_bytes(value: Any) -> Any:
    if isinstance(value, bytes):
        return {"sha256": sha256(value), "length": len(value)}
    if isinstance(value, dict):
        return {key: strip_bytes(item) for key, item in value.items()}
    if isinstance(value, list):
        return [strip_bytes(item) for item in value]
    return value


def main() -> int:
    args = parse_args()
    args.output.mkdir(parents=True, exist_ok=False)
    mame_work_path = args.mame_dir / f"mame-tick-{args.mame_tick:05d}.work.bin"
    mame_work = mame_work_path.read_bytes()
    if len(mame_work) != 0x10000:
        raise RuntimeError(f"{mame_work_path}: expected 64 KiB work RAM")
    mame_row = read_capture_row(args.mame_dir / "capture.jsonl", args.mame_tick)
    variants = {
        "native-off": run_variant(args, "native-off", args.port, args.output),
        "native-on": run_variant(args, "native-on", args.port + 1, args.output),
    }
    work_equal = {
        mode: variants[mode]["after"]["work"] == mame_work
        for mode in variants
    }
    same_stall = all(
        variants[mode]["stayed_ispin"]
        and variants[mode]["stayed_same_halt"]
        and variants[mode]["unsupported_opcode_halt"]
        for mode in variants
    )
    same_diagnostic = (
        variants["native-off"]["after"]["virtual_pc"]
        == variants["native-on"]["after"]["virtual_pc"]
        and variants["native-off"]["after"]["opcode"]
        == variants["native-on"]["after"]["opcode"]
        and variants["native-off"]["after"]["halt"]
        == variants["native-on"]["after"]["halt"]
    )
    summary = {
        "result": "green" if same_stall else "red",
        "classification": (
            "interpreter-unimplemented-opcode"
            if same_stall
            else "native-or-interpreter-stall-differential"
        ),
        "scope": "retained fresh-campaign failure state; neutral 120-frame liveness comparison, not a fresh playthrough",
        "rom_sha256": sha256(args.rom.read_bytes()),
        "state": str(args.state),
        "mame": {
            "tick": args.mame_tick,
            "work_path": str(mame_work_path),
            "work_sha256": sha256(mame_work),
            "capture": mame_row,
        },
        "variants": strip_bytes(variants),
        "mame_work_equal_after": work_equal,
        "same_ispin_stall_native_off_on": same_stall,
        "checks": {
            "both_modes_stay_ispin": all(
                variants[mode]["stayed_ispin"] for mode in variants
            ),
            "both_modes_retain_dead_f800": all(
                variants[mode]["unsupported_opcode_halt"] for mode in variants
            ),
            "same_virtual_pc_opcode_halt": same_diagnostic,
            "native_off_gate_cleared": variants["native-off"]["before"]["gates"]["071A"] == 0,
            "native_on_gate_preserved": variants["native-on"]["before"]["gates"]["071A"] != 0,
            "mame_register_capture_present": all(
                key in mame_row for key in ("PC", "SR", "A7", "D0", "D7")
            ),
        },
    }
    (args.output / "summary.json").write_text(
        json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(
        json.dumps(
            {
                "result": summary["result"],
                "classification": summary["classification"],
                "same_ispin_stall_native_off_on": same_stall,
                "mame_work_equal_after": work_equal,
            },
            sort_keys=True,
        )
    )
    return 0 if summary["result"] == "green" else 1


if __name__ == "__main__":
    raise SystemExit(main())
