#!/usr/bin/env python3
"""Capture live $CAF6/$CB9E native-entry inputs from a checkpointed lab run.

This is a diagnostic capture, not performance or correctness evidence.  It
pauses on the actual bank-$97 execution addresses and records the emulated
68K registers plus the A6 frame bytes that select the sprite-build paths.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import TextIO


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, "/home/chad/Mesen2/python")

import mesen_mcp.session as _session

_session.validate_mesen_build = lambda *_args, **_kwargs: None
from mesen_mcp import McpSession


DEFAULT_NEXEN = Path(
    "/mnt/sdc1/Nexen-r5-20260712/"
    "bin/linux-x64/Release/linux-x64/publish/Nexen"
)
DEFAULT_ROM = (
    ROOT
    / "build/playability-20260719/dma158-native-v3-nmi-lab/interp_vsync_lab.sfc"
)
DEFAULT_STATE = (
    ROOT
    / "build/playability-20260719/dma158-native-v3-cold-ordering-soak-1100/final.mss"
)
ENTRY_CAF6 = 0x97D800
ENTRY_CB9E = 0x97E800
RETURN_CB9E_FIRST_LOOP = 0x97DB16
RETURN_CAF6_CALLER = 0x99B741
REG_NAMES = [f"D{i}" for i in range(8)] + [f"A{i}" for i in range(8)]
SPIN = bytes.fromhex("80fe")  # bra -2, temporary debugger-only capture loop.


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--rom", type=Path, default=DEFAULT_ROM)
    parser.add_argument("--state", type=Path, default=DEFAULT_STATE)
    parser.add_argument("--nexen", type=Path, default=DEFAULT_NEXEN)
    parser.add_argument("--port", type=int, default=7494)
    parser.add_argument("--draws", type=int, default=5)
    parser.add_argument(
        "--entries",
        type=int,
        help="Capture this many complete CAF6 calls instead of nested CB9E entries.",
    )
    parser.add_argument(
        "--hook-address",
        type=lambda value: int(value, 0),
        help="Capture at an explicit SA-1 execution address (for guard diagnostics).",
    )
    parser.add_argument(
        "--captures",
        type=int,
        default=1,
        help="Number of explicit-address captures (used with --hook-address).",
    )
    parser.add_argument(
        "--atomic-captures",
        type=int,
        help=(
            "Atomically freeze and capture this many hcaf6_fast entries. "
            "Unlike a bare hook, this cannot sample after the hot SA-1 advances."
        ),
    )
    parser.add_argument(
        "--output",
        type=Path,
        help="Retain emitted JSONL at this new path as well as stdout.",
    )
    parser.add_argument(
        "--input-buttons",
        type=lambda value: int(value, 0),
        help="Hold this 12-bit Nexen controller mask after loading the state.",
    )
    return parser.parse_args()


def symbol_address(path: Path, mapped_bank: int, name: str) -> int:
    for raw in path.read_text(encoding="utf-8-sig").splitlines():
        fields = raw.split()
        if len(fields) >= 2 and fields[1] == name:
            return (mapped_bank << 16) | int(fields[0].split(":", 1)[1], 16)
    raise RuntimeError(f"missing symbol {name!r} in {path}")


def emit(output: TextIO | None, row: dict) -> None:
    line = json.dumps(row, sort_keys=True)
    print(line, flush=True)
    if output is not None:
        output.write(line + "\n")
        output.flush()


def registers(m: McpSession) -> dict[str, int]:
    raw = bytes(m.read_memory("Sa1Memory", 0, 0x40))
    return {
        name: int.from_bytes(raw[index * 4 : index * 4 + 4], "little")
        for index, name in enumerate(REG_NAMES)
    }


def hit(m: McpSession, address: int) -> None:
    hook = m.add_exec_hook(address, cpu_type="Sa1")
    m.drain_notifications(timeout=0.05)
    result = m.run_until(max_frames=120, hook_handle=hook)
    m.pause()
    m.remove_hook(hook)
    if (result or {}).get("reason") != "hookFired":
        raise RuntimeError(f"hook ${address:06X} did not fire: {result!r}")


def snapshot(m: McpSession, event: str, index: int | None = None) -> dict:
    regs = registers(m)
    a6 = regs["A6"]
    local = b""
    if a6 >> 16 == 0xF0:
        local = bytes(
            m.read_memory("snesMemory", 0x400000 + ((a6 - 0x80) & 0xFFFF), 0x100)
        )
    decoded = {}
    if local:
        def word(displacement: int) -> int:
            offset = 0x80 + displacement
            return int.from_bytes(local[offset : offset + 2], "big")

        def longword(displacement: int) -> int:
            offset = 0x80 + displacement
            return int.from_bytes(local[offset : offset + 4], "big")

        decoded = {
            "a2_ptr_m54": f"{longword(-0x54):08X}",
            "d6_select_m50": f"{word(-0x50):04X}",
            "mirror_byte_m24": f"{local[0x80 - 0x24]:02X}",
            "base_m22": f"{word(-0x22):04X}",
            "origin_m1e": f"{word(-0x1E):04X}",
            "d2_m1a": f"{word(-0x1A):04X}",
            "d7_m18": f"{word(-0x18):04X}",
            "d0sel_m16": f"{word(-0x16):04X}",
            "d1sel_m14": f"{word(-0x14):04X}",
            "a0_m12": f"{longword(-0x12):08X}",
            "compare_m4": f"{word(-0x04):04X}",
            "compare_m2": f"{word(-0x02):04X}",
            "a1_slots": [
                f"{longword(-0x38 + offset):08X}"
                for offset in range(0, 0x14, 4)
            ],
        }
    return {
        "event": event,
        "index": index,
        "caller_return": f"{m.read_u16(0x42, 'Sa1Memory'):04X}{m.read_u16(0x40, 'Sa1Memory'):04X}",
        "registers": {name: f"{value:08X}" for name, value in regs.items()},
        "a6_minus_80_hex": local.hex(),
        "frame": decoded,
        "ccr_words": {
            "c": m.read_u16(0x6E, "Sa1Memory"),
            "v": m.read_u16(0x72, "Sa1Memory"),
            "z": m.read_u16(0x60, "Sa1Memory"),
            "n": m.read_u16(0x70, "Sa1Memory"),
            "x": m.read_u16(0xA2, "Sa1Memory"),
        },
    }


def atomic_captures(
    m: McpSession,
    count: int,
    output: TextIO | None,
) -> None:
    if count < 1:
        raise ValueError("--atomic-captures must be positive")
    entry = symbol_address(ROOT / "src/escbank3.sym", 0x97, "hcaf6_fast")
    next_pc = entry + 2  # hcaf6_fast begins with the complete two-byte REP #$30.
    original_entry = bytes(m.read_memory("snesMemory", entry, 2))
    original_next = bytes(m.read_memory("snesMemory", next_pc, 2))
    m.write_memory("snesMemory", entry, SPIN.hex())
    if bytes(m.read_memory("snesMemory", entry, 2)) != SPIN:
        raise RuntimeError("Nexen rejected the temporary CAF6 entry capture loop")
    emit(
        output,
        {
            "event": "capture_patch",
            "scope": "checkpointed atomic argument capture; not fps",
            "entry": f"{entry:06X}",
            "entry_original": original_entry.hex(),
            "next": f"{next_pc:06X}",
            "next_original": original_next.hex(),
            "runtime_poke": SPIN.hex(),
        },
    )
    entry_hook = m.add_exec_hook(entry, cpu_type="Sa1")
    try:
        for index in range(count):
            result = m.run_until(max_frames=1200, hook_handle=entry_hook)
            if (result or {}).get("reason") != "hookFired":
                raise RuntimeError(
                    f"atomic CAF6 capture {index} did not fire: {result!r}"
                )
            m.pause()
            cpu = m.get_cpu_state("Sa1")
            row = snapshot(m, "caf6_atomic_entry", index)
            row["native_pc"] = (
                f"{int(cpu.get('k', 0)) & 0xFF:02X}"
                f"{int(cpu.get('pc', 0)) & 0xFFFF:04X}"
            )
            row["sa1_cycles"] = int(cpu.get("cycleCount", 0))
            emit(output, row)
            if index + 1 == count:
                break

            # Let exactly the original REP execute into a second temporary
            # loop, then re-arm the entry loop before releasing the SA-1.
            m.write_memory("snesMemory", next_pc, SPIN.hex())
            m.write_memory("snesMemory", entry, original_entry.hex())
            m.remove_hook(entry_hook)
            next_hook = m.add_exec_hook(next_pc, cpu_type="Sa1")
            advanced = m.run_until(max_frames=8, hook_handle=next_hook)
            if (advanced or {}).get("reason") != "hookFired":
                # The temporary branch still makes the stop coherent even if
                # Nexen loses a hot hook notification.  Accept only proof that
                # the SA-1 is physically parked at the intended loop.
                m.pause()
                state = m.get_cpu_state("Sa1")
                parked = (
                    ((int(state.get("k", 0)) << 16) | int(state.get("pc", 0)))
                    & 0xFFFFFF
                )
                if parked != next_pc:
                    raise RuntimeError(
                        f"atomic CAF6 handoff {index} failed: {advanced!r}, "
                        f"parked=${parked:06X}"
                    )
            m.pause()
            m.write_memory("snesMemory", entry, SPIN.hex())
            m.write_memory("snesMemory", next_pc, original_next.hex())
            m.remove_hook(next_hook)
            entry_hook = m.add_exec_hook(entry, cpu_type="Sa1")
    finally:
        m.pause()
        m.write_memory("snesMemory", entry, original_entry.hex())
        m.write_memory("snesMemory", next_pc, original_next.hex())
        m.remove_hook(entry_hook)


def main() -> int:
    args = parse_args()
    if args.output is not None and args.output.exists():
        raise SystemExit(f"output already exists: {args.output}")
    if args.output is not None:
        args.output.parent.mkdir(parents=True, exist_ok=True)
    os.environ["DOTNET_ROOT"] = "/home/chad/.dotnet10"
    os.environ["PATH"] = "/home/chad/.dotnet10:" + os.environ.get("PATH", "")
    output_context = (
        args.output.open("x", encoding="utf-8") if args.output is not None else None
    )
    try:
        with McpSession(
            rom=args.rom.resolve(),
            mesen=args.nexen.resolve(),
            cwd=ROOT,
            port=args.port,
            boot_wait=6.0,
            socket_timeout=180.0,
            stderr_log=(
                args.output.with_suffix(".stderr.log")
                if args.output is not None
                else ROOT / "build/playability-20260719/caf6-capture.stderr.log"
            ),
        ) as m:
            m.pause()
            m.load_state(args.state.resolve())
            m.pause()
            if args.input_buttons is not None:
                if not 0 <= args.input_buttons <= 0xFFF:
                    raise SystemExit("--input-buttons must be a 12-bit mask")
                m.tool(
                    "set_input",
                    {"port": 0, "buttons": args.input_buttons, "hold": True},
                )
            if args.atomic_captures is not None:
                atomic_captures(m, args.atomic_captures, output_context)
                return 0
            if args.hook_address is not None:
                for index in range(args.captures):
                    hit(m, args.hook_address)
                    emit(output_context, snapshot(m, "hook_capture", index))
                return 0
            hit(m, ENTRY_CAF6)
            emit(output_context, snapshot(m, "caf6_entry"))
            if args.entries:
                for index in range(1, args.entries):
                    hit(m, RETURN_CAF6_CALLER)
                    hit(m, ENTRY_CAF6)
                    emit(output_context, snapshot(m, "caf6_entry", index))
                return 0
            for index in range(args.draws):
                hit(m, ENTRY_CB9E)
                emit(output_context, snapshot(m, "cb9e_entry", index))
                hit(m, RETURN_CB9E_FIRST_LOOP)
    finally:
        if output_context is not None:
            output_context.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
