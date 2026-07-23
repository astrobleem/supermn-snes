#!/usr/bin/env python3
"""Describe the exact sprite population in a paused production checkpoint.

This reads the immutable 5A22 renderer caches and applies vid_obj's visibility
tests in index order.  It is a checkpoint/layout diagnostic, not performance
or FPS evidence.
"""

from __future__ import annotations

import argparse
import hashlib
import json
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


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--rom", type=Path, default=ROOT / "build/interp.sfc")
    parser.add_argument("--state", type=Path, required=True)
    parser.add_argument("--nexen", type=Path, default=DEFAULT_NEXEN)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--port", type=int, default=7613)
    return parser.parse_args()


def be16(data: bytes, offset: int) -> int:
    return int.from_bytes(data[offset : offset + 2], "big")


def main() -> int:
    args = parse_args()
    for path in (args.rom, args.state, args.nexen):
        if not path.is_file():
            raise FileNotFoundError(path)
    args.output.parent.mkdir(parents=True, exist_ok=True)

    with McpSession(
        rom=args.rom.resolve(),
        mesen=args.nexen.resolve(),
        cwd=ROOT,
        port=args.port,
        boot_wait=6.0,
        socket_timeout=120.0,
        stderr_log=args.output.with_suffix(".stderr.log"),
    ) as m:
        m.pause()
        m.load_state(args.state.resolve())
        m.pause()
        y_plane = m.read_memory("snesWorkRam", 0x3000, 0x0400)
        code_plane = m.read_memory("snesWorkRam", 0x4000, 0x0400)
        xcolor_plane = m.read_memory("snesWorkRam", 0x4400, 0x0400)

    entries = []
    y_qualified_indexes = [
        index
        for index in range(512)
        if 0 < y_plane[index * 2 + 1] < 0xF0
    ]
    y_x_qualified_indexes = []
    for index in y_qualified_indexes:
        offset = index * 2
        xcolor = be16(xcolor_plane, offset)
        sx = xcolor & 0x1FF
        if sx >= 0x100:
            sx -= 0x200
        if sx >= -16:
            y_x_qualified_indexes.append(index)

    rejected = {
        "zero_code": 0,
        "ffff_code": 0,
        "zero_y": 0,
        "y_240_or_more": 0,
        "left_of_screen": 0,
        "after_oam_cap": 0,
    }
    for index in range(512):
        offset = index * 2
        code = be16(code_plane, offset)
        if code & 0x3FFF == 0:
            rejected["zero_code"] += 1
            continue
        if code == 0xFFFF:
            rejected["ffff_code"] += 1
            continue
        sy = y_plane[offset + 1]
        if sy == 0:
            rejected["zero_y"] += 1
            continue
        if sy >= 240:
            rejected["y_240_or_more"] += 1
            continue
        xcolor = be16(xcolor_plane, offset)
        sx = xcolor & 0xFF
        if xcolor & 0x100:
            sx -= 0x100
        if sx + 16 < 0:
            rejected["left_of_screen"] += 1
            continue
        if len(entries) >= 128:
            rejected["after_oam_cap"] += 1
            continue
        entries.append(
            {
                "index": index,
                "code": code & 0x3FFF,
                "flip_x": bool(code & 0x8000),
                "flip_y": bool(code & 0x4000),
                "sx": sx,
                "sy": sy,
                "palette_bank": (xcolor >> 11) & 0x1F,
            }
        )

    indexes = [entry["index"] for entry in entries]
    result = {
        "scope": "paused production-checkpoint OBJ population; not FPS",
        "rom": str(args.rom.resolve()),
        "rom_sha256": sha256(args.rom),
        "state": str(args.state.resolve()),
        "state_sha256": sha256(args.state),
        "nexen": str(args.nexen.resolve()),
        "nexen_sha256": sha256(args.nexen),
        "active_count": len(entries),
        "active_index_min": min(indexes, default=None),
        "active_index_max": max(indexes, default=None),
        "active_indexes": indexes,
        "y_qualified_count": len(y_qualified_indexes),
        "y_x_qualified_count": len(y_x_qualified_indexes),
        "y_low_zero_count": sum(
            y_plane[index * 2 + 1] == 0 for index in range(512)
        ),
        "y_low_240_or_more_count": sum(
            y_plane[index * 2 + 1] >= 0xF0 for index in range(512)
        ),
        "all_zero_y_groups": {
            str(group): sum(
                all(
                    y_plane[index * 2 + 1] == 0
                    for index in range(start, start + group)
                )
                for start in range(0, 512, group)
            )
            for group in (4, 8, 16)
        },
        "active_by_128_entry_quarter": [
            sum(start <= index < start + 128 for index in indexes)
            for start in range(0, 512, 128)
        ],
        "unique_codes": len({entry["code"] for entry in entries}),
        "palette_banks": sorted({entry["palette_bank"] for entry in entries}),
        "rejected": rejected,
        "entries": entries,
    }
    args.output.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
    print(
        json.dumps(
            {
                "active_count": result["active_count"],
                "active_by_128_entry_quarter": result["active_by_128_entry_quarter"],
                "unique_codes": result["unique_codes"],
                "palette_banks": result["palette_banks"],
                "output": str(args.output),
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
