#!/usr/bin/env python3
"""Atomically capture organic table-convention $00111A arguments.

The temporary two-instruction loop parks the SA-1 at the real $95:A700 entry,
before REP or any emulated state change.  This is checkpoint diagnostics, not
FPS or cold-boot evidence.
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
ENTRY = 0x95A700
NEXT = ENTRY + 2
SPIN = bytes.fromhex("80fe")
REG_NAMES = [f"D{i}" for i in range(8)] + [f"A{i}" for i in range(8)]


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def be16(data: bytes) -> int:
    return int.from_bytes(data, "big")


def be32(data: bytes) -> int:
    return int.from_bytes(data, "big")


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
    parser.add_argument("--port", type=int, default=7601)
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

    os.environ["DOTNET_ROOT"] = "/home/chad/.dotnet10"
    os.environ["PATH"] = "/home/chad/.dotnet10:" + os.environ.get("PATH", "")
    with args.output.open("x", encoding="utf-8") as output:
        emit(
            output,
            {
                "event": "provenance",
                "scope": "checkpointed atomic $111A argument capture; not fps",
                "rom": str(args.rom.resolve()),
                "rom_sha256": sha256(args.rom),
                "state": str(args.state.resolve()),
                "state_sha256": sha256(args.state),
                "nexen": str(args.nexen.resolve()),
                "nexen_sha256": sha256(args.nexen),
                "input_buttons": args.input_buttons,
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
            original_entry = bytes(session.read_memory("snesMemory", ENTRY, 2))
            original_next = bytes(session.read_memory("snesMemory", NEXT, 2))
            session.write_memory("snesMemory", ENTRY, SPIN.hex())
            if bytes(session.read_memory("snesMemory", ENTRY, 2)) != SPIN:
                raise RuntimeError("Nexen rejected the temporary $111A loop")
            entry_hook = session.add_exec_hook(ENTRY, cpu_type="Sa1")
            try:
                for index in range(args.calls):
                    hit = session.run_until(max_frames=1200, hook_handle=entry_hook)
                    if (hit or {}).get("reason") != "hookFired":
                        raise RuntimeError(f"call {index}: entry did not fire: {hit!r}")
                    session.pause()
                    cpu = session.get_cpu_state("Sa1")
                    raw = bytes(session.read_memory("Sa1Memory", 0, 0x40))
                    regs = {
                        name: int.from_bytes(raw[i * 4 : i * 4 + 4], "little")
                        for i, name in enumerate(REG_NAMES)
                    }
                    a7 = regs["A7"]
                    if a7 >> 16 != 0xF0:
                        raise RuntimeError(f"call {index}: A7 is not work RAM: ${a7:08X}")
                    stack = bytes(
                        session.read_memory(
                            "snesMemory", 0x400000 + (a7 & 0xFFFF), 20
                        )
                    )
                    emit(
                        output,
                        {
                            "event": "call",
                            "index": index,
                            "native_pc": (
                                f"{int(cpu.get('k', 0)) & 0xFF:02X}"
                                f"{int(cpu.get('pc', 0)) & 0xFFFF:04X}"
                            ),
                            "sa1_cycles": int(cpu.get("cycleCount", 0)),
                            "registers": {
                                name: f"{value:08X}" for name, value in regs.items()
                            },
                            "stack_hex": stack.hex(),
                            "arguments": {
                                "caller_return": f"{be32(stack[0:4]):08X}",
                                "output_offset": f"{be16(stack[4:6]):04X}",
                                "x_bias": f"{be16(stack[8:10]):04X}",
                                "initial_y": f"{be16(stack[10:12]):04X}",
                                "source": f"{be32(stack[12:16]):08X}",
                                "capacity_minus_one": f"{be16(stack[16:18]):04X}",
                            },
                        },
                    )
                    if index + 1 == args.calls:
                        break

                    session.write_memory("snesMemory", NEXT, SPIN.hex())
                    session.write_memory("snesMemory", ENTRY, original_entry.hex())
                    session.remove_hook(entry_hook)
                    next_hook = session.add_exec_hook(NEXT, cpu_type="Sa1")
                    advanced = session.run_until(max_frames=8, hook_handle=next_hook)
                    if (advanced or {}).get("reason") != "hookFired":
                        session.pause()
                        parked_state = session.get_cpu_state("Sa1")
                        parked = (
                            (int(parked_state.get("k", 0)) << 16)
                            | int(parked_state.get("pc", 0))
                        ) & 0xFFFFFF
                        if parked != NEXT:
                            raise RuntimeError(
                                f"call {index}: handoff failed: {advanced!r}, "
                                f"parked=${parked:06X}"
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
