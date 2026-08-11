#!/usr/bin/env python3
"""Derive deterministic signed-boundary fixtures for Stage-3 leaf $02F542."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path


# Every signed comparison boundary, plus one ordinary in-range point.
COORDINATES = (
    ("x-neg17", -17, 0),
    ("x-neg16", -16, 0),
    ("x-neg15", -15, 0),
    ("x-127", 127, 0),
    ("x-128", 128, 0),
    ("y-neg17", 0, -17),
    ("y-neg16", 0, -16),
    ("y-neg15", 0, -15),
    ("y-247", 0, 247),
    ("y-248", 0, 248),
)
RETURNS = (0x02F478, 0x02F50A)


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def put_be16(work: bytearray, address: int, value: int) -> None:
    offset = address & 0xFFFF
    work[offset : offset + 2] = (value & 0xFFFF).to_bytes(2, "big")


def put_be32(work: bytearray, address: int, value: int) -> None:
    offset = address & 0xFFFF
    work[offset : offset + 4] = (value & 0xFFFFFFFF).to_bytes(4, "big")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    metadata_path = args.source / "entry.json"
    work_path = args.source / "entry.work.bin"
    if not metadata_path.is_file() or not work_path.is_file():
        parser.error("--source must contain entry.json and entry.work.bin")
    if args.output.exists():
        parser.error(f"output already exists: {args.output}")

    source = json.loads(metadata_path.read_text(encoding="utf-8"))
    if int(str(source["target"]), 16) != 0x02F542:
        parser.error("source is not a $02F542 fixture")
    source_work = work_path.read_bytes()
    if len(source_work) != 0x10000:
        parser.error("source work image is not 64 KiB")

    a4 = int(source["regs"]["A4"]) & 0xFFFFFFFF
    a7 = int(source["regs"]["A7"]) & 0xFFFFFFFF
    if a4 >> 16 != 0x00F0 or a7 >> 16 != 0x00F0:
        parser.error("source A4/A7 are not canonical work RAM")

    args.output.mkdir(parents=True)
    manifest: list[dict[str, object]] = []
    index = 0
    for caller_index, return_pc in enumerate(RETURNS):
        for boundary_index, (label, x, y) in enumerate(COORDINATES):
            work = bytearray(source_work)
            metadata = json.loads(json.dumps(source))
            incoming_x = (caller_index + boundary_index) & 1

            put_be16(work, a4 + 4, x)
            put_be16(work, a4 + 6, y)
            put_be32(work, a7, return_pc)

            metadata["index"] = index
            metadata["return_pc"] = f"{return_pc:06X}"
            # MOVE.W #1,D7 must preserve this nontrivial high word.
            metadata["regs"]["D7"] = 0xA5A50000 | (
                int(source["regs"]["D7"]) & 0xFFFF
            )
            metadata["sr"] = (int(source["sr"]) & ~0x1F) | (
                incoming_x << 4
            )
            metadata["work_sha256"] = digest(work)
            metadata["intervention"] = {
                "kind": "focused_2f542_signed_boundary",
                "source_fixture": str(args.source.resolve()),
                "source_work_sha256": digest(source_work),
                "x": x,
                "y": y,
                "incoming_x": incoming_x,
                "d7_high_word": "A5A5",
                "return_pc": f"{return_pc:06X}",
            }
            metadata["object_record_hex"] = work[
                (a4 & 0xFFFF) : (a4 & 0xFFFF) + 0x40
            ].hex()
            metadata["stack_window_hex"] = work[
                max(0, (a7 & 0xFFFF) - 64) :
                min(0x10000, (a7 & 0xFFFF) + 16)
            ].hex()

            case_dir = args.output / (
                f"02f542-r{return_pc:06x}-{label}-x{incoming_x}"
            )
            case_dir.mkdir()
            (case_dir / "entry.work.bin").write_bytes(work)
            (case_dir / "entry.json").write_text(
                json.dumps(metadata, indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )
            manifest.append(
                {
                    "case": case_dir.name,
                    "x": x,
                    "y": y,
                    "incoming_x": incoming_x,
                    "return_pc": f"{return_pc:06X}",
                    "work_sha256": metadata["work_sha256"],
                }
            )
            index += 1

    (args.output / "manifest.json").write_text(
        json.dumps(
            {
                "scope": (
                    "derived signed-boundary fixtures from one organic "
                    "$02F542 PC-ring entry; both real callers and both "
                    "incoming X values; no gameplay/performance claim"
                ),
                "source": str(args.source.resolve()),
                "cases": manifest,
            },
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    print(f"generated {len(manifest)} $02F542 edge fixtures in {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
