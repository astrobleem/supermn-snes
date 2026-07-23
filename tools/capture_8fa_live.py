#!/usr/bin/env python3
"""Capture organic $0008FA table-call arguments from a Nexen checkpoint.

The native escape uses the existing table-call convention: the caller return is
already at (A7), and the descriptor pointer is the long at 4(A7).  ``run_until``
pauses atomically at the real bank-$94 execution hook, so the captured stack and
register state are coherent.  This is checkpoint diagnostics, not fps evidence.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
import time
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, "/home/chad/Mesen2/python")

import mesen_mcp.session as _session

_session.validate_mesen_build = lambda *_args, **_kwargs: None
from mesen_mcp import McpSession


DEFAULT_ROM = ROOT / "build/interp.sfc"
DEFAULT_STATE = (
    ROOT
    / "build/playability-20260720/96a-start-transition-checkpoint/post_start.mss"
)
DEFAULT_NEXEN = Path(
    "/mnt/sdc1/Nexen-r5-20260712/"
    "bin/linux-x64/Release/linux-x64/publish/Nexen"
)
DEFAULT_ARCADE = ROOT / "data/superman_m68k.bin"
DEFAULT_OUTPUT = ROOT / "build/capture-8fa-live.jsonl"
ENTRY_NATIVE = 0x94AD98
ENTRY_NEXT = ENTRY_NATIVE + 2  # rep #$30 is the first complete instruction.
SPIN = bytes.fromhex("80fe")   # bra -2, temporary debugger-only capture loop.


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def git_value(*args: str) -> str:
    try:
        return subprocess.check_output(
            ["git", *args], cwd=ROOT, text=True, stderr=subprocess.DEVNULL
        ).strip()
    except Exception:
        return "unknown"


def configure_dotnet(executable: Path) -> None:
    root = "/home/chad/.dotnet10" if executable.name == "Nexen" else "/home/chad/.dotnet8"
    other = "/home/chad/.dotnet8" if executable.name == "Nexen" else "/home/chad/.dotnet10"
    os.environ["DOTNET_ROOT"] = root
    current = [
        item
        for item in os.environ.get("PATH", "").split(":")
        if item and item not in (root, other)
    ]
    os.environ["PATH"] = ":".join([root, other, *current])


def be16(data: bytes) -> int:
    return int.from_bytes(data, "big")


def be32(data: bytes) -> int:
    return int.from_bytes(data, "big")


def parse_descriptor(image: bytes, address: int) -> dict[str, int | str]:
    if not 0 <= address <= len(image) - 10:
        return {"error": f"descriptor ${address:08X} is outside the arcade image"}
    count = be16(image[address : address + 2])
    longs = count + 1
    end = address + 10 + longs * 4
    if end > len(image):
        return {
            "error": (
                f"descriptor ${address:08X} payload ends at ${end:08X}, "
                "outside the arcade image"
            )
        }
    payload = image[address + 10 : end]
    return {
        "count_word": count,
        "long_count": longs,
        "destination": f"{be32(image[address + 2 : address + 6]):08X}",
        "or_mask": f"{be32(image[address + 6 : address + 10]):08X}",
        "payload_bytes": len(payload),
        "payload_sha256": hashlib.sha256(payload).hexdigest(),
        "descriptor_end": f"{end:08X}",
    }


def emit(stream, event: str, **fields) -> None:
    row = {"event": event, "time": time.time(), **fields}
    line = json.dumps(row, sort_keys=True)
    print(line, flush=True)
    stream.write(line + "\n")
    stream.flush()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--rom", type=Path, default=DEFAULT_ROM)
    parser.add_argument("--state", type=Path, default=DEFAULT_STATE)
    parser.add_argument("--nexen", type=Path, default=DEFAULT_NEXEN)
    parser.add_argument("--arcade", type=Path, default=DEFAULT_ARCADE)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--calls", type=int, default=3)
    parser.add_argument("--port", type=int, default=7589)
    parser.add_argument("--max-frames", type=int, default=1200)
    args = parser.parse_args()

    if args.calls < 1:
        raise SystemExit("--calls must be positive")
    paths = [args.rom, args.state, args.nexen, args.arcade]
    for path in paths:
        if not path.is_file():
            raise SystemExit(f"required file not found: {path}")
    if args.output.exists():
        raise SystemExit(f"output already exists: {args.output}")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    arcade = args.arcade.read_bytes()
    if len(arcade) != 512 * 1024:
        raise SystemExit(f"expected a 512 KiB arcade image, got {len(arcade)} bytes")

    configure_dotnet(args.nexen)
    stderr_log = args.output.with_suffix(".stderr.log")
    with args.output.open("x", encoding="utf-8") as output:
        emit(
            output,
            "provenance",
            scope="organic checkpoint argument capture; not fps",
            project_commit=git_value("rev-parse", "HEAD"),
            project_status=git_value("status", "--short").splitlines(),
            rom=str(args.rom.resolve()),
            rom_sha256=sha256(args.rom),
            state=str(args.state.resolve()),
            state_sha256=sha256(args.state),
            nexen=str(args.nexen.resolve()),
            nexen_sha256=sha256(args.nexen),
            arcade_sha256=sha256(args.arcade),
            runtime_pokes=[
                {
                    "address": f"{ENTRY_NATIVE:06X}",
                    "bytes": SPIN.hex(),
                    "purpose": "freeze each $08FA entry before its first instruction",
                },
                {
                    "address": f"{ENTRY_NEXT:06X}",
                    "bytes": SPIN.hex(),
                    "purpose": "hand off safely between consecutive entry captures",
                },
            ],
            entry_native=f"{ENTRY_NATIVE:06X}",
        )
        with McpSession(
            rom=args.rom.resolve(),
            mesen=args.nexen.resolve(),
            cwd=ROOT,
            port=args.port,
            boot_wait=8.0,
            socket_timeout=180.0,
            stderr_log=stderr_log,
        ) as session:
            session.pause()
            session.load_state(args.state.resolve())
            session.pause()
            original_entry = session.read_memory("snesMemory", ENTRY_NATIVE, 2)
            original_next = session.read_memory("snesMemory", ENTRY_NEXT, 2)
            session.write_memory("snesMemory", ENTRY_NATIVE, SPIN.hex())
            if session.read_memory("snesMemory", ENTRY_NATIVE, 2) != SPIN:
                raise RuntimeError("Nexen rejected the temporary entry capture loop")
            emit(
                output,
                "capture_patch",
                entry_original=original_entry.hex(),
                next_original=original_next.hex(),
            )

            entry_hook = session.add_exec_hook(ENTRY_NATIVE, cpu_type="Sa1")
            try:
                for index in range(args.calls):
                    hit = session.run_until(
                        max_frames=args.max_frames, hook_handle=entry_hook
                    )
                    if (hit or {}).get("reason") != "hookFired":
                        raise RuntimeError(
                            f"call {index}: did not reach ${ENTRY_NATIVE:06X}: {hit!r}"
                        )
                    session.pause()
                    state = session.get_cpu_state("Sa1")
                    raw_regs = session.read_memory("Sa1Memory", 0x00, 0x40)
                    regs = [
                        int.from_bytes(raw_regs[offset : offset + 4], "little")
                        for offset in range(0, 0x40, 4)
                    ]
                    a5 = regs[13]
                    a7 = regs[15]
                    stack = session.read_memory(
                        "snesMemory", 0x400000 + (a7 & 0xFFFF), 12
                    )
                    descriptor = be32(stack[4:8])
                    or_value = session.read_memory(
                        "snesMemory", 0x400000 + ((a5 + 0x1B12) & 0xFFFF), 4
                    )
                    emit(
                        output,
                        "call",
                        index=index,
                        frame=int(state.get("frameCount", 0)),
                        sa1_cycles=int(state["cycleCount"]),
                        native_pc=(
                            f"{int(state['k']) & 0xFF:02X}"
                            f"{int(state['pc']) & 0xFFFF:04X}"
                        ),
                        a5=f"{a5:08X}",
                        a7=f"{a7:08X}",
                        stack_hex=stack.hex(),
                        caller_return=f"{be32(stack[:4]):08X}",
                        descriptor=f"{descriptor:08X}",
                        or_target_before=or_value.hex(),
                        descriptor_fields=parse_descriptor(arcade, descriptor),
                    )
                    if index + 1 == args.calls:
                        break

                    # Double-buffer the debugger loop.  First freeze at the
                    # instruction after REP while restoring the entry bytes;
                    # then restore that instruction and arm the entry loop for
                    # the next call.  At no point can asynchronous hook delivery
                    # run past an unarmed consecutive $08FA entry.
                    session.write_memory("snesMemory", ENTRY_NEXT, SPIN.hex())
                    session.write_memory(
                        "snesMemory", ENTRY_NATIVE, original_entry.hex()
                    )
                    session.remove_hook(entry_hook)
                    next_hook = session.add_exec_hook(ENTRY_NEXT, cpu_type="Sa1")
                    advanced = session.run_until(
                        max_frames=1, hook_handle=next_hook
                    )
                    if (advanced or {}).get("reason") != "hookFired":
                        raise RuntimeError(
                            f"call {index}: failed to hand off at "
                            f"${ENTRY_NEXT:06X}: {advanced!r}"
                        )
                    session.pause()
                    session.write_memory("snesMemory", ENTRY_NATIVE, SPIN.hex())
                    session.write_memory(
                        "snesMemory", ENTRY_NEXT, original_next.hex()
                    )
                    session.remove_hook(next_hook)
                    entry_hook = session.add_exec_hook(
                        ENTRY_NATIVE, cpu_type="Sa1"
                    )
            finally:
                session.pause()
                session.write_memory("snesMemory", ENTRY_NATIVE, original_entry.hex())
                session.write_memory("snesMemory", ENTRY_NEXT, original_next.hex())
                session.remove_hook(entry_hook)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
