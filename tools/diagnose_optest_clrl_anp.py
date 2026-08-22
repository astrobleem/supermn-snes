#!/usr/bin/env python3
"""Preserve a focused failed TESTFLAG single-step for CLR.L (A0)+.

This is a local interpreter micro-diagnostic.  It creates a disposable TESTFLAG
ROM with opcode $4298 at the optest slot, runs one requested vector, and writes
only compact hook/cpu/trace/state artifacts.
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
sys.path.insert(0, str(ROOT / "tools"))
sys.path.insert(0, "/home/chad/Mesen2/python")

import mesen_mcp.session as _session

_session.validate_mesen_build = lambda *_args, **_kwargs: None
from mesen_mcp import McpSession

import optest


DEFAULT_NEXEN = Path(
    "/mnt/sdc1/Nexen-r5-20260712/bin/linux-x64/Release/linux-x64/publish/Nexen"
)


HOOKS = {
    "move_dispatch_check": 0x00E124,
    "op_clr_g": 0x00FA73,
    "ea_resolve": 0x00B699,
    "ea_write": 0x00B8E9,
    "writelong": 0x00A2B4,
    "store_vid_long": 0x00F915,
    "map_snes": 0x00F800,
    "shadow_dirty_publish": 0x9EDE20,
    "ms_shadow_return": 0x00F846,
    "inext": 0x00D0F7,
    "idone": 0x00D11E,
    "idone_test": 0x00D12B,
    "test_idle": 0x00D12E,
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--rom", type=Path, default=Path("build/interp.sfc"))
    parser.add_argument("--nexen", type=Path, default=DEFAULT_NEXEN)
    parser.add_argument("--port", type=int, default=7651)
    parser.add_argument("--a0", type=lambda value: int(value, 0), default=optest.OPND)
    parser.add_argument("--frames", type=int, default=120)
    parser.add_argument("--stop-at", choices=sorted(HOOKS), help="pause at this hook instead of running the full step window")
    parser.add_argument("--park-at", choices=sorted(HOOKS), help="patch the disposable test ROM to BRA -2 at this hook")
    parser.add_argument("--park-address", type=lambda value: int(value, 0), help="patch the disposable test ROM to BRA -2 at this CPU address")
    return parser.parse_args()


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def configure_dotnet(path: Path) -> None:
    root = "/home/chad/.dotnet10" if path.name == "Nexen" else "/home/chad/.dotnet8"
    other = "/home/chad/.dotnet8" if root.endswith("dotnet10") else "/home/chad/.dotnet10"
    os.environ["DOTNET_ROOT"] = root
    current = [
        item
        for item in os.environ.get("PATH", "").split(":")
        if item and item not in (root, other)
    ]
    os.environ["PATH"] = ":".join([root, other, *current])


def le16(data: bytes) -> int:
    return int.from_bytes(data, "little")


def cpu_address(cpu: dict[str, Any]) -> int:
    return ((int(cpu.get("k", 0)) & 0xFF) << 16) | (int(cpu.get("pc", 0)) & 0xFFFF)


def drain_hook_rows(m: McpSession) -> list[dict[str, Any]]:
    rows = []
    for note in m.drain_notifications(timeout=0.05):
        if note.get("method") != "notifications/mesen/hookFired":
            continue
        params = note.get("params")
        if isinstance(params, dict):
            rows.append(dict(params))
    return rows


def snapshot(m: McpSession) -> dict[str, Any]:
    snes = dict(m.get_cpu_state("Snes"))
    sa1 = dict(m.get_cpu_state("Sa1"))
    pcblk = bytes(m.read_memory("Sa1Memory", 0x0040, 4))
    dp = bytes(m.read_memory("Sa1Memory", 0x0000, 0x0100))
    sp = int(sa1.get("sp", 0)) & 0xFFFF
    stack_start = max(0, sp - 0x40)
    stack_len = min(0x100, 0x800 - stack_start)
    return {
        "emulator": dict(m.get_state()),
        "snes_cpu": snes,
        "sa1_cpu": sa1,
        "snes_pc": cpu_address(snes),
        "sa1_pc": cpu_address(sa1),
        "pc68k": le16(pcblk[0:2]) | (le16(pcblk[2:4]) << 16),
        "a0": le16(dp[0x20:0x22]) | (le16(dp[0x22:0x24]) << 16),
        "halt": le16(dp[0x4E:0x50]),
        "go": le16(dp[0xA0:0xA2]),
        "dp_0000_00ff": dp.hex(),
        "sa1_stack_window": {
            "start": stack_start,
            "sp": sp,
            "bytes": bytes(m.read_memory("Sa1Memory", stack_start, stack_len)).hex(),
        },
        "sa1_trace": m.trace_log(count=128, cpu_type="Sa1"),
        "sa1_disassembly": m.disassemble(cpu_address(sa1), count=32, cpu_type="Sa1"),
    }


def main() -> int:
    args = parse_args()
    args.rom = args.rom.resolve()
    args.nexen = args.nexen.resolve()
    args.output = args.output.resolve()
    if args.output.exists():
        raise SystemExit(f"output already exists: {args.output}")
    args.output.mkdir(parents=True)
    if not args.rom.is_file():
        raise FileNotFoundError(args.rom)
    if not args.nexen.is_file():
        raise FileNotFoundError(args.nexen)
    configure_dotnet(args.nexen)

    test_sfc = Path(optest._make_test_sfc([0x4298]))
    park_address = HOOKS[args.park_at] if args.park_at else args.park_address
    if park_address is not None:
        data = bytearray(test_sfc.read_bytes())
        address = park_address
        if (address >> 16) == 0 and 0x8000 <= (address & 0xFFFF) <= 0xFFFF:
            lo = (address & 0xFFFF) - 0x8000
            offsets = (lo, lo + 0x8000)
        else:
            bank = (address >> 16) & 0xFF
            pc = address & 0xFFFF
            offsets = (0x200000 + (bank - 0x80) * 0x8000 + (pc - 0x8000),)
        for offset in offsets:
            data[offset:offset + 2] = b"\x80\xFE"
        test_sfc.write_bytes(data)
    test_copy = args.output / "clrl-anp-testflag.sfc"
    shutil.copy2(test_sfc, test_copy)
    result: dict[str, Any] = {
        "scope": "TESTFLAG CLR.L (A0)+ one-step diagnostic; not gameplay evidence",
        "base_rom": str(args.rom),
        "base_rom_sha256": sha256(args.rom),
        "test_rom": str(test_copy),
        "test_rom_sha256": sha256(test_copy),
        "nexen": str(args.nexen),
        "a0": args.a0,
        "frames": args.frames,
        "hooks": HOOKS,
    }
    try:
        with McpSession(
            rom=test_sfc,
            mesen=args.nexen,
            cwd=ROOT,
            port=args.port,
            boot_wait=3.0,
            socket_timeout=120.0,
            stderr_log=args.output / "emulator.stderr.log",
        ) as m:
            optest._prepare_interp_session(m)
            vector = optest.Vec({"A0": args.a0}, ccr=optest.ccr_bits(x=1), opnd=b"\x12\x34\x56\x78")
            m.write_memory(optest.DP_SPACE, 0x00, optest._regblk(vector).hex())
            pc = optest.INTERP_CODE_68K
            m.write_memory(
                optest.DP_SPACE,
                0x40,
                bytes([pc & 0xFF, (pc >> 8) & 0xFF, (pc >> 16) & 0xFF, (pc >> 24) & 0xFF]).hex(),
            )
            for address, value in ((0x60, 0), (0x6E, 0), (0x70, 0), (0x72, 0), (0xA2, 1)):
                m.write_memory(optest.DP_SPACE, address, bytes([value, 0]).hex())
            m.write_memory(optest.DP_SPACE, 0x7C, b"\x07\x00".hex())
            m.write_memory(optest.OPND_SPACE, optest.OPND_ADDR, vector.opnd.hex())
            handles: dict[int, str] = {}
            for label, address in HOOKS.items():
                handles[m.add_exec_hook(address, cpu_type="Sa1")] = label
            drain_hook_rows(m)
            m.write_memory(optest.DP_SPACE, 0x4E, "0000")
            m.write_memory(optest.DP_SPACE, 0xA0, "0100")
            events: list[dict[str, Any]] = []
            if args.stop_at:
                stop_handle = next(handle for handle, label in handles.items() if label == args.stop_at)
                result["run_until"] = dict(m.run_until(max_frames=args.frames, hook_handle=stop_handle))
                for row in drain_hook_rows(m):
                    row["label"] = handles.get(int(row.get("handle", -1)), "unknown")
                    events.append(row)
            else:
                for frame in range(1, args.frames + 1):
                    m.run_frames(1)
                    for row in drain_hook_rows(m):
                        row["label"] = handles.get(int(row.get("handle", -1)), "unknown")
                        events.append(row)
                    halt = le16(bytes(m.read_memory(optest.DP_SPACE, 0x4E, 2)))
                    if halt:
                        result["completed_frame"] = frame
                        break
            result["events"] = events[:512]
            result["event_count_retained"] = len(events)
            result["hook_diag"] = dict(m.hook_diag())
            result["final"] = snapshot(m)
            screenshot_response = m.take_screenshot(format="path")
            screenshot = args.output / "clrl-anp.png"
            shutil.copy2(Path(screenshot_response["path"]), screenshot)
            state_path = args.output / "clrl-anp.mss"
            save_response = m.save_state(state_path.resolve())
            result["artifacts"] = {
                "screenshot": {"path": str(screenshot), "sha256": sha256(screenshot), "response": screenshot_response},
                "state": {"path": str(state_path), "sha256": sha256(state_path), "response": save_response},
            }
    finally:
        try:
            test_sfc.unlink()
        except FileNotFoundError:
            pass

    result_path = args.output / "results.json"
    result_path.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
    final = result["final"]
    print(
        json.dumps(
            {
                "completed_frame": result.get("completed_frame"),
                "event_count": result["event_count_retained"],
                "final_sa1_pc": final["sa1_pc"],
                "final_pc68k": final["pc68k"],
                "final_a0": final["a0"],
                "halt": final["halt"],
                "results": str(result_path),
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
