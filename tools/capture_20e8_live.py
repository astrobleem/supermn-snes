#!/usr/bin/env python3
"""Atomically capture organic post-prologue $0020E8 calls.

The bank-$00 lowering has already built its LINK/MOVEM frame when it reaches
the guarded helper at $9D:A003.  A temporary two-byte BRA loop parks each call
before the helper changes any emulated state.  This is checkpoint diagnostics,
not FPS or playability evidence.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import time
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, "/home/chad/Mesen2/python")

import mesen_mcp.session as _session

_session.validate_mesen_build = lambda *_args, **_kwargs: None
from mesen_mcp import McpSession


DEFAULT_NEXEN = Path(
    "/mnt/sdc1/Nexen-r5-20260712/"
    "bin/linux-x64/Release/linux-x64/publish/Nexen"
)
ENTRY = 0x9DA003
NEXT = ENTRY + 2
CLAMP = 0x00F5A3
SPIN = bytes.fromhex("80fe")
REG_NAMES = [f"D{i}" for i in range(8)] + [f"A{i}" for i in range(8)]


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def be16(data: bytes, offset: int) -> int:
    return int.from_bytes(data[offset : offset + 2], "big")


def be32(data: bytes, offset: int) -> int:
    return int.from_bytes(data[offset : offset + 4], "big")


def emit(stream, row: dict) -> None:
    line = json.dumps(row, sort_keys=True)
    print(line, flush=True)
    stream.write(line + "\n")
    stream.flush()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--rom", required=True, type=Path)
    parser.add_argument("--state", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--nexen", type=Path, default=DEFAULT_NEXEN)
    parser.add_argument("--port", type=int, default=7631)
    parser.add_argument("--calls", type=int, default=64)
    parser.add_argument(
        "--warmup-ticks",
        type=int,
        default=0,
        help=(
            "Advance this many real $00:F5A3 game-tick boundaries after "
            "loading the checkpoint, before installing the temporary entry loop."
        ),
    )
    parser.add_argument("--input-buttons", type=lambda value: int(value, 0))
    args = parser.parse_args()
    for path in (args.rom, args.state, args.nexen):
        if not path.is_file():
            parser.error(f"missing required input: {path}")
    if args.calls < 1:
        parser.error("--calls must be positive")
    if args.warmup_ticks < 0:
        parser.error("--warmup-ticks cannot be negative")
    if args.output.exists():
        parser.error(f"output already exists: {args.output}")
    args.output.parent.mkdir(parents=True, exist_ok=True)

    os.environ["DOTNET_ROOT"] = "/home/chad/.dotnet10"
    os.environ["PATH"] = "/home/chad/.dotnet10:" + os.environ.get("PATH", "")
    with args.output.open("x", encoding="utf-8") as output:
        emit(
            output,
            {
                "event": "provenance",
                "scope": "organic post-prologue $20E8 capture; not fps",
                "rom": str(args.rom.resolve()),
                "rom_sha256": sha256(args.rom),
                "state": str(args.state.resolve()),
                "state_sha256": sha256(args.state),
                "nexen": str(args.nexen.resolve()),
                "nexen_sha256": sha256(args.nexen),
                "input_buttons": args.input_buttons,
                "warmup_ticks": args.warmup_ticks,
                "entry": f"{ENTRY:06X}",
                "runtime_pokes": [
                    {"address": f"{ENTRY:06X}", "bytes": SPIN.hex()},
                    {"address": f"{NEXT:06X}", "bytes": SPIN.hex()},
                ],
            },
        )
        with McpSession(
            rom=args.rom.resolve(),
            mesen=args.nexen.resolve(),
            cwd=ROOT,
            port=args.port,
            boot_wait=8.0,
            socket_timeout=180.0,
            stderr_log=args.output.with_suffix(".stderr.log"),
        ) as session:
            session.pause()
            session.load_state(args.state.resolve())
            session.pause()
            if args.input_buttons is not None:
                session.tool(
                    "set_input",
                    {"port": 0, "buttons": args.input_buttons, "hold": True},
                )
            if args.warmup_ticks:
                warmup_hook = session.add_exec_hook(CLAMP, cpu_type="Sa1")
                session.drain_notifications(timeout=0.05)
                warmup_started = time.monotonic()
                observed = 0
                session.resume()
                try:
                    while observed < args.warmup_ticks:
                        for notification in session.drain_notifications(timeout=0.25):
                            if notification.get("method") != "notifications/mesen/hookFired":
                                continue
                            params = notification.get("params", {})
                            if int(params.get("handle", -1)) == warmup_hook:
                                observed += 1
                        if time.monotonic() - warmup_started > 180.0:
                            raise TimeoutError(
                                f"warmup stopped at {observed}/{args.warmup_ticks} ticks"
                            )
                finally:
                    session.pause()
                    session.remove_hook(warmup_hook)
                emit(
                    output,
                    {
                        "event": "warmup_finished",
                        "requested_ticks": args.warmup_ticks,
                        "observed_tick_hooks": observed,
                        "wall_seconds": time.monotonic() - warmup_started,
                    },
                )
            original_entry = bytes(session.read_memory("snesMemory", ENTRY, 2))
            original_next = bytes(session.read_memory("snesMemory", NEXT, 2))
            session.write_memory("snesMemory", ENTRY, SPIN.hex())
            if bytes(session.read_memory("snesMemory", ENTRY, 2)) != SPIN:
                raise RuntimeError("Nexen rejected the temporary $20E8 loop")
            entry_hook = session.add_exec_hook(ENTRY, cpu_type="Sa1")
            try:
                for index in range(args.calls):
                    hit = session.run_until(max_frames=1200, hook_handle=entry_hook)
                    if (hit or {}).get("reason") != "hookFired":
                        raise RuntimeError(f"call {index}: entry did not fire: {hit!r}")
                    session.pause()
                    cpu = session.get_cpu_state("Sa1")
                    raw = bytes(session.read_memory("Sa1Memory", 0, 0xB0))
                    regs = {
                        name: int.from_bytes(raw[i * 4 : i * 4 + 4], "little")
                        for i, name in enumerate(REG_NAMES)
                    }
                    frame = regs["A6"] & 0xFFFF
                    stack = bytes(
                        session.read_memory("snesMemory", 0x400000 + frame, 0x20)
                    )
                    emit(
                        output,
                        {
                            "event": "call",
                            "index": index,
                            "tick": be16(
                                bytes(session.read_memory("snesMemory", 0x401C56, 2)),
                                0,
                            ),
                            "sa1_cycles": int(cpu.get("cycleCount", 0)),
                            "registers": {
                                name: f"{value:08X}" for name, value in regs.items()
                            },
                            "frame_hex": stack.hex(),
                            "arguments": {
                                "saved_a6": f"{be32(stack, 0):08X}",
                                "caller_return": f"{be32(stack, 4):08X}",
                                "video_offset": f"{be16(stack, 8):04X}",
                                "fill_word": f"{be16(stack, 10):04X}",
                                "row_adjust": f"{be16(stack, 12):04X}",
                                "row_coordinate": f"{be16(stack, 14):04X}",
                                "descriptor": f"{be32(stack, 16):08X}",
                                "fill_count": f"{be16(stack, 20):04X}",
                            },
                            "scratch": {
                                f"{off:02X}": f"{int.from_bytes(raw[off:off+2], 'little'):04X}"
                                for off in range(0, 0xB0, 2)
                            },
                        },
                    )
                    if index + 1 == args.calls:
                        break

                    session.write_memory("snesMemory", NEXT, SPIN.hex())
                    session.write_memory("snesMemory", ENTRY, original_entry.hex())
                    session.remove_hook(entry_hook)
                    next_hook = session.add_exec_hook(NEXT, cpu_type="Sa1")
                    advanced = session.run_until(max_frames=2, hook_handle=next_hook)
                    if (advanced or {}).get("reason") != "hookFired":
                        raise RuntimeError(
                            f"call {index}: handoff at ${NEXT:06X} failed: {advanced!r}"
                        )
                    session.pause()
                    session.write_memory("snesMemory", ENTRY, SPIN.hex())
                    session.write_memory("snesMemory", NEXT, original_next.hex())
                    session.remove_hook(next_hook)
                    entry_hook = session.add_exec_hook(ENTRY, cpu_type="Sa1")
            finally:
                session.pause()
                session.write_memory("snesMemory", ENTRY, original_entry.hex())
                session.write_memory("snesMemory", NEXT, original_next.hex())
                session.remove_hook(entry_hook)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
