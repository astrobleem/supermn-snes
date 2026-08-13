#!/usr/bin/env python3
"""Extract one serialized SNES checkpoint's logical X1-001 video image.

The SA-1 presentation shadow stores arcade palette, Y/control, and code/X
planes as big-endian bytes.  This diagnostic converts them to the established
little-endian dump format consumed by ``render_full_frame.py``.  It does not
modify the checkpoint or claim that the software render is an exact MAME frame.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import struct
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, "/home/chad/Mesen2/python")

import mesen_mcp.session as _session  # noqa: E402

_session.validate_mesen_build = lambda *_args, **_kwargs: None
from mesen_mcp import McpSession  # noqa: E402


DEFAULT_MESEN = Path("/home/chad/Mesen2/bin/linux-x64/Release/Mesen")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--rom", type=Path, required=True)
    parser.add_argument("--state", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--emulator", type=Path, default=DEFAULT_MESEN)
    parser.add_argument("--port", type=int, default=43120)
    return parser.parse_args()


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def configure_dotnet(emulator: Path) -> None:
    selected = "/home/chad/.dotnet8" if emulator.name == "Mesen" else "/home/chad/.dotnet10"
    other = "/home/chad/.dotnet10" if selected.endswith("dotnet8") else "/home/chad/.dotnet8"
    os.environ["DOTNET_ROOT"] = selected
    current = [
        item
        for item in os.environ.get("PATH", "").split(":")
        if item and item not in (selected, other)
    ]
    os.environ["PATH"] = ":".join([selected, other, *current])


def words_be_to_le(data: bytes) -> bytes:
    if len(data) % 2:
        raise ValueError("word plane has odd length")
    words = struct.unpack(f">{len(data) // 2}H", data)
    return struct.pack(f"<{len(words)}H", *words)


def main() -> int:
    args = parse_args()
    for path in (args.rom, args.state, args.emulator):
        if not path.is_file():
            raise FileNotFoundError(path)
    rom = args.rom.resolve()
    state = args.state.resolve()
    output = args.output.resolve()
    if output.exists():
        raise SystemExit(f"refusing existing output: {output}")
    if rom.stat().st_size != 0x400000:
        raise SystemExit("expected a 4 MiB production ROM")
    output.mkdir(parents=True)
    configure_dotnet(args.emulator)

    with McpSession(
        rom=rom,
        mesen=args.emulator.resolve(),
        cwd=ROOT,
        port=args.port,
        boot_wait=6.0,
        socket_timeout=120.0,
        stderr_log=output / "emulator.stderr.log",
    ) as m:
        m.pause()
        m.load_state(state)
        m.pause()
        palette = bytes(m.read_memory("snesMemory", 0x412000, 0x1000))
        y_control = bytes(m.read_memory("snesMemory", 0x413000, 0x1000))
        code_x = bytes(m.read_memory("snesMemory", 0x414000, 0x4000))
        raw_bg_codes = bytes(m.read_memory("snesWorkRam", 0x2000, 0x0400))
        raw_bg_colors = bytes(m.read_memory("snesWorkRam", 0x2400, 0x0400))
        frame = int(m.get_state().get("frameCount", 0))

    logical_y = y_control[1:0x0600:2]
    if len(logical_y) != 0x0300:
        raise RuntimeError("logical X1 Y plane did not contain 768 byte lanes")
    live_bg_codes = code_x[0x0800:0x0C00]
    live_bg_colors = code_x[0x0C00:0x1000]
    products = {
        "c_palette.bin": words_be_to_le(palette),
        "c_spritecode_full.bin": words_be_to_le(code_x),
        "c_spriteylow.bin": logical_y,
        "c_spritectrl.bin": words_be_to_le(y_control[0x0600:0x0608]),
        "video-shadow.bin": palette + y_control + code_x,
        "canonical-raw-bg-codes.bin": raw_bg_codes,
        "canonical-raw-bg-colors.bin": raw_bg_colors,
        "live-x1-bg-codes.bin": live_bg_codes,
        "live-x1-bg-colors.bin": live_bg_colors,
    }
    artifacts = {}
    for name, data in products.items():
        path = output / name
        path.write_bytes(data)
        artifacts[name] = {
            "path": str(path),
            "bytes": len(data),
            "sha256": hashlib.sha256(data).hexdigest(),
        }

    report = {
        "schema": 1,
        "scope": (
            "serialized checkpoint X1-001 presentation-shadow extraction; "
            "software-renderer input only, not an exact MAME oracle"
        ),
        "rom": str(rom),
        "rom_sha256": sha256(rom),
        "state": str(state),
        "state_sha256": sha256(state),
        "emulator": str(args.emulator.resolve()),
        "frame": frame,
        "runtime_memory_writes": [],
        "canonical_raw_vs_live_x1": {
            "exact": (
                raw_bg_codes == live_bg_codes
                and raw_bg_colors == live_bg_colors
            ),
            "code_mismatch_count": sum(
                left != right
                for left, right in zip(raw_bg_codes, live_bg_codes)
            ),
            "color_mismatch_count": sum(
                left != right
                for left, right in zip(raw_bg_colors, live_bg_colors)
            ),
            "first_code_mismatch_offsets": [
                index
                for index, (left, right) in enumerate(
                    zip(raw_bg_codes, live_bg_codes)
                )
                if left != right
            ][:64],
            "first_color_mismatch_offsets": [
                index
                for index, (left, right) in enumerate(
                    zip(raw_bg_colors, live_bg_colors)
                )
                if left != right
            ][:64],
        },
        "artifacts": artifacts,
    }
    target = output / "report.json"
    target.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    print(json.dumps({"report": str(target), "frame": frame}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
