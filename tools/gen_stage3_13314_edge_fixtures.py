#!/usr/bin/env python3
"""Derive coordinate-boundary fixtures for Stage-3 clamp leaf $013314."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path


BOUNDARIES = (
    ("x-31", 31, 100),
    ("x-32", 32, 100),
    ("x-200", 200, 100),
    ("x-201", 201, 100),
    ("y-31", 100, 31),
    ("y-32", 100, 32),
    ("y-320", 100, 320),
    ("y-321", 100, 321),
)


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
    if int(str(source["target"]), 16) != 0x013314:
        parser.error("source is not a $013314 fixture")
    source_work = work_path.read_bytes()
    if len(source_work) != 0x10000:
        parser.error("source work image is not 64 KiB")

    a6 = int(source["regs"]["A6"]) & 0xFFFFFFFF
    a7 = int(source["regs"]["A7"]) & 0xFFFFFFFF
    if a6 >> 16 != 0x00F0 or a7 >> 16 != 0x00F0:
        parser.error("source A6/A7 are not canonical work RAM")

    args.output.mkdir(parents=True)
    manifest: list[dict[str, object]] = []
    index = 0
    for boundary_index, (label, x, y) in enumerate(BOUNDARIES):
        for incoming_x in (0, 1):
            work = bytearray(source_work)
            metadata = json.loads(json.dumps(source))

            # The routine reloads D2.W from A6-$40, clamps X at A6-$22 and Y
            # at A6-$1E, then clears one of D2 bits 0-3 for each boundary it
            # clips.  Seed all four bits plus unrelated bits to expose both
            # required clears and forbidden collateral writes.
            put_be16(work, a6 - 0x40, 0x5A5F)
            put_be16(work, a6 - 0x22, x)
            put_be16(work, a6 - 0x1E, y)
            put_be32(work, a7, 0x012702)

            metadata["index"] = index
            metadata["return_pc"] = "012702"
            metadata["regs"]["D0"] = 0x5A5ADEAD
            metadata["regs"]["D2"] = 0xA5A5BEEF
            metadata["sr"] = (int(source["sr"]) & ~0x1F) | (
                incoming_x << 4
            )
            metadata["work_sha256"] = digest(work)
            metadata["intervention"] = {
                "kind": "focused_13314_coordinate_boundary",
                "source_fixture": str(args.source.resolve()),
                "source_work_sha256": digest(source_work),
                "x": x,
                "y": y,
                "incoming_x": incoming_x,
                "d0_high_word": "5A5A",
                "d2_high_word": "A5A5",
                "d2_source_word": "5A5F",
            }
            metadata["object_record_hex"] = work[
                (a6 & 0xFFFF) : (a6 & 0xFFFF) + 0x40
            ].hex()
            metadata["stack_window_hex"] = work[
                max(0, (a7 & 0xFFFF) - 64) :
                min(0x10000, (a7 & 0xFFFF) + 16)
            ].hex()

            case_dir = args.output / f"013314-{label}-x{incoming_x}"
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
                    "work_sha256": metadata["work_sha256"],
                }
            )
            index += 1

    (args.output / "manifest.json").write_text(
        json.dumps(
            {
                "scope": (
                    "derived clamp-boundary fixtures from one organic "
                    "$013314 PC-ring entry; D0/D2 high-word preservation, "
                    "D2 bits 0-3, and both incoming X values; no gameplay "
                    "or performance claim"
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
    print(f"generated {len(manifest)} $013314 edge fixtures in {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
