#!/usr/bin/env python3
"""Atomically capture organic $01E7C0 common-helper cold edges.

The debugger-only BRA loops park the SA-1 before the bank-$97 cold trampoline
can enter the generated bank-$98 record body.  Captures include the live 68K
register file, helper scratch, current list slot, object record, and relevant
globals.  This is checkpoint diagnostics, not FPS or correctness evidence.
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
SPIN = bytes.fromhex("80fe")
REG_NAMES = [f"D{i}" for i in range(8)] + [f"A{i}" for i in range(8)]


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def symbol_address(path: Path, mapped_bank: int, name: str) -> int:
    for raw in path.read_text(encoding="utf-8-sig").splitlines():
        fields = raw.split()
        if len(fields) >= 2 and fields[1] == name:
            return (mapped_bank << 16) | int(fields[0].split(":", 1)[1], 16)
    raise RuntimeError(f"missing symbol {name!r} in {path}")


def be16(data: bytes, offset: int) -> int:
    return int.from_bytes(data[offset : offset + 2], "big")


def be32(data: bytes, offset: int) -> int:
    return int.from_bytes(data[offset : offset + 4], "big")


def dp16(data: bytes, offset: int) -> int:
    return int.from_bytes(data[offset : offset + 2], "little")


def signed16(value: int) -> int:
    return value - 0x10000 if value & 0x8000 else value


def emit(stream, row: dict) -> None:
    line = json.dumps(row, sort_keys=True)
    print(line, flush=True)
    stream.write(line + "\n")
    stream.flush()


def decode_capture(session: McpSession, index: int) -> dict:
    cpu = session.get_cpu_state("Sa1")
    dp = bytes(session.read_memory("Sa1Memory", 0, 0xB0))
    work = bytes(session.read_memory("snesMemory", 0x400000, 0x4000))
    regs = {
        name: int.from_bytes(dp[i * 4 : i * 4 + 4], "little")
        for i, name in enumerate(REG_NAMES)
    }
    obj_low = dp16(dp, 0x80)
    obj_high = dp16(dp, 0x82)
    obj = work[obj_low : obj_low + 0x70] if obj_high == 0x00F0 else b""
    camera_x = be16(work, 0x2A32)
    mode = be16(work, 0x2A4A)
    special_mask = work[0x3522]

    decoded: dict[str, object] = {}
    inferred = "global-or-pointer-guard"
    if len(obj) == 0x70:
        count = be16(obj, 0x0E)
        world_x = be16(obj, 0x2E)
        world_y = be16(obj, 0x32)
        a2 = be32(obj, 0x46)
        a3 = be32(obj, 0x4A)
        a4 = be32(obj, 0x4E)

        def subword(pointer: int, displacement: int) -> int | None:
            if pointer >> 16 != 0xF0:
                return None
            low = pointer & 0xFFFF
            if low + displacement + 2 > len(work):
                return None
            return be16(work, low + displacement)

        a2e = subword(a2, 0x0E)
        a3e = subword(a3, 0x0E)
        d1 = (world_x - camera_x) & 0xFFFF
        d2 = world_y
        sign_mismatch = bool((be16(obj, 0x36) ^ be16(obj, 0x3C)) & 0x8000)
        callback = be32(work, 0x3510 if be16(obj, 0x36) & 0x8000 else 0x3514)

        if any(obj[offset] != 0 for offset in (0x04, 0x66, 0x0A, 0x05)):
            inferred = "status-byte-guard"
        # The native steady arm decrements the word and must leave it
        # positive.  Input 0/1 belongs to the original animation-script arm;
        # only 2..$7FFF is eligible for the direct renderer path.
        elif not (2 <= count < 0x8000):
            inferred = "animation-count"
        elif a2e != 0:
            inferred = "a2-script-state"
        elif a3e != 0:
            inferred = "a3-script-state"
        elif sign_mismatch:
            inferred = "horizontal-sign"
        elif not (0x000C <= d1 < 0x0175):
            inferred = "horizontal-range"
        elif not (d2 < 0x00A1):
            inferred = "vertical-range"
        elif callback not in (0x00000D96, 0x0000111A):
            inferred = "callback"
        else:
            inferred = "post-guard-or-unclassified"

        decoded = {
            "status_bytes": {
                f"{offset:02X}": obj[offset]
                for offset in (0x04, 0x05, 0x06, 0x07, 0x08, 0x0A, 0x66)
            },
            "animation_count": f"{count:04X}",
            "frame_source": f"{be32(obj, 0x14):08X}",
            "sprite_count": f"{be16(obj, 0x1A):04X}",
            "world_x": f"{world_x:04X}",
            "world_y": f"{world_y:04X}",
            "world_y_signed": signed16(world_y),
            "latch_36": f"{be16(obj, 0x36):04X}",
            "latch_3c": f"{be16(obj, 0x3C):04X}",
            "a2": f"{a2:08X}",
            "a3": f"{a3:08X}",
            "a4": f"{a4:08X}",
            "a2_e": None if a2e is None else f"{a2e:04X}",
            "a3_e": None if a3e is None else f"{a3e:04X}",
            "d1": f"{d1:04X}",
            "d1_signed": signed16(d1),
            "d2": f"{d2:04X}",
            "callback": f"{callback:08X}",
        }

    list_low = dp16(dp, 0x24)
    list_high = dp16(dp, 0x26)
    list_pointer = (
        be32(work, list_low)
        if list_high == 0x00F0 and list_low + 4 <= len(work)
        else None
    )
    return {
        "event": "cold_edge",
        "index": index,
        "native_pc": (
            f"{int(cpu.get('k', 0)) & 0xFF:02X}"
            f"{int(cpu.get('pc', 0)) & 0xFFFF:04X}"
        ),
        # The accumulator and status at the shared cold trampoline identify
        # which immediately preceding guard delegated.  Keep these raw: this
        # is debugger evidence, not emulated-68K architectural state.
        "native_cpu": {
            name: f"{int(cpu.get(name, 0)):X}"
            for name in ("a", "x", "y", "sp", "d", "dbr", "k", "pc", "ps")
            if name in cpu
        },
        "sa1_cycles": int(cpu.get("cycleCount", 0)),
        "registers": {name: f"{value:08X}" for name, value in regs.items()},
        "helper": {
            "d5": f"{dp16(dp, 0x14):04X}",
            "list_cursor": f"{list_high:04X}{list_low:04X}",
            "list_pointer": None if list_pointer is None else f"{list_pointer:08X}",
            "object_pointer": f"{obj_high:04X}{obj_low:04X}",
            "a2_low": f"{dp16(dp, 0x84):04X}",
            "a3_low": f"{dp16(dp, 0x86):04X}",
            "a4_low": f"{dp16(dp, 0x88):04X}",
            "d1": f"{dp16(dp, 0x8A):04X}",
            "d2": f"{dp16(dp, 0x8C):04X}",
            "camera_or_delta": f"{dp16(dp, 0x8E):04X}",
        },
        "globals": {
            "camera_x": f"{camera_x:04X}",
            "mode": f"{mode:04X}",
            "special_mask": f"{special_mask:02X}",
            "callback_negative": f"{be32(work, 0x3510):08X}",
            "callback_positive": f"{be32(work, 0x3514):08X}",
        },
        "inferred_guard": inferred,
        "object": decoded,
        "object_hex": obj.hex(),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--rom", required=True, type=Path)
    parser.add_argument("--state", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--nexen", type=Path, default=DEFAULT_NEXEN)
    parser.add_argument("--port", type=int, default=7613)
    parser.add_argument("--captures", type=int, default=12)
    parser.add_argument("--input-buttons", type=lambda value: int(value, 0))
    args = parser.parse_args()
    for path in (args.rom, args.state, args.nexen):
        if not path.is_file():
            parser.error(f"missing required input: {path}")
    if args.captures < 1:
        parser.error("--captures must be positive")
    if args.output.exists():
        parser.error(f"output already exists: {args.output}")
    if args.input_buttons is not None and not 0 <= args.input_buttons <= 0xFFF:
        parser.error("--input-buttons must be a 12-bit mask")
    args.output.parent.mkdir(parents=True, exist_ok=True)

    cold = symbol_address(ROOT / "src/escbank3.sym", 0x97, "h1e7c0_hot_cold")
    generated = symbol_address(
        ROOT / "src/escbank4.sym", 0x98, "L1e7c0_1e7cc"
    )
    os.environ["DOTNET_ROOT"] = "/home/chad/.dotnet10"
    os.environ["PATH"] = "/home/chad/.dotnet10:" + os.environ.get("PATH", "")
    with args.output.open("x", encoding="utf-8") as output:
        emit(
            output,
            {
                "event": "provenance",
                "scope": "checkpointed atomic $01E7C0 cold-edge capture; not fps",
                "rom": str(args.rom.resolve()),
                "rom_sha256": sha256(args.rom),
                "state": str(args.state.resolve()),
                "state_sha256": sha256(args.state),
                "nexen": str(args.nexen.resolve()),
                "nexen_sha256": sha256(args.nexen),
                "input_buttons": args.input_buttons,
                "cold_trampoline": f"{cold:06X}",
                "generated_reentry": f"{generated:06X}",
                "runtime_pokes": [
                    {"address": f"{cold:06X}", "bytes": SPIN.hex()},
                    {"address": f"{generated:06X}", "bytes": SPIN.hex()},
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
            original_cold = bytes(session.read_memory("snesMemory", cold, 2))
            original_generated = bytes(
                session.read_memory("snesMemory", generated, 2)
            )
            session.write_memory("snesMemory", cold, SPIN.hex())
            if bytes(session.read_memory("snesMemory", cold, 2)) != SPIN:
                raise RuntimeError("Nexen rejected the temporary cold-edge loop")
            cold_hook = session.add_exec_hook(cold, cpu_type="Sa1")
            try:
                for index in range(args.captures):
                    hit = session.run_until(max_frames=1200, hook_handle=cold_hook)
                    if (hit or {}).get("reason") != "hookFired":
                        raise RuntimeError(
                            f"capture {index}: cold edge did not fire: {hit!r}"
                        )
                    session.pause()
                    emit(output, decode_capture(session, index))
                    if index + 1 == args.captures:
                        break

                    # Execute the original four-byte JML into a temporary loop
                    # at the generated re-entry, then re-arm the cold edge.
                    session.write_memory("snesMemory", generated, SPIN.hex())
                    session.write_memory("snesMemory", cold, original_cold.hex())
                    session.remove_hook(cold_hook)
                    generated_hook = session.add_exec_hook(generated, cpu_type="Sa1")
                    advanced = session.run_until(
                        max_frames=8, hook_handle=generated_hook
                    )
                    if (advanced or {}).get("reason") != "hookFired":
                        session.pause()
                        state = session.get_cpu_state("Sa1")
                        parked = (
                            (int(state.get("k", 0)) << 16)
                            | int(state.get("pc", 0))
                        ) & 0xFFFFFF
                        if parked != generated:
                            raise RuntimeError(
                                f"capture {index}: handoff failed: {advanced!r}, "
                                f"parked=${parked:06X}"
                            )
                    session.pause()
                    session.write_memory("snesMemory", cold, SPIN.hex())
                    session.write_memory(
                        "snesMemory", generated, original_generated.hex()
                    )
                    session.remove_hook(generated_hook)
                    cold_hook = session.add_exec_hook(cold, cpu_type="Sa1")
            finally:
                session.pause()
                session.write_memory("snesMemory", cold, original_cold.hex())
                session.write_memory(
                    "snesMemory", generated, original_generated.hex()
                )
                session.remove_hook(cold_hook)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
