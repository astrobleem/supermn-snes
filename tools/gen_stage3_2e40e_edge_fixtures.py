#!/usr/bin/env python3
"""Derive deterministic selector/shift edge fixtures for Stage-3 $02E40E."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path


CASES = (
    # label, complete D0 input, incoming X, genuine caller return
    ("zero", 0xA5C30000, 1, 0x02E44A),
    ("below-six-alt-return", 0xDEAD0006, 0, 0x02E3E6),
    ("threshold-seven", 0xBEEF0007, 1, 0x02E44A),
    ("post-sub-positive-7f", 0x13570086, 0, 0x02E44A),
    ("post-sub-negative-80", 0x24680087, 1, 0x02E44A),
    ("post-sub-negative-f8", 0xFACE00FF, 0, 0x02E3E6),
)


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


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
    if int(str(source["target"]), 16) != 0x02E40E:
        parser.error("source is not a $02E40E fixture")
    source_work = work_path.read_bytes()
    if len(source_work) != 0x10000:
        parser.error("source work image is not 64 KiB")

    args.output.mkdir(parents=True)
    manifest: list[dict[str, object]] = []
    for index, (label, d0, x, return_pc) in enumerate(CASES):
        work = bytearray(source_work)
        metadata = json.loads(json.dumps(source))
        a7 = int(metadata["regs"]["A7"]) & 0xFFFF
        work[a7 : a7 + 4] = return_pc.to_bytes(4, "big")
        metadata["index"] = index
        metadata["return_pc"] = f"{return_pc:06X}"
        metadata["regs"]["D0"] = d0
        metadata["sr"] = (int(source["sr"]) & ~0x1F) | (x << 4)
        metadata["work_sha256"] = digest(work)
        metadata["intervention"] = {
            "kind": "focused_2e40e_semantic_edge",
            "source_fixture": str(args.source.resolve()),
            "source_work_sha256": digest(source_work),
            "d0": f"{d0:08X}",
            "d0_byte": d0 & 0xFF,
            "incoming_x": x,
            "return_pc": f"{return_pc:06X}",
            "other_incoming_ccr_bits": 0,
        }
        a4 = int(metadata["regs"]["A4"]) & 0xFFFF
        metadata["object_record_hex"] = bytes(
            work[(a4 + offset) & 0xFFFF] for offset in range(0x40)
        ).hex()
        metadata["stack_window_hex"] = work[
            max(0, a7 - 64) : min(0x10000, a7 + 16)
        ].hex()

        case_dir = args.output / f"02e40e-{label}"
        case_dir.mkdir()
        (case_dir / "entry.work.bin").write_bytes(work)
        (case_dir / "entry.json").write_text(
            json.dumps(metadata, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        manifest.append(
            {
                "case": case_dir.name,
                "d0": f"{d0:08X}",
                "incoming_x": x,
                "return_pc": f"{return_pc:06X}",
                "work_sha256": metadata["work_sha256"],
            }
        )

    (args.output / "manifest.json").write_text(
        json.dumps(
            {
                "scope": (
                    "derived semantic edge fixtures from one organic "
                    "$02E40E PC-ring entry; no gameplay/performance claim"
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
    print(f"generated {len(manifest)} $02E40E edge fixtures in {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
