#!/usr/bin/env python3
"""Capture live $025110 stage-2 fast-path misses atomically.

A debugger-only loop parks the SA-1 at the helper's shared fallback before the
byte-retained stage-2 implementation can make its first write.  The capture
therefore contains the exact records and scratch state that caused the miss.
This is checkpointed diagnostics for extending the semantic fast path, not FPS.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
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
OUTER_BASE = 0x3A54
INNER_BASE = 0x3A74
RECORD_SIZE = 0x10
INNER_COUNT = 32
SPIN = bytes.fromhex("80fe")
REG_NAMES = [f"D{i}" for i in range(8)] + [f"A{i}" for i in range(8)]


def symbol_address(path: Path, mapped_bank: int, name: str) -> int:
    for raw in path.read_text(encoding="utf-8-sig").splitlines():
        fields = raw.split()
        if len(fields) >= 2 and fields[1] == name:
            return (mapped_bank << 16) | int(fields[0].split(":", 1)[1], 16)
    raise RuntimeError(f"missing symbol {name!r} in {path}")


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def be16(data: bytes, offset: int) -> int:
    return int.from_bytes(data[offset : offset + 2], "big")


def signed16(value: int) -> int:
    return value - 0x10000 if value & 0x8000 else value


def decode_record(raw: bytes, address: int) -> dict[str, object]:
    words = [be16(raw, offset) for offset in range(0, RECORD_SIZE, 2)]
    return {
        "address": f"F0{address:04X}",
        "words": [f"{word:04X}" for word in words],
        "active": signed16(words[0]),
        "edges": [signed16(word) for word in words[1:5]],
        "type": f"{words[5]:04X}",
        "response": raw[0x0C:0x0E].hex(),
        "e": signed16(words[7]),
    }


def registers(session: McpSession) -> dict[str, str]:
    raw = bytes(session.read_memory("Sa1Memory", 0, 0x40))
    return {
        name: f"{int.from_bytes(raw[index * 4 : index * 4 + 4], 'little'):08X}"
        for index, name in enumerate(REG_NAMES)
    }


def scratch(session: McpSession) -> dict[str, str]:
    raw = bytes(session.read_memory("Sa1Memory", 0, 0xB0))
    return {
        f"{offset:02X}": f"{int.from_bytes(raw[offset : offset + 2], 'little'):04X}"
        for offset in range(0, 0xB0, 2)
    }


def records(session: McpSession) -> list[dict[str, object]]:
    start = 0x400000 + OUTER_BASE
    size = (2 + INNER_COUNT) * RECORD_SIZE
    raw = bytes(session.read_memory("snesMemory", start, size))
    return [
        decode_record(
            raw[index * RECORD_SIZE : (index + 1) * RECORD_SIZE],
            OUTER_BASE + index * RECORD_SIZE,
        )
        for index in range(2 + INNER_COUNT)
    ]


def emit(stream, row: dict[str, object]) -> None:
    line = json.dumps(row, sort_keys=True)
    print(line, flush=True)
    stream.write(line + "\n")
    stream.flush()


def run_to(session: McpSession, address: int, max_frames: int = 180) -> dict:
    hook = session.add_exec_hook(address, cpu_type="Sa1")
    session.drain_notifications(timeout=0.05)
    try:
        result = session.run_until(max_frames=max_frames, hook_handle=hook)
        session.pause()
        if (result or {}).get("reason") != "hookFired":
            raise RuntimeError(f"hook ${address:06X} did not fire: {result!r}")
        return session.get_cpu_state("Sa1")
    finally:
        session.remove_hook(hook)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--rom", required=True, type=Path)
    parser.add_argument("--state", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--nexen", type=Path, default=DEFAULT_NEXEN)
    parser.add_argument("--port", type=int, default=7611)
    parser.add_argument("--calls", type=int, default=8)
    parser.add_argument("--input-buttons", type=lambda value: int(value, 0))
    args = parser.parse_args()
    for path in (args.rom, args.state, args.nexen):
        if not path.is_file():
            parser.error(f"missing required input: {path}")
    if args.calls < 1:
        parser.error("--calls must be positive")
    if args.output.exists():
        parser.error(f"output already exists: {args.output}")
    if args.input_buttons is not None and not 0 <= args.input_buttons <= 0xFFF:
        parser.error("--input-buttons must be a 12-bit mask")
    args.output.parent.mkdir(parents=True, exist_ok=True)

    stage2_entry = symbol_address(
        ROOT / "src/escbank7.sym", 0x9D, "h25110_stage2_try"
    )
    stage2_fallback = symbol_address(
        ROOT / "src/escbank7.sym", 0x9D, "h25s2_fallback"
    )
    generated_setup = symbol_address(
        ROOT / "src/escbank3.sym", 0x97, "h25110_stage2_generated_setup"
    )

    os.environ["DOTNET_ROOT"] = "/home/chad/.dotnet10"
    os.environ["PATH"] = "/home/chad/.dotnet10:" + os.environ.get("PATH", "")
    with args.output.open("x", encoding="utf-8") as output:
        emit(
            output,
            {
                "event": "provenance",
                "scope": "checkpointed atomic $25110 stage-2 miss capture; not fps",
                "rom": str(args.rom.resolve()),
                "rom_sha256": sha256(args.rom),
                "state": str(args.state.resolve()),
                "state_sha256": sha256(args.state),
                "nexen": str(args.nexen.resolve()),
                "nexen_sha256": sha256(args.nexen),
                "input_buttons": args.input_buttons,
                "hooks": {
                    "stage2_entry": f"{stage2_entry:06X}",
                    "stage2_fallback": f"{stage2_fallback:06X}",
                    "generated_setup": f"{generated_setup:06X}",
                },
                "runtime_pokes": [
                    {"address": f"{stage2_fallback:06X}", "bytes": SPIN.hex()},
                    {"address": f"{generated_setup:06X}", "bytes": SPIN.hex()},
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
            original_fallback = bytes(
                session.read_memory("snesMemory", stage2_fallback, len(SPIN))
            )
            original_generated = bytes(
                session.read_memory("snesMemory", generated_setup, len(SPIN))
            )
            session.write_memory("snesMemory", stage2_fallback, SPIN.hex())
            fallback_hook = session.add_exec_hook(stage2_fallback, cpu_type="Sa1")
            try:
                for index in range(args.calls):
                    hit = session.run_until(
                        max_frames=1200, hook_handle=fallback_hook
                    )
                    session.pause()
                    if (hit or {}).get("reason") != "hookFired":
                        raise RuntimeError(
                            f"capture {index}: fallback did not fire: {hit!r}"
                        )
                    fallback_cpu = session.get_cpu_state("Sa1")
                    fallback_tick = int.from_bytes(
                        bytes(session.read_memory("snesMemory", 0x401C56, 2)),
                        "big",
                    )
                    fallback_scratch = scratch(session)
                    native_x = int(fallback_cpu.get("x", 0)) & 0xFFFF
                    emit(
                        output,
                        {
                            "event": "call",
                            "index": index,
                            "fallback_tick": fallback_tick,
                            "fallback_cycles": int(fallback_cpu.get("cycleCount", 0)),
                            "fallback_native_x": f"{native_x:04X}",
                            "registers": registers(session),
                            "scratch": fallback_scratch,
                            "records_at_fallback": records(session),
                        },
                    )
                    if index + 1 == args.calls:
                        break

                    # Execute the original fallback into a separately parked
                    # generated setup, then restore both sites and re-arm the
                    # next organic miss without replaying this call.
                    session.write_memory("snesMemory", generated_setup, SPIN.hex())
                    session.write_memory(
                        "snesMemory", stage2_fallback, original_fallback.hex()
                    )
                    session.remove_hook(fallback_hook)
                    generated_hook = session.add_exec_hook(
                        generated_setup, cpu_type="Sa1"
                    )
                    advanced = session.run_until(
                        max_frames=8, hook_handle=generated_hook
                    )
                    session.pause()
                    if (advanced or {}).get("reason") != "hookFired":
                        raise RuntimeError(
                            f"capture {index}: generated handoff failed: {advanced!r}"
                        )
                    session.write_memory("snesMemory", stage2_fallback, SPIN.hex())
                    session.write_memory(
                        "snesMemory", generated_setup, original_generated.hex()
                    )
                    session.remove_hook(generated_hook)
                    fallback_hook = session.add_exec_hook(
                        stage2_fallback, cpu_type="Sa1"
                    )
            finally:
                session.pause()
                session.write_memory(
                    "snesMemory", stage2_fallback, original_fallback.hex()
                )
                session.write_memory(
                    "snesMemory", generated_setup, original_generated.hex()
                )
                session.remove_hook(fallback_hook)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
