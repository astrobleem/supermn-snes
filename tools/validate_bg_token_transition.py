#!/usr/bin/env python3
"""Focused C0BC token-transition fixture for the real 5A22 BG helper.

This loads a retained paused checkpoint, parks the SA-1, calls the production
``bg_column_map_update`` on the 5A22 with synthetic column metadata, and checks
the C0BC applied-token transition plus the exact immutable-ROM map remap.  It
is synthetic checkpoint evidence only: not fresh boot, visual acceptance, FPS,
or gameplay evidence.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
MESEN_PY = Path("/home/chad/Mesen2/python")
DEFAULT_NEXEN = Path(
    "/mnt/sdc1/Nexen-r5-20260712/bin/linux-x64/Release/"
    "linux-x64/publish/Nexen"
)
MAP_ROM_OFFSET = 0x2F9000
MAP_LENGTH = 0x1000
CURRENT_MAP = 0x7E89E0
APPLIED_MAP = 0x7E89F0
KIND = 0x7E8996
BG_LEN = 0x7E89BC
BG_DIRTY = 0x7E8990
PREPARED_LENGTH = 0x7E89C4
PREPARED_CODES = 0x7E7900
PREPARED_PALMAP = 0x7E8940
DISPLAY_TOKEN = 0x7E7492
APPLIED_TOKEN = 0x7E7498
TILEMAP = 0x7E9000
STACK_POINTER = 0x1FEC

sys.path.insert(0, str(MESEN_PY))
import mesen_mcp.session as _session  # noqa: E402

_session.validate_mesen_build = lambda *_args, **_kwargs: None
from mesen_mcp import McpSession  # noqa: E402


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--rom", type=Path, required=True)
    parser.add_argument("--state", type=Path, required=True)
    parser.add_argument("--symbols", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--nexen", type=Path, default=DEFAULT_NEXEN)
    parser.add_argument("--port", type=int, default=8878)
    return parser.parse_args()


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def symbol_address(path: Path, name: str) -> int:
    pattern = re.compile(r"^([0-9A-Fa-f]{2}):([0-9A-Fa-f]{4})\s+(\S+)$")
    for line in path.read_text(encoding="utf-8-sig").splitlines():
        match = pattern.match(line.strip())
        if match and match.group(3) == name:
            bank, offset = match.group(1), match.group(2)
            if int(bank, 16) != 0:
                raise RuntimeError(f"unexpected video symbol bank for {name}: {bank}:{offset}")
            return 0xE90000 | int(offset, 16)
    raise RuntimeError(f"missing symbol {name} in {path}")


def configure_runtime() -> None:
    os.environ["DOTNET_ROOT"] = "/home/chad/.dotnet10"
    old_path = os.environ.get("PATH", "")
    os.environ["PATH"] = "/home/chad/.dotnet10:/home/chad/.dotnet8:" + old_path


def write(m: McpSession, address: int, data: bytes) -> None:
    m.write_memory("snesMemory", address, data.hex())


def read(m: McpSession, address: int, length: int) -> bytes:
    return bytes(m.read_memory("snesMemory", address, length))


def park_sa1(m: McpSession) -> None:
    m.write_memory("Sa1Memory", 0x0600, "80fe")
    m.write_memory("snesMemory", 0x2201, "00")
    state = dict(m.get_cpu_state("Sa1"))
    allowed = {
        "cpuType": state.get("cpuType", "Sa1"),
        "pc": 0x0600,
        "k": 0,
        "a": int(state.get("a", 0)),
        "x": int(state.get("x", 0)),
        "y": int(state.get("y", 0)),
        "sp": int(state.get("sp", 0x1FF0)),
        "d": 0,
        "dbr": 0,
        "ps": int(state.get("ps", 0x04)) | 0x04,
        "emulationMode": False,
    }
    m.tool("set_cpu_state", allowed)


def rom_file_offset(cpu_address: int) -> int:
    bank = (cpu_address >> 16) & 0xFF
    if bank < 0xC0:
        raise RuntimeError(f"expected HiROM helper address, got ${cpu_address:06X}")
    return ((bank & 0x3F) << 16) | (cpu_address & 0xFFFF)


def mismatch(expected: bytes, observed: bytes) -> dict[str, Any]:
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


def reference_remap(source: bytes, column_map: bytes) -> bytes:
    """Model prepared_bg_map_remap's two 32x32 nametable halves."""
    if len(source) != MAP_LENGTH or len(column_map) != 16:
        raise ValueError("reference input has an unexpected size")
    output = bytearray(MAP_LENGTH)
    for row in range(32):
        row_offset = row * 0x40
        for source_column, physical in enumerate(column_map):
            source_quad = (
                row_offset
                + (source_column & 7) * 8
                + (0x800 if source_column & 8 else 0)
            )
            destination_quad = (
                row_offset
                + (physical & 7) * 8
                + (0x800 if physical & 8 else 0)
            )
            for byte in range(0, 8, 2):
                value = source[source_quad + byte : source_quad + byte + 2]
                if value != b"\x00\x00":
                    output[
                        destination_quad + byte : destination_quad + byte + 2
                    ] = value
    return bytes(output)


