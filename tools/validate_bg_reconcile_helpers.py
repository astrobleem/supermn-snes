#!/usr/bin/env python3
"""Differentially validate production BG promote/revert helper semantics.

This is a synthetic checkpointed helper gate, not FPS evidence.  It invokes
the exact production RTS helpers with controlled accepted/candidate planes and
checks both compact-list and full-image directions byte for byte.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
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
RETURN_HOOK = 0x9EE600
STACK_POINTER = 0x0700
RETURN_MINUS_ONE = 0xE5FF
SMALL_OFFSETS = (0x0000, 0x000A, 0x0100, 0x01FE, 0x03FE)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--rom", type=Path, required=True)
    parser.add_argument("--state", type=Path, required=True)
    parser.add_argument("--symbols", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--nexen", type=Path, default=DEFAULT_NEXEN)
    parser.add_argument("--port", type=int, default=7696)
    return parser.parse_args()


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def symbol_address(path: Path, name: str) -> int:
    pattern = re.compile(r"^([0-9A-Fa-f]{2}):([0-9A-Fa-f]{4})\s+(\S+)$")
    for line in path.read_text(encoding="utf-8").splitlines():
        match = pattern.match(line.strip())
        if match and match.group(3) == name:
            return (0x9E << 16) | int(match.group(2), 16)
    raise SystemExit(f"missing symbol {name} in {path}")


def pattern(multiplier: int, bias: int) -> bytes:
    return bytes((index * multiplier + bias) & 0xFF for index in range(0x0400))


def mismatch(expected: bytes, observed: bytes) -> dict[str, object]:
    offsets = [
        index
        for index, (left, right) in enumerate(zip(expected, observed))
        if left != right
    ]
    return {
        "mismatch_count": len(offsets),
        "first_offsets": offsets[:16],
        "expected_sha256": hashlib.sha256(expected).hexdigest(),
        "observed_sha256": hashlib.sha256(observed).hexdigest(),
    }


def write(m: McpSession, address: int, data: bytes) -> None:
    m.write_memory("snesMemory", address, data.hex())


def run_case(
    m: McpSession,
    state: Path,
    entry: int,
    name: str,
    direction: str,
    full: bool,
) -> dict[str, object]:
    m.pause()
    m.load_state(state)
    m.pause()

    baseline_code = pattern(3, 7)
    baseline_color = pattern(5, 11)
    if full:
        candidate_code = pattern(7, 19)
        candidate_color = pattern(11, 23)
        manifest_length = 0xFFFE
        offsets: tuple[int, ...] = ()
    else:
        candidate_code_array = bytearray(baseline_code)
        candidate_color_array = bytearray(baseline_color)
        for index, offset in enumerate(SMALL_OFFSETS):
            candidate_code_array[offset : offset + 2] = bytes(
                (0xA0 + index, 0x30 + index)
            )
            candidate_color_array[offset : offset + 2] = bytes(
                (0x50 + index, 0xC0 + index)
            )
        candidate_code = bytes(candidate_code_array)
        candidate_color = bytes(candidate_color_array)
        manifest_length = len(SMALL_OFFSETS) * 2
        offsets = SMALL_OFFSETS

    write(m, 0x410200, baseline_code)
    write(m, 0x410600, baseline_color)
    write(m, 0x410A00, candidate_code)
    write(m, 0x410E00, candidate_color)
    write(m, 0x41013A, manifest_length.to_bytes(2, "little"))
    if offsets:
        write(
            m,
            0x411A00,
            b"".join(offset.to_bytes(2, "little") for offset in offsets),
        )

    # RTS pulls low/high from S+1/S+2 and increments the stored PC.  Rejoin the
    # long-running production OBJ scan so the non-pausing hook has ample time
    # to stop the emulator before any unrelated epilogue can execute.
    m.write_memory(
        "Sa1Memory",
        STACK_POINTER + 1,
        RETURN_MINUS_ONE.to_bytes(2, "little").hex(),
    )
    hook = m.add_exec_hook(RETURN_HOOK, cpu_type="Sa1")
    m.drain_notifications(timeout=0.02)
    m.tool(
        "set_cpu_state",
        {
            "cpuType": "Sa1",
            "pc": entry & 0xFFFF,
            "k": entry >> 16,
            "a": 0,
            "x": 0,
            "y": 0,
            "sp": STACK_POINTER,
            "d": 0,
            "dbr": 0x41,
            "ps": 0x04,
            "emulationMode": False,
        },
    )
    hit = m.run_until(max_frames=1, hook_handle=hook)
    m.pause()
    m.remove_hook(hook)
    if (hit or {}).get("reason") != "hookFired":
        raise RuntimeError(f"{name}: helper return hook did not fire: {hit!r}")

    observed_baseline_code = bytes(m.read_memory("snesMemory", 0x410200, 0x0400))
    observed_baseline_color = bytes(m.read_memory("snesMemory", 0x410600, 0x0400))
    observed_candidate_code = bytes(m.read_memory("snesMemory", 0x410A00, 0x0400))
    observed_candidate_color = bytes(m.read_memory("snesMemory", 0x410E00, 0x0400))
    if direction == "promote":
        expected_baseline_code = candidate_code
        expected_baseline_color = candidate_color
        expected_candidate_code = candidate_code
        expected_candidate_color = candidate_color
    else:
        expected_baseline_code = baseline_code
        expected_baseline_color = baseline_color
        expected_candidate_code = baseline_code
        expected_candidate_color = baseline_color

    comparisons = {
        "baseline_code": mismatch(expected_baseline_code, observed_baseline_code),
        "baseline_color": mismatch(expected_baseline_color, observed_baseline_color),
        "candidate_code": mismatch(expected_candidate_code, observed_candidate_code),
        "candidate_color": mismatch(expected_candidate_color, observed_candidate_color),
    }
    green = all(item["mismatch_count"] == 0 for item in comparisons.values())
    return {
        "name": name,
        "direction": direction,
        "representation": "full" if full else "compact-list",
        "entry": f"{entry:06X}",
        "manifest_length": manifest_length,
        "offsets": list(offsets),
        "comparisons": comparisons,
        "green": green,
    }


def main() -> int:
    args = parse_args()
    paths = (args.rom, args.state, args.symbols, args.nexen)
    for path in paths:
        if not path.is_file() or path.stat().st_size == 0:
            raise SystemExit(f"missing or empty input: {path}")
    if args.output.exists():
        raise SystemExit(f"refusing existing output: {args.output}")
    args.output.mkdir(parents=True)
    os.environ["DOTNET_ROOT"] = "/home/chad/.dotnet10"
    os.environ["PATH"] = "/home/chad/.dotnet10:" + os.environ.get("PATH", "")

    entries = {
        "promote": symbol_address(args.symbols, "rmb_bg_promote"),
        "revert": symbol_address(args.symbols, "rmb_bg_revert"),
    }
    cases: list[dict[str, object]] = []
    with McpSession(
        rom=args.rom.resolve(),
        mesen=args.nexen.resolve(),
        cwd=ROOT,
        port=args.port,
        boot_wait=8.0,
        socket_timeout=120.0,
        stderr_log=args.output / "nexen.stderr.log",
    ) as m:
        for direction in ("promote", "revert"):
            for full in (False, True):
                name = f"{direction}-{'full' if full else 'compact'}"
                case = run_case(
                    m,
                    args.state.resolve(),
                    entries[direction],
                    name,
                    direction,
                    full,
                )
                cases.append(case)
                print(json.dumps({"event": "case", **case}, sort_keys=True), flush=True)

    result = {
        "scope": "synthetic checkpointed production BG helper equivalence; not fps",
        "result": "green" if all(case["green"] for case in cases) else "red",
        "rom": str(args.rom.resolve()),
        "rom_sha256": sha256(args.rom),
        "state": str(args.state.resolve()),
        "state_sha256": sha256(args.state),
        "symbols": str(args.symbols.resolve()),
        "symbols_sha256": sha256(args.symbols),
        "nexen": str(args.nexen.resolve()),
        "nexen_sha256": sha256(args.nexen),
        "entries": {name: f"{address:06X}" for name, address in entries.items()},
        "cases": cases,
    }
    target = args.output / "results.json"
    target.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
    print(
        json.dumps(
            {"event": "summary", "result": result["result"], "results": str(target)},
            sort_keys=True,
        ),
        flush=True,
    )
    return 0 if result["result"] == "green" else 2


if __name__ == "__main__":
    raise SystemExit(main())
