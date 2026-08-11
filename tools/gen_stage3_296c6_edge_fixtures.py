#!/usr/bin/env python3
"""Derive deterministic CCR/X edge fixtures for the Stage-3 $0296C6 leaf.

The source fixture must be an organically captured PC-ring entry fixture.  This
tool changes only the compared A5+$293B byte, D7, and incoming CCR bits.  The
resulting fixtures are consumed by ``validate_stage3_hot_handlers.py`` for the
same MAME/native-off/native-on architectural comparison as organic cases.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path


CASES = (
    # CMP.B branches below two and therefore must preserve incoming X.
    ("cmp-below-x0", 0x00, 0x89AB1357, 0),
    ("cmp-below-x1", 0x01, 0x89AB2468, 1),
    # ADDQ.W result classes: ordinary, signed overflow, carry/zero, negative.
    ("add-ordinary", 0x02, 0x89AB0000, 1),
    ("add-overflow", 0x02, 0x89AB7FFF, 1),
    ("add-carry-zero", 0x02, 0x89ABFFFF, 0),
    ("add-negative", 0xFF, 0x89ABFFFE, 1),
)


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    source_meta_path = args.source / "entry.json"
    source_work_path = args.source / "entry.work.bin"
    if not source_meta_path.is_file() or not source_work_path.is_file():
        parser.error("--source must contain entry.json and entry.work.bin")
    if args.output.exists():
        parser.error(f"output already exists: {args.output}")

    source = json.loads(source_meta_path.read_text(encoding="utf-8"))
    if int(str(source["target"]), 16) != 0x0296C6:
        parser.error("source is not a $0296C6 entry fixture")
    original_work = source_work_path.read_bytes()
    if len(original_work) != 0x10000:
        parser.error("source work image is not 64 KiB")
    a5 = int(source["regs"]["A5"]) & 0xFFFFFFFF
    if a5 != 0x00F00000:
        parser.error(f"source A5 is not canonical work RAM: ${a5:08X}")

    args.output.mkdir(parents=True)
    manifest: list[dict[str, object]] = []
    for index, (label, compared_byte, d7, x) in enumerate(CASES):
        work = bytearray(original_work)
        compare_offset = (a5 + 0x293B) & 0xFFFF
        work[compare_offset] = compared_byte

        metadata = json.loads(json.dumps(source))
        metadata["index"] = index
        metadata["regs"]["D7"] = d7
        metadata["sr"] = (int(source["sr"]) & ~0x1F) | (x << 4)
        metadata["work_sha256"] = sha256_bytes(work)
        metadata["intervention"] = {
            "kind": "focused_296c6_semantic_edge",
            "source_fixture": str(args.source.resolve()),
            "source_work_sha256": sha256_bytes(original_work),
            "compare_address": "F0293B",
            "compare_byte": compared_byte,
            "d7": f"{d7:08X}",
            "incoming_x": x,
            "other_incoming_ccr_bits": 0,
        }
        a4 = int(metadata["regs"]["A4"]) & 0xFFFF
        a7 = int(metadata["regs"]["A7"]) & 0xFFFF
        metadata["object_record_hex"] = bytes(
            work[(a4 + offset) & 0xFFFF] for offset in range(0x40)
        ).hex()
        metadata["stack_window_hex"] = work[
            max(0, a7 - 64) : min(0x10000, a7 + 16)
        ].hex()

        case_dir = args.output / f"0296c6-{label}"
        case_dir.mkdir()
        (case_dir / "entry.work.bin").write_bytes(work)
        (case_dir / "entry.json").write_text(
            json.dumps(metadata, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        manifest.append(
            {
                "case": case_dir.name,
                "compare_byte": compared_byte,
                "d7": f"{d7:08X}",
                "incoming_x": x,
                "work_sha256": metadata["work_sha256"],
            }
        )

    (args.output / "manifest.json").write_text(
        json.dumps(
            {
                "scope": (
                    "derived semantic edge fixtures from one organic "
                    "$0296C6 PC-ring entry; no gameplay/performance claim"
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
    print(f"generated {len(manifest)} $0296C6 edge fixtures in {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