def set_cpu_rtl_call(m: McpSession, entry: int, return_spin: int) -> dict[str, Any]:
    """Call an RTL helper with a synthetic JSL return frame and stop at spin."""
    return_minus_one = (return_spin - 1) & 0xFFFF
    # RTL consumes low/high/bank at S+1..S+3 and increments the 16-bit PC.
    m.write_memory(
        "snesMemory",
        STACK_POINTER + 1,
        return_minus_one.to_bytes(2, "little").hex() + f"{(return_spin >> 16) & 0xFF:02x}",
    )
    previous = dict(m.get_cpu_state("Snes"))
    state = {
        "cpuType": previous.get("cpuType", "Snes"),
        "pc": entry & 0xFFFF,
        "k": (entry >> 16) & 0xFF,
        "a": 0,
        "x": 0,
        "y": 0,
        "sp": STACK_POINTER,
        "d": 0,
        "dbr": 0,
        "ps": (int(previous.get("ps", 0x04)) & ~0x30) | 0x04,
        "emulationMode": False,
    }
    hook = m.add_exec_hook(return_spin, cpu_type="Snes")
    m.drain_notifications(timeout=0.02)
    try:
        m.tool("set_cpu_state", state)
        # The exact 4 KiB canonical remap is intentionally foreground work and
        # can cross several emulated video frames in this isolated direct call.
        hit = m.run_until(max_frames=20, hook_handle=hook)
        m.pause()
        final = dict(m.get_cpu_state("Snes"))
    finally:
        m.remove_hook(hook)
        m.drain_notifications(timeout=0.02)
    pc = ((int(final.get("k", 0)) & 0xFF) << 16) | (int(final.get("pc", 0)) & 0xFFFF)
    if (hit or {}).get("reason") != "hookFired" or pc != return_spin:
        raise RuntimeError(f"bg_column_map_update did not RTL to ${return_spin:06X}: {hit!r}, {final!r}")
    return final


def prepare_case(m: McpSession, token: int, marker: bytes, column_map: bytes) -> None:
    write(m, CURRENT_MAP, column_map)
    write(m, APPLIED_MAP, column_map)
    write(m, KIND, (0x003F).to_bytes(2, "little"))
    write(m, BG_LEN, b"\x00\x00")
    write(m, BG_DIRTY, b"\x00\x00")
    write(m, PREPARED_LENGTH, b"\x00\x00")
    write(m, PREPARED_CODES, b"\xA5" * 0x005A)
    write(m, PREPARED_PALMAP, b"\x5A" * 0x0020)
    write(m, DISPLAY_TOKEN, token.to_bytes(2, "little"))
    write(m, APPLIED_TOKEN, b"\x00\x00")
    write(m, TILEMAP, marker)


