#!/usr/bin/env python3
"""Capture natural calls into the guarded $000CE4 sprite renderer.

The table-convention native body sees the real 68K return followed by CE4's
seven argument words.  Pausing only after a natural execution hook exposes the
source frame, coordinates, output cursor, and capacity without injecting a
call or changing game memory.  This is checkpointed diagnostic evidence, not
performance or fps evidence.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
from collections import Counter
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
DEFAULT_STATE = (
    ROOT / "build/playability-20260720/111a-table-active-cold-boot-v1/final.mss"
)
ENTRY = 0x94FA00
BODY_END = 0x94FD56


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--rom", type=Path, default=ROOT / "build/interp.sfc")
    parser.add_argument("--state", type=Path, default=DEFAULT_STATE)
    parser.add_argument("--nexen", type=Path, default=DEFAULT_NEXEN)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--calls", type=int, default=40)
    parser.add_argument("--port", type=int, default=7802)
    parser.add_argument(
        "--input-buttons",
        type=lambda value: int(value, 0),
        default=0,
        help="Hold this Nexen port-0 mask while capturing (for example 0x82 for Right+B).",
    )
    return parser.parse_args()


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


def le16(data: bytes) -> int:
    return int.from_bytes(data, "little")


def le32(data: bytes) -> int:
    return int.from_bytes(data, "little")


def be_words(data: bytes) -> list[int]:
    return [
        int.from_bytes(data[index : index + 2], "big")
        for index in range(0, len(data), 2)
    ]


def read_68k(m: McpSession, address: int, length: int) -> bytes:
    address &= 0xFFFFFF
    if address < 0x080000 and address + length <= 0x080000:
        bank = 0xC1 + (address >> 16)
        return bytes(
            m.read_memory("snesMemory", (bank << 16) | (address & 0xFFFF), length)
        )
    if 0xF00000 <= address and address + length <= 0xF10000:
        return bytes(m.read_memory("snesMemory", 0x400000 | (address & 0xFFFF), length))
    return b""


def capture_call(
    m: McpSession, index: int, attempt: int
) -> tuple[dict[str, object] | None, dict[str, object] | None]:
    hook = m.add_exec_hook(ENTRY, cpu_type="Sa1")
    m.drain_notifications(timeout=0.05)
    hit = m.run_until(max_frames=60, hook_handle=hook)
    m.pause()
    m.remove_hook(hook)
    if (hit or {}).get("reason") != "hookFired":
        raise RuntimeError(f"CE4 call {index}: entry did not fire: {hit!r}")

    cpu = dict(m.get_cpu_state("Sa1"))
    native_pc = ((int(cpu.get("k", 0)) << 16) | int(cpu.get("pc", 0))) & 0xFFFFFF
    regs = bytes(m.read_memory("Sa1Memory", 0x0000, 0x40))
    sp = le32(regs[0x3C:0x40]) & 0xFFFFFF
    if not (ENTRY <= native_pc < BODY_END):
        return None, {
            "attempt": attempt,
            "reason": "entry_completed_before_pause",
            "native_pc": f"{native_pc:06X}",
            "sp": f"{sp:06X}",
        }
    if not 0xF00000 <= sp <= 0xF0FFEE:
        return None, {
            "attempt": attempt,
            "reason": "stack_out_of_range",
            "native_pc": f"{native_pc:06X}",
            "sp": f"{sp:06X}",
        }

    raw_frame = bytes(m.read_memory("snesMemory", 0x400000 | (sp & 0xFFFF), 18))
    words = be_words(raw_frame)
    return_pc = ((words[0] << 16) | words[1]) & 0xFFFFFF
    args = words[2:]
    source = ((args[4] << 16) | args[5]) & 0xFFFFFF
    header_bytes = read_68k(m, source, 4)
    header = be_words(header_bytes) if len(header_bytes) == 4 else []
    rows = header[0] + 1 if len(header) == 2 and header[0] < 0x20 else None
    columns = header[1] + 1 if len(header) == 2 and header[1] < 0x20 else None
    shape_words = rows * columns if rows is not None and columns is not None else None
    source_bytes = (
        read_68k(m, source, 4 + 2 * shape_words) if shape_words is not None else b""
    )
    tiles = be_words(source_bytes[4:]) if source_bytes else []
    return {
        "index": index,
        "attempt": attempt,
        "tick": le16(bytes(m.read_memory("Sa1Memory", 0x0760, 2))),
        "cycles": int(cpu["cycleCount"]),
        "native_pc_when_paused": f"{native_pc:06X}",
        "sp": f"{sp:06X}",
        "return_pc": f"{return_pc:06X}",
        "args": [f"{word:04X}" for word in args],
        "cursor": args[0],
        "attribute": args[1],
        "screen_x": args[2],
        "screen_y": args[3],
        "source": f"{source:06X}",
        "capacity_minus_one": args[6],
        "source_header": [f"{word:04X}" for word in header],
        "rows": rows,
        "columns": columns,
        "shape_words": shape_words,
        "nonzero_tiles": sum(tile != 0 for tile in tiles),
        "source_sha256": hashlib.sha256(source_bytes).hexdigest()
        if source_bytes
        else None,
    }, None


def main() -> int:
    args = parse_args()
    if args.calls <= 0:
        raise SystemExit("--calls must be positive")
    rom = args.rom.resolve()
    state = args.state.resolve()
    nexen = args.nexen.resolve()
    output = args.output.resolve()
    for label, path in (("ROM", rom), ("state", state), ("Nexen", nexen)):
        if not path.is_file() or path.stat().st_size == 0:
            raise SystemExit(f"{label} missing or empty: {path}")
    if output.exists():
        raise SystemExit(f"refusing existing output: {output}")
    output.mkdir(parents=True)
    os.environ["DOTNET_ROOT"] = "/home/chad/.dotnet10"
    os.environ["PATH"] = "/home/chad/.dotnet10:" + os.environ.get("PATH", "")

    calls: list[dict[str, object]] = []
    misses: list[dict[str, object]] = []
    with McpSession(
        rom=rom,
        mesen=nexen,
        cwd=ROOT,
        port=args.port,
        boot_wait=8.0,
        socket_timeout=120.0,
        stderr_log=output / "nexen.stderr.log",
    ) as m:
        m.pause()
        m.load_state(state)
        m.pause()
        m.tool(
            "set_input",
            {"port": 0, "buttons": args.input_buttons, "hold": True},
        )
        attempt = 0
        while len(calls) < args.calls and attempt < args.calls * 20:
            call, miss = capture_call(m, len(calls), attempt)
            attempt += 1
            if miss is not None:
                misses.append(miss)
                print(json.dumps({"event": "miss", **miss}, sort_keys=True), flush=True)
                continue
            assert call is not None
            calls.append(call)
            print(json.dumps({"event": "call", **call}, sort_keys=True), flush=True)
        if len(calls) < args.calls:
            raise RuntimeError(
                f"captured only {len(calls)}/{args.calls} CE4 calls after {attempt} attempts"
            )

    signatures = Counter(
        (
            str(call["source"]),
            str(call["source_sha256"]),
            tuple(call["source_header"]),  # type: ignore[arg-type]
            int(call["capacity_minus_one"]),
        )
        for call in calls
    )
    summary = {
        "scope": "paused natural CE4 call capture; not fps",
        "project_commit": git_value("rev-parse", "HEAD"),
        "project_status": git_value("status", "--porcelain=v1").splitlines(),
        "rom": str(rom),
        "rom_sha256": sha256(rom),
        "state": str(state),
        "state_sha256": sha256(state),
        "nexen": str(nexen),
        "nexen_sha256": sha256(nexen),
        "input_buttons": args.input_buttons,
        "input_transport": "nexen_port0_manual_4016",
        "call_count": len(calls),
        "miss_count": len(misses),
        "signatures": [
            {
                "source": key[0],
                "source_sha256": key[1],
                "source_header": list(key[2]),
                "capacity_minus_one": key[3],
                "count": count,
            }
            for key, count in signatures.most_common()
        ],
        "calls": calls,
        "misses": misses,
    }
    (output / "summary.json").write_text(
        json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(
        json.dumps(
            {
                "event": "summary",
                "call_count": len(calls),
                "miss_count": len(misses),
                "unique_signatures": len(signatures),
                "summary": str(output / "summary.json"),
            },
            sort_keys=True,
        ),
        flush=True,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
