#!/usr/bin/env python3
"""Derive deterministic byte/CCR/X edges for Stage-3 player leaf $013468.

The organic PC-ring fixtures originally retained for this handler all entered
with the descriptor status word at zero and therefore took the early exit.
These derived fixtures keep one exact organic register/work/stack layout, but
exercise the status split and the signed C/D direction bytes, including both
``NEG.B Dn`` instructions at $0134E0/$0134EA.

The output remains bounded fixture evidence.  It is not a gameplay or
fresh-boot claim.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path


# label, descriptor status, C byte, D byte, incoming CCR low five bits
CASES = (
    ("early-zero", 0x0000, 0x55, 0x66, 0x0F),
    ("below-threshold", 0x009D, 0x55, 0x66, 0x10),
    ("signed-negative", 0x8000, 0x55, 0x66, 0x00),
    ("special-809d", 0x809D, 0x00, 0xFF, 0x1F),
    ("threshold-czero-dpositive", 0x009E, 0x00, 0x01, 0x10),
    ("threshold-cpositive-dzero", 0x009E, 0x01, 0x00, 0x00),
    ("neg-both-non-equal", 0x009E, 0xFF, 0xFD, 0x00),
    ("neg-both-equal", 0x009E, 0xFF, 0xFF, 0x10),
    ("neg-c-only", 0x009E, 0xFF, 0x01, 0x00),
    ("neg-d-only", 0x009E, 0x01, 0xFD, 0x10),
    ("neg-c-overflow", 0x009E, 0x80, 0x01, 0x00),
    ("neg-d-overflow", 0x009E, 0x01, 0x80, 0x10),
)


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def get_be32(work: bytes, address: int) -> int:
    offset = address & 0xFFFF
    return int.from_bytes(work[offset : offset + 4], "big")


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
    if int(str(source["target"]), 16) != 0x013468:
        parser.error("source is not a $013468 fixture")
    source_work = work_path.read_bytes()
    if len(source_work) != 0x10000:
        parser.error("source work image is not 64 KiB")

    a6 = int(source["regs"]["A6"]) & 0xFFFFFFFF
    a7 = int(source["regs"]["A7"]) & 0xFFFFFFFF
    if a6 >> 16 != 0x00F0 or a7 >> 16 != 0x00F0:
        parser.error("source A6/A7 are not canonical work RAM")
    descriptor = get_be32(source_work, a6 - 0x28)
    alternate = get_be32(source_work, a6 - 0x34)
    for label, address in (
        ("descriptor", descriptor),
        ("alternate descriptor", alternate),
    ):
        if address >> 16 != 0x00F0 or (address & 0xFFFF) > 0x3FF0:
            parser.error(f"{label} pointer is not canonical: ${address:08X}")

    args.output.mkdir(parents=True)
    manifest: list[dict[str, object]] = []
    for index, (label, status, c_byte, d_byte, ccr) in enumerate(CASES):
        work = bytearray(source_work)
        metadata = json.loads(json.dumps(source))

        work[(descriptor + 0x0C) & 0xFFFF] = c_byte
        work[(descriptor + 0x0D) & 0xFFFF] = d_byte
        put_be16(work, descriptor + 0x0E, status)
        put_be16(work, a6 - 0x70, 0xA55A)
        put_be32(work, a7, 0x000126DC)

        metadata["index"] = index
        metadata["return_pc"] = "0126DC"
        # MOVE.B must preserve these poisoned upper 24 bits; NEG.B must also
        # preserve bits8-31.  The old lowering visibly changed ABxx -> 54xx
        # and CDxx -> 32xx at its internal seams.
        metadata["regs"]["D0"] = 0xA1A1AB55
        metadata["regs"]["D1"] = 0xB2B2CD66
        metadata["regs"]["D2"] = 0xC3C3BEEF
        metadata["sr"] = (int(source["sr"]) & ~0x1F) | ccr
        metadata["work_sha256"] = digest(work)
        metadata["intervention"] = {
            "kind": "focused_13468_neg_byte_edge",
            "source_fixture": str(args.source.resolve()),
            "source_work_sha256": digest(source_work),
            "descriptor": f"{descriptor:08X}",
            "alternate_descriptor": f"{alternate:08X}",
            "status": f"{status:04X}",
            "c_byte": f"{c_byte:02X}",
            "d_byte": f"{d_byte:02X}",
            "incoming_ccr_xnzvc": ccr,
            "d0_initial": "A1A1AB55",
            "d1_initial": "B2B2CD66",
            "first_neg_seam": c_byte >= 0x80 and status == 0x009E,
            "second_neg_seam": d_byte >= 0x80 and status == 0x009E,
        }
        metadata["object_record_hex"] = work[
            descriptor & 0xFFFF : (descriptor & 0xFFFF) + 0x40
        ].hex()
        sp = a7 & 0xFFFF
        metadata["stack_window_hex"] = work[
            max(0, sp - 64) : min(0x10000, sp + 16)
        ].hex()

        case_dir = args.output / f"013468-{label}"
        case_dir.mkdir()
        (case_dir / "entry.work.bin").write_bytes(work)
        (case_dir / "entry.json").write_text(
            json.dumps(metadata, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        manifest.append(
            {
                "case": case_dir.name,
                "status": f"{status:04X}",
                "c_byte": f"{c_byte:02X}",
                "d_byte": f"{d_byte:02X}",
                "incoming_ccr_xnzvc": ccr,
                "first_neg_seam": metadata["intervention"][
                    "first_neg_seam"
                ],
                "second_neg_seam": metadata["intervention"][
                    "second_neg_seam"
                ],
                "work_sha256": metadata["work_sha256"],
            }
        )

    (args.output / "manifest.json").write_text(
        json.dumps(
            {
                "scope": (
                    "derived $013468 status/direction-byte fixtures from one "
                    "organic PC-ring entry; poisoned D0/D1 upper bytes and "
                    "both incoming X values; no gameplay/performance claim"
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
    print(f"generated {len(manifest)} $013468 edge fixtures in {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
