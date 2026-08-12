#!/usr/bin/env python3
"""Validate cumulative BG producer-list and exact manifest semantics.

This is a synthetic checkpointed SA-1 helper gate, not FPS evidence.  It
exercises the exact production helpers with controlled shared-memory images:

* producer ranges append cumulatively and fail closed on overflow/unknown data;
* duplicate producer offsets collapse to one final manifest entry;
* candidate code/color planes match the live values for every published cell;
* clean, first-image, empty, and unknown-list states retain the old paths.
* the first C0BC image preserves its raw baseline while selecting the immutable
  prepared payload; other first images remain raw/full and clear stale tokens.
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
STACK_POINTER = 0x0700
APPENDER_RETURN = 0x9DA800


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--rom", type=Path, required=True)
    parser.add_argument("--state", type=Path, required=True)
    parser.add_argument("--esc7-symbols", type=Path, required=True)
    parser.add_argument("--esc8-symbols", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--nexen", type=Path, default=DEFAULT_NEXEN)
    parser.add_argument("--port", type=int, default=7984)
    return parser.parse_args()


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def symbol_address(path: Path, bank: int, name: str) -> int:
    pattern = re.compile(r"^[0-9A-Fa-f]{2}:([0-9A-Fa-f]{4})\s+(\S+)$")
    for line in path.read_text(encoding="utf-8").splitlines():
        match = pattern.match(line.strip())
        if match and match.group(2) == name:
            return (bank << 16) | int(match.group(1), 16)
    raise SystemExit(f"missing symbol {name} in {path}")


def write(m: McpSession, address: int, data: bytes) -> None:
    m.write_memory("snesMemory", address, data.hex())


def read(m: McpSession, address: int, length: int) -> bytes:
    return bytes(m.read_memory("snesMemory", address, length))


def u16(m: McpSession, address: int) -> int:
    return int.from_bytes(read(m, address, 2), "little")


def write_u16(m: McpSession, address: int, value: int) -> None:
    write(m, address, value.to_bytes(2, "little"))


def set_sa1(
    m: McpSession,
    address: int,
    *,
    a: int = 0,
    x: int = 0,
    dbr: int = 0x41,
) -> None:
    m.tool(
        "set_cpu_state",
        {
            "cpuType": "Sa1",
            "pc": address & 0xFFFF,
            "k": address >> 16,
            "a": a,
            "x": x,
            "y": 0,
            "sp": STACK_POINTER,
            "d": 0,
            "dbr": dbr,
            "ps": 0x04,
            "emulationMode": False,
        },
    )


def run_to_hook(
    m: McpSession,
    entry: int,
    target: int,
    *,
    a: int = 0,
    x: int = 0,
    dbr: int = 0x41,
    max_frames: int = 1,
) -> dict[str, object]:
    hook = m.add_exec_hook(target, cpu_type="Sa1")
    m.drain_notifications(timeout=0.02)
    set_sa1(m, entry, a=a, x=x, dbr=dbr)
    hit = m.run_until(max_frames=max_frames, hook_handle=hook)
    m.pause()
    m.remove_hook(hook)
    if (hit or {}).get("reason") != "hookFired":
        raise RuntimeError(
            f"helper ${entry:06X} did not reach ${target:06X}: {hit!r}"
        )
    return m.get_cpu_state("Sa1")


def call_appender(
    m: McpSession, entry: int, first: int, count: int
) -> dict[str, object]:
    # RTS pulls the low/high return word from S+1 and increments it.
    m.write_memory(
        "Sa1Memory",
        STACK_POINTER + 1,
        ((APPENDER_RETURN & 0xFFFF) - 1).to_bytes(2, "little").hex(),
    )
    # Organic native callers enter with DBR=$00.  The appender must select its
    # bank-$41 list explicitly and restore that caller-visible bank on return.
    return run_to_hook(
        m, entry, APPENDER_RETURN, a=count, x=first, dbr=0x00
    )


def appender_cases(
    m: McpSession, state: Path, entry: int
) -> list[dict[str, object]]:
    cases: list[dict[str, object]] = []

    m.load_state(state)
    m.pause()
    write_u16(m, 0x41014C, 0)
    write_u16(m, 0x41014E, 0)
    first_return = call_appender(m, entry, 0x0380, 0x0040)
    second_return = call_appender(m, entry, 0x0380, 0x001C)
    observed = [
        int.from_bytes(read(m, 0x411200 + offset, 2), "little")
        for offset in range(0, 0x00B8, 2)
    ]
    expected = list(range(0x0380, 0x0400, 2)) + list(
        range(0x0380, 0x03B8, 2)
    )
    cumulative_green = (
        u16(m, 0x41014C) == 1
        and u16(m, 0x41014E) == 0x00B8
        and observed == expected
        and int(first_return.get("dbr", -1)) == 0
        and int(second_return.get("dbr", -1)) == 0
    )
    cases.append(
        {
            "name": "cumulative-overlap",
            "status": u16(m, 0x41014C),
            "length": u16(m, 0x41014E),
            "return_dbrs": [
                int(first_return.get("dbr", -1)),
                int(second_return.get("dbr", -1)),
            ],
            "list_sha256": hashlib.sha256(read(m, 0x411200, 0x00B8)).hexdigest(),
            "green": cumulative_green,
        }
    )

    m.load_state(state)
    m.pause()
    write_u16(m, 0x41014C, 1)
    write_u16(m, 0x41014E, 0x03FE)
    write(m, 0x4115FE, b"\xA5\x5A")
    overflow_return = call_appender(m, entry, 0x0000, 2)
    overflow_green = (
        u16(m, 0x41014C) == 0xFFFF
        and u16(m, 0x41014E) == 0x03FE
        and read(m, 0x4115FE, 2) == b"\x00\x00"
        and int(overflow_return.get("dbr", -1)) == 0
    )
    cases.append(
        {
            "name": "overflow-fails-closed",
            "status": u16(m, 0x41014C),
            "length": u16(m, 0x41014E),
            "return_dbr": int(overflow_return.get("dbr", -1)),
            "last_written_offset": u16(m, 0x4115FE),
            "green": overflow_green,
        }
    )

    m.load_state(state)
    m.pause()
    write_u16(m, 0x41014C, 0xFFFF)
    write_u16(m, 0x41014E, 0x0020)
    write(m, 0x411220, b"\xA5\x5A")
    unknown_return = call_appender(m, entry, 0x0200, 4)
    unknown_green = (
        u16(m, 0x41014C) == 0xFFFF
        and u16(m, 0x41014E) == 0x0020
        and read(m, 0x411220, 2) == b"\xA5\x5A"
        and int(unknown_return.get("dbr", -1)) == 0
    )
    cases.append(
        {
            "name": "unknown-remains-unknown",
            "status": u16(m, 0x41014C),
            "length": u16(m, 0x41014E),
            "return_dbr": int(unknown_return.get("dbr", -1)),
            "green": unknown_green,
        }
    )
    return cases


def pattern(multiplier: int, bias: int) -> bytes:
    return bytes((index * multiplier + bias) & 0xFF for index in range(0x0400))


def sparse_case(
    m: McpSession,
    state: Path,
    entry: int,
    done: int,
) -> dict[str, object]:
    m.load_state(state)
    m.pause()
    baseline_code = pattern(3, 7)
    baseline_color = pattern(5, 11)
    live_code = bytearray(baseline_code)
    live_color = bytearray(baseline_color)
    source_offsets = (0x0000, 0x000A, 0x0000, 0x0100, 0x000A, 0x03FE)
    changed_offsets = (0x0000, 0x0100, 0x03FE)
    for index, offset in enumerate(changed_offsets):
        live_code[offset : offset + 2] = bytes((0xA0 + index, 0x30 + index))
        live_color[offset : offset + 2] = bytes((0x50 + index, 0xC0 + index))

    write(m, 0x410200, baseline_code)
    write(m, 0x410600, baseline_color)
    write(m, 0x410A00, baseline_code)
    write(m, 0x410E00, baseline_color)
    write(m, 0x414800, bytes(live_code))
    write(m, 0x414C00, bytes(live_color))
    write(
        m,
        0x411200,
        b"".join(offset.to_bytes(2, "little") for offset in source_offsets),
    )
    write_u16(m, 0x410136, 1)
    write_u16(m, 0x410140, 1)
    write_u16(m, 0x410142, 0)
    write_u16(m, 0x41014C, 1)
    write_u16(m, 0x41014E, len(source_offsets) * 2)
    run_to_hook(m, entry, done)

    manifest_length = u16(m, 0x41013A)
    manifest = tuple(
        int.from_bytes(read(m, 0x411A00 + offset, 2), "little")
        for offset in range(0, manifest_length, 2)
    )
    observed_code = read(m, 0x410A00, 0x0400)
    observed_color = read(m, 0x410E00, 0x0400)
    green = (
        manifest == changed_offsets
        and manifest_length == len(changed_offsets) * 2
        and observed_code == bytes(live_code)
        and observed_color == bytes(live_color)
        and u16(m, 0x410142) == 1
    )
    return {
        "name": "sparse-duplicate-elimination",
        "source_offsets": list(source_offsets),
        "manifest_offsets": list(manifest),
        "manifest_length": manifest_length,
        "candidate_code_sha256": hashlib.sha256(observed_code).hexdigest(),
        "candidate_color_sha256": hashlib.sha256(observed_color).hexdigest(),
        "green": green,
    }


def route_cases(
    m: McpSession,
    state: Path,
    entry: int,
    full_scan: int,
    first: int,
    clean: int,
) -> list[dict[str, object]]:
    cases = (
        ("unknown", 1, 0xFFFF, 0x0010, 1, full_scan),
        ("empty-exact", 1, 1, 0, 1, full_scan),
        ("first-image", 1, 1, 0x0010, 0, first),
        ("clean", 0, 0, 0, 1, clean),
    )
    results = []
    for name, dirty, status, length, baseline, target in cases:
        m.load_state(state)
        m.pause()
        write_u16(m, 0x410140, dirty)
        write_u16(m, 0x41014C, status)
        write_u16(m, 0x41014E, length)
        write_u16(m, 0x410136, baseline)
        run_to_hook(m, entry, target)
        results.append({"name": f"route-{name}", "target": f"{target:06X}", "green": True})
    return results


def first_image_cases(
    m: McpSession,
    state: Path,
    entry: int,
    done: int,
    rom: bytes,
) -> list[dict[str, object]]:
    live_code = pattern(7, 3)
    live_color = pattern(11, 5)
    prepared_map = rom[0x2F9000:0x2FA000]
    prepared_codes = rom[0x2FA000:0x2FA05A]
    prepared_palettes = rom[0x2FA05A:0x2FA07A]
    if not (
        len(prepared_map) == 0x1000
        and len(prepared_codes) == 0x005A
        and len(prepared_palettes) == 0x0020
    ):
        raise AssertionError("C0BC prepared ROM payload is truncated")

    results: list[dict[str, object]] = []
    for name, token in (("c0bc", 0xC0BC), ("ordinary", 0x1234)):
        m.load_state(state)
        m.pause()
        write(m, 0x414800, live_code)
        write(m, 0x414C00, live_color)
        write(m, 0x410A00, bytes(0x0400))
        write(m, 0x410E00, bytes(0x0400))
        write(m, 0x418000, bytes([0xA5]) * 0x1000)
        write_u16(m, 0x41013A, 0)
        write_u16(m, 0x410146, 0)
        write_u16(m, 0x41014A, token)
        write_u16(m, 0x41015A, 0xC0BC)
        run_to_hook(m, entry, done)

        copied = (
            read(m, 0x410A00, 0x0400) == live_code
            and read(m, 0x410E00, 0x0400) == live_color
        )
        if name == "c0bc":
            route_green = (
                u16(m, 0x41013A) == 0xFFFE
                and u16(m, 0x410146) == 0x005A
                and u16(m, 0x41014A) == 0xC0BC
                and u16(m, 0x41015A) == 0xC0BC
                and read(m, 0x418000, 0x1000) == prepared_map
                and read(m, 0x419000, 0x005A) == prepared_codes
                and read(m, 0x419200, 0x0020) == prepared_palettes
            )
        else:
            route_green = (
                u16(m, 0x41013A) == 0xFFFF
                and u16(m, 0x410146) == 0
                and u16(m, 0x41014A) == 0
                and u16(m, 0x41015A) == 0
                and read(m, 0x418000, 0x1000) == bytes([0xA5]) * 0x1000
            )
        results.append(
            {
                "name": f"first-image-{name}",
                "manifest_length": u16(m, 0x41013A),
                "prepared_code_length": u16(m, 0x410146),
                "producer_token": f"{u16(m, 0x41014A):04X}",
                "displayed_source": f"{u16(m, 0x41015A):04X}",
                "candidate_copied": copied,
                "green": copied and route_green,
            }
        )
    return results


def c0bc_transition_cases(
    m: McpSession,
    state: Path,
    entry: int,
    done: int,
    rom: bytes,
) -> list[dict[str, object]]:
    """Distinguish a baseline delta from mutation after C0BC publication."""
    live_code = bytes((0x00, 0x01)) * 0x0200
    live_color = bytes(0x0400)
    prepared_map = rom[0x2F9000:0x2FA000]
    results: list[dict[str, object]] = []
    for name, mutate_snapshot in (
        ("published-exact", False),
        ("post-publish-mutation", True),
    ):
        m.load_state(state)
        m.pause()
        write(m, 0x410200, bytes(0x0400))
        write(m, 0x410600, bytes(0x0400))
        write(m, 0x410A00, bytes(0x0400))
        write(m, 0x410E00, bytes(0x0400))
        write(m, 0x414800, live_code)
        write(m, 0x414C00, live_color)
        snapshot_code = bytearray(live_code)
        if mutate_snapshot:
            snapshot_code[0] ^= 0x80
        write(m, 0x41A000, bytes(snapshot_code))
        write(m, 0x41A400, live_color)
        write_u16(m, 0x410136, 1)
        write_u16(m, 0x41013A, 0)
        write_u16(m, 0x410146, 0)
        write_u16(m, 0x41014A, 0xC0BC)
        write_u16(m, 0x41015A, 0)
        # A full 512-cell scan followed by exact snapshot validation and
        # prepared-map construction can legitimately cross one video frame.
        run_to_hook(m, entry, done, max_frames=8)

        token = u16(m, 0x41014A)
        displayed = u16(m, 0x41015A)
        manifest_length = u16(m, 0x41013A)
        prepared_length = u16(m, 0x410146)
        copied = read(m, 0x410A00, 0x0400) == live_code
        if mutate_snapshot:
            route_green = (
                token == 0
                and displayed == 0
                and manifest_length == 0xFFFE
                and prepared_length == 0x0002
            )
        else:
            route_green = (
                token == 0xC0BC
                and displayed == 0xC0BC
                and manifest_length == 0xFFFE
                and prepared_length == 0x005A
                and read(m, 0x418000, 0x1000) == prepared_map
            )
        results.append(
            {
                "name": f"c0bc-transition-{name}",
                "manifest_length": manifest_length,
                "prepared_code_length": prepared_length,
                "producer_token": f"{token:04X}",
                "displayed_source": f"{displayed:04X}",
                "candidate_copied": copied,
                "green": copied and route_green,
            }
        )
    return results


def main() -> int:
    args = parse_args()
    for path in (
        args.rom,
        args.state,
        args.esc7_symbols,
        args.esc8_symbols,
        args.nexen,
    ):
        if not path.is_file() or path.stat().st_size == 0:
            raise SystemExit(f"missing or empty input: {path}")
    if args.output.exists():
        raise SystemExit(f"refusing existing output: {args.output}")
    args.output.mkdir(parents=True)
    os.environ["DOTNET_ROOT"] = "/home/chad/.dotnet10"
    os.environ["PATH"] = "/home/chad/.dotnet10:" + os.environ.get("PATH", "")

    entries = {
        "appender": symbol_address(
            args.esc7_symbols, 0x9D, "producer_bg_append_range"
        ),
        "sparse": symbol_address(args.esc8_symbols, 0x9E, "render_bg_dirty_sparse"),
        "sparse_done": symbol_address(args.esc8_symbols, 0x9E, "rbds_done"),
        "full_scan": symbol_address(args.esc8_symbols, 0x9E, "rmb_bg_full_scan"),
        "first": symbol_address(args.esc8_symbols, 0x9E, "rmb_bg_first"),
        "clean": symbol_address(args.esc8_symbols, 0x9E, "rmb_bg_clean"),
        "obj_begin": symbol_address(args.esc8_symbols, 0x9E, "rmb_obj_begin"),
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
        m.pause()
        cases.extend(appender_cases(m, args.state.resolve(), entries["appender"]))
        cases.append(
            sparse_case(
                m,
                args.state.resolve(),
                entries["sparse"],
                entries["sparse_done"],
            )
        )
        cases.extend(
            route_cases(
                m,
                args.state.resolve(),
                entries["sparse"],
                entries["full_scan"],
                entries["first"],
                entries["clean"],
            )
        )
        cases.extend(
            first_image_cases(
                m,
                args.state.resolve(),
                entries["first"],
                entries["obj_begin"],
                args.rom.read_bytes(),
            )
        )
        cases.extend(
            c0bc_transition_cases(
                m,
                args.state.resolve(),
                entries["full_scan"],
                entries["obj_begin"],
                args.rom.read_bytes(),
            )
        )

    result = {
        "scope": "synthetic checkpointed exact BG producer-list semantics; not fps",
        "result": "green" if all(case["green"] for case in cases) else "red",
        "rom": str(args.rom.resolve()),
        "rom_sha256": sha256(args.rom),
        "state": str(args.state.resolve()),
        "state_sha256": sha256(args.state),
        "nexen": str(args.nexen.resolve()),
        "nexen_sha256": sha256(args.nexen),
        "entries": {name: f"{address:06X}" for name, address in entries.items()},
        "cases": cases,
    }
    target = args.output / "results.json"
    target.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
    for case in cases:
        print(json.dumps({"event": "case", **case}, sort_keys=True), flush=True)
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