def main() -> int:
    args = parse_args()
    for label, path in (("ROM", args.rom), ("state", args.state), ("symbols", args.symbols), ("Nexen", args.nexen)):
        if not path.is_file() or path.stat().st_size == 0:
            raise FileNotFoundError(f"missing or empty {label}: {path}")
    if args.output.exists():
        raise RuntimeError(f"refusing to overwrite existing output: {args.output}")
    rom = args.rom.resolve()
    rom_bytes = rom.read_bytes()
    if len(rom_bytes) != 0x400000:
        raise RuntimeError("expected a 4 MiB production ROM")
    if int.from_bytes(rom_bytes[0x77E0:0x77E2], "little") != 0:
        raise RuntimeError("refusing non-production ROM: TESTFLAG is set")
    prepared_source = rom_bytes[MAP_ROM_OFFSET : MAP_ROM_OFFSET + MAP_LENGTH]
    if len(prepared_source) != MAP_LENGTH:
        raise RuntimeError("ROM does not contain complete immutable C0BC map")
    entry = symbol_address(args.symbols, "bg_column_map_update")
    end = symbol_address(args.symbols, "bg_column_map_update_end")
    return_spin = symbol_address(args.symbols, "accept_bg_columns_direct_end") + 1
    spin_offset = rom_file_offset(return_spin)
    if rom_bytes[spin_offset : spin_offset + 2] != b"\x00\x00":
        raise RuntimeError(f"return seam ${return_spin:06X} is not a zero seam")
    column_map = bytes(range(14)) + b"\x00\x00"
    reference = reference_remap(prepared_source, column_map)
    marker = (b"\xBE\xEF" * (MAP_LENGTH // 2))
    configure_runtime()
    rows: list[dict[str, Any]] = []
    args.output.parent.mkdir(parents=True, exist_ok=True)
    stderr_log = args.output.parent / (args.output.stem + ".nexen.stderr.log")
    with McpSession(
        rom=rom,
        mesen=args.nexen.resolve(),
        cwd=ROOT,
        port=args.port,
        boot_wait=8.0,
        socket_timeout=120.0,
        stderr_log=stderr_log,
    ) as m:
        m.pause()
        m.load_state(str(args.state.resolve()))
        m.pause()
        park_sa1(m)
        m.write_memory("snesPrgRom", spin_offset, "80fe")
        if bytes(m.read_memory("snesPrgRom", spin_offset, 2)) != b"\x80\xfe":
            raise RuntimeError("failed to install runtime RTL return spin")

        prepare_case(m, 0xC0BC, marker, column_map)
        set_cpu_rtl_call(m, entry, return_spin)
        first_map = read(m, TILEMAP, MAP_LENGTH)
        first_token = int.from_bytes(read(m, APPLIED_TOKEN, 2), "little")
        first_dirty = int.from_bytes(read(m, BG_DIRTY, 2), "little")
        first_length = int.from_bytes(read(m, BG_LEN, 2), "little")
        first_prepared_length = int.from_bytes(
            read(m, PREPARED_LENGTH, 2), "little"
        )
        first_codes = read(m, PREPARED_CODES, 0x005A)
        first_palmap = read(m, PREPARED_PALMAP, 0x0020)
        first = {
            "name": "c0bc-transition",
            "token": {"expected": 0xC0BC, "observed": first_token},
            "bg_dirty": {"expected": 1, "observed": first_dirty},
            "bg_length": {"expected": 0xFFFE, "observed": first_length},
            "prepared_length": {
                "expected": 0x005A,
                "observed": first_prepared_length,
            },
            "prepared_codes": mismatch(
                rom_bytes[0x2FA000:0x2FA05A], first_codes
            ),
            "prepared_palette_map": mismatch(
                rom_bytes[0x2FA05A:0x2FA07A], first_palmap
            ),
            "map": mismatch(reference, first_map),
        }
        first["pass"] = (
            first_token == 0xC0BC
            and first_dirty == 1
            and first_length == 0xFFFE
            and first_prepared_length == 0x005A
            and first["prepared_codes"]["mismatch_count"] == 0
            and first["prepared_palette_map"]["mismatch_count"] == 0
            and first["map"]["mismatch_count"] == 0
        )
        rows.append(first)

        set_cpu_rtl_call(m, entry, return_spin)
        second_map = read(m, TILEMAP, MAP_LENGTH)
        second_token = int.from_bytes(read(m, APPLIED_TOKEN, 2), "little")
        second_dirty = int.from_bytes(read(m, BG_DIRTY, 2), "little")
        second_length = int.from_bytes(read(m, BG_LEN, 2), "little")
        second = {
            "name": "c0bc-idempotent",
            "token": {"expected": 0xC0BC, "observed": second_token},
            "bg_dirty": {"expected": 1, "observed": second_dirty},
            "bg_length": {"expected": 0xFFFE, "observed": second_length},
            "map": mismatch(first_map, second_map),
        }
        second["pass"] = (
            second_token == 0xC0BC
            and second_dirty == 1
            and second_length == 0xFFFE
            and second["map"]["mismatch_count"] == 0
        )
        rows.append(second)

        m.load_state(str(args.state.resolve()))
        m.pause()
        park_sa1(m)
        m.write_memory("snesPrgRom", spin_offset, "80fe")
        if bytes(m.read_memory("snesPrgRom", spin_offset, 2)) != b"\x80\xfe":
            raise RuntimeError("runtime RTL return spin did not survive state reload")
        prepare_case(m, 0, marker, column_map)
        set_cpu_rtl_call(m, entry, return_spin)
        control_map = read(m, TILEMAP, MAP_LENGTH)
        control_token = int.from_bytes(read(m, APPLIED_TOKEN, 2), "little")
        control_dirty = int.from_bytes(read(m, BG_DIRTY, 2), "little")
        control_length = int.from_bytes(read(m, BG_LEN, 2), "little")
        control_prepared_length = int.from_bytes(
            read(m, PREPARED_LENGTH, 2), "little"
        )
        control = {
            "name": "non-c0bc-control",
            "token": {"expected": 0, "observed": control_token},
            "bg_dirty": {"expected": 0, "observed": control_dirty},
            "bg_length": {"expected": 0, "observed": control_length},
            "prepared_length": {
                "expected": 0,
                "observed": control_prepared_length,
            },
            "prepared_codes": mismatch(
                b"\xA5" * 0x005A, read(m, PREPARED_CODES, 0x005A)
            ),
            "prepared_palette_map": mismatch(
                b"\x5A" * 0x0020, read(m, PREPARED_PALMAP, 0x0020)
            ),
            "map": mismatch(marker, control_map),
        }
        control["pass"] = (
            control_token == 0
            and control_dirty == 0
            and control_length == 0
            and control_prepared_length == 0
            and control["prepared_codes"]["mismatch_count"] == 0
            and control["prepared_palette_map"]["mismatch_count"] == 0
            and control["map"]["mismatch_count"] == 0
        )
        rows.append(control)

    report = {
        "scope": "synthetic paused-checkpoint 5A22 token/remap fixture; not fresh boot, visual acceptance, FPS, or gameplay evidence",
        "rom": str(rom),
        "rom_sha256": sha256(rom),
        "state": str(args.state.resolve()),
        "symbols": str(args.symbols.resolve()),
        "nexen": str(args.nexen.resolve()),
        "helpers": {"entry": f"{entry:06X}", "end": f"{end:06X}", "return_spin": f"{return_spin:06X}"},
        "column_map": column_map.hex(),
        "prepared_rom_offset": f"{MAP_ROM_OFFSET:06X}",
        "prepared_rom_sha256": hashlib.sha256(prepared_source).hexdigest(),
        "rows": rows,
        "passed": sum(bool(row["pass"]) for row in rows),
        "total": len(rows),
    }
    args.output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0 if report["passed"] == report["total"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
