#!/usr/bin/env python3
"""Capture natural $01F096 sprite-emitter entries from a gameplay checkpoint.

The native entries retain the real table-call return followed by seven 68K
argument words.  Stopping there exposes the exact arguments, source header, and
output capacity without injecting a call or changing game memory.  This is a
paused checkpoint diagnostic, not performance or FPS evidence.
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
    ROOT
    / "build/playability-20260720/111a-table-active-cold-boot-v1/final.mss"
)
def current_symbol(path: Path, bank: int, symbol: str) -> int:
    if not path.is_file():
        raise SystemExit(f"current layout symbols are required: {path}")
    for raw in path.read_text(encoding="utf-8-sig").splitlines():
        fields = raw.split()
        if len(fields) == 2 and fields[1] == symbol:
            return bank | int(fields[0].split(":", 1)[1], 16)
    raise SystemExit(f"{path}: missing {symbol}")


ENTRIES = (
    (
        "d96",
        current_symbol(ROOT / "src/escbank4.sym", 0x980000, "entry_d96t"),
        0x000D96,
    ),
    (
        "111a",
        current_symbol(ROOT / "src/escbank6.sym", 0x950000, "entry_111at"),
        0x00111A,
    ),
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--rom", type=Path, default=ROOT / "build/interp.sfc")
    parser.add_argument("--state", type=Path, default=DEFAULT_STATE)
    parser.add_argument("--nexen", type=Path, default=DEFAULT_NEXEN)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--calls-per-entry", type=int, default=24)
    parser.add_argument("--port", type=int, default=7662)
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
    return [int.from_bytes(data[index : index + 2], "big") for index in range(0, len(data), 2)]


def read_68k(m: McpSession, address: int, length: int) -> bytes:
    address &= 0xFFFFFF
    if address < 0x080000:
        bank = 0xC1 + (address >> 16)
        return bytes(
            m.read_memory("snesMemory", (bank << 16) | (address & 0xFFFF), length)
        )
    if 0xF00000 <= address <= 0xF0FFFF and address + length <= 0xF10000:
        return bytes(m.read_memory("snesMemory", 0x400000 | (address & 0xFFFF), length))
    return b""


def capture_call(
    m: McpSession,
    entry_name: str,
    entry_address: int,
    renderer: int,
    index: int,
    attempt: int,
) -> tuple[dict[str, object] | None, dict[str, object] | None]:
    hook = m.add_exec_hook(entry_address, cpu_type="Sa1")
    m.drain_notifications(timeout=0.05)
    hit = m.run_until(max_frames=60, hook_handle=hook)
    m.pause()
    m.remove_hook(hook)
    if (hit or {}).get("reason") != "hookFired":
        raise RuntimeError(f"{entry_name} call {index}: entry did not fire: {hit!r}")

    regs = bytes(m.read_memory("Sa1Memory", 0x0000, 0x40))
    sp = le32(regs[0x3C:0x40]) & 0xFFFFFF
    cpu = dict(m.get_cpu_state("Sa1"))
    native_pc = ((int(cpu.get("k", 0)) << 16) | int(cpu.get("pc", 0))) & 0xFFFFFF
    if not 0xF00000 <= sp <= 0xF0FFEE:
        return None, {
            "entry": entry_name,
            "attempt": attempt,
            "reason": "stack_out_of_range",
            "sp": f"{sp:06X}",
            "native_pc": f"{native_pc:06X}",
        }
    raw_frame = bytes(m.read_memory("snesMemory", 0x400000 | (sp & 0xFFFF), 18))
    frame_words = be_words(raw_frame)
    return_pc = ((frame_words[0] << 16) | frame_words[1]) & 0xFFFFFF
    if return_pc not in (0xFBDDE7, 0xFBE285):
        return None, {
            "entry": entry_name,
            "attempt": attempt,
            "reason": "entry_completed_before_pause",
            "sp": f"{sp:06X}",
            "native_pc": f"{native_pc:06X}",
            "observed_top": f"{return_pc:06X}",
        }
    args = frame_words[2:]
    source = ((args[4] << 16) | args[5]) & 0xFFFFFF
    source_bytes = read_68k(m, source, 0x0100)
    header = be_words(source_bytes[:4]) if len(source_bytes) >= 4 else []
    row_words = header[0] + 1 if len(header) == 2 and header[0] < 0x8000 else None
    column_words = header[1] + 1 if len(header) == 2 and header[1] < 0x8000 else None
    return {
        "entry": entry_name,
        "entry_address": f"{entry_address:06X}",
        "index": index,
        "attempt": attempt,
        "tick": le16(m.read_memory("Sa1Memory", 0x0760, 2)),
        "cycles": int(m.get_cpu_state("Sa1")["cycleCount"]),
        "native_pc_when_paused": f"{native_pc:06X}",
        "sp": f"{sp:06X}",
        "renderer": f"{renderer:06X}",
        "renderer_name": entry_name,
        "return_pc": f"{return_pc:06X}",
        "args": [f"{word:04X}" for word in args],
        "source": f"{source:06X}",
        "source_header": [f"{word:04X}" for word in header],
        "rows": row_words,
        "columns": column_words,
        "shape_words": row_words * column_words
        if row_words is not None and column_words is not None
        else None,
        "source_prefix_sha256": hashlib.sha256(source_bytes).hexdigest()
        if source_bytes
        else None,
    }, None


def main() -> int:
    args = parse_args()
    if args.calls_per_entry <= 0:
        raise SystemExit("--calls-per-entry must be positive")
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
        for entry_name, entry_address, renderer in ENTRIES:
            m.pause()
            m.load_state(state)
            m.pause()
            attempt = 0
            captured = 0
            while captured < args.calls_per_entry and attempt < args.calls_per_entry * 12:
                call, miss = capture_call(
                    m, entry_name, entry_address, renderer, captured, attempt
                )
                attempt += 1
                if miss is not None:
                    misses.append(miss)
                    print(json.dumps({"event": "miss", **miss}, sort_keys=True), flush=True)
                    continue
                assert call is not None
                calls.append(call)
                captured += 1
                print(json.dumps({"event": "call", **call}, sort_keys=True), flush=True)
            if captured < args.calls_per_entry:
                raise RuntimeError(
                    f"captured only {captured}/{args.calls_per_entry} {entry_name} calls "
                    f"after {attempt} attempts"
                )

    shape_counts = Counter(
        (
            str(call["entry"]),
            str(call["renderer"]),
            tuple(call["args"]),  # type: ignore[arg-type]
            tuple(call["source_header"]),  # type: ignore[arg-type]
        )
        for call in calls
    )
    renderer_counts = Counter(str(call["renderer"]) for call in calls)
    summary = {
        "scope": "paused natural sprite-emitter call capture; not fps",
        "project_commit": git_value("rev-parse", "HEAD"),
        "project_status": git_value("status", "--porcelain=v1").splitlines(),
        "rom": str(rom),
        "rom_sha256": sha256(rom),
        "state": str(state),
        "state_sha256": sha256(state),
        "nexen": str(nexen),
        "nexen_sha256": sha256(nexen),
        "calls_per_entry": args.calls_per_entry,
        "call_count": len(calls),
        "miss_count": len(misses),
        "renderer_counts": dict(sorted(renderer_counts.items())),
        "shape_counts": [
            {
                "entry": key[0],
                "renderer": key[1],
                "args": list(key[2]),
                "source_header": list(key[3]),
                "count": count,
            }
            for key, count in shape_counts.most_common()
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
                "renderer_counts": summary["renderer_counts"],
                "unique_shapes": len(shape_counts),
                "summary": str(output / "summary.json"),
            },
            sort_keys=True,
        ),
        flush=True,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
