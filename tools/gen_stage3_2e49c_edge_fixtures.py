#!/usr/bin/env python3
"""Derive deterministic selector/CCR edges for Stage-3 lookup leaf $02E49C.

The retained organic fixtures exercise only small positive second selectors.
These cases preserve one real register/work/stack layout while covering every
final LSL.W flag class, both ends of the admitted first table, the ROM-bank
carry boundary, and the highest canonical A4/A7 fast-path addresses.

The output is bounded same-state fixture evidence, not gameplay or fresh-boot
proof.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path


# label, first selector, second selector, incoming CCR, optional A4/A7 low word
CASES = (
    ("zero", 0x0000, 0x0000, 0x1B, None, None),
    ("positive", 0x0012, 0x0001, 0x1F, None, None),
    ("negative", 0x0000, 0x2000, 0x07, None, None),
    ("zero-carry-x", 0x0000, 0x4000, 0x0A, None, None),
    ("negative-carry-x", 0x0000, 0x6000, 0x06, None, None),
    ("wrap-negative-carry-x", 0x0000, 0xFFFF, 0x04, None, None),
    ("last-c3-long", 0x0000, 0x0638, 0x12, None, None),
    ("first-c4-long", 0x0000, 0x0639, 0x0D, None, None),
    ("a4-last-canonical", 0x0012, 0x0001, 0x10, 0x3FF2, None),
    ("a7-last-canonical", 0x0000, 0x0000, 0x00, None, 0x3FFC),
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
    if int(str(source["target"]), 16) != 0x02E49C:
        parser.error("source is not a $02E49C fixture")
    source_work = work_path.read_bytes()
    if len(source_work) != 0x10000:
        parser.error("source work image is not 64 KiB")

    args.output.mkdir(parents=True)
    manifest: list[dict[str, object]] = []
    for index, (
        label,
        first_selector,
        second_selector,
        incoming_ccr,
        a4_low,
        a7_low,
    ) in enumerate(CASES):
        work = bytearray(source_work)
        metadata = json.loads(json.dumps(source))

        a4 = int(metadata["regs"]["A4"]) & 0xFFFFFFFF
        a7 = int(metadata["regs"]["A7"]) & 0xFFFFFFFF
        if a4_low is not None:
            a4 = 0x00F00000 | a4_low
        if a7_low is not None:
            a7 = 0x00F00000 | a7_low
        metadata["regs"]["A4"] = a4
        metadata["regs"]["A7"] = a7

        put_be16(work, a4 + 0x0A, first_selector)
        put_be16(work, a4 + 0x0C, second_selector)
        put_be32(work, a7, 0x0002E4BA)

        metadata["index"] = index
        metadata["return_pc"] = "02E4BA"
        metadata["regs"]["D0"] = 0xA5C3BEEF
        metadata["regs"]["A0"] = 0x0055AA33
        metadata["sr"] = (
            (int(source["sr"]) & ~0x1F) | (incoming_ccr & 0x1F)
        )
        metadata["state"] = 0
        metadata["substate"] = 0
        metadata["work_sha256"] = digest(work)
        metadata["intervention"] = {
            "kind": "focused_2e49c_selector_ccr_edge",
            "source_fixture": str(args.source.resolve()),
            "source_work_sha256": digest(source_work),
            "first_selector": f"{first_selector:04X}",
            "second_selector": f"{second_selector:04X}",
            "incoming_ccr_xnzvc": incoming_ccr,
            "a4": f"{a4:08X}",
            "a7": f"{a7:08X}",
            "expected_final_d0_word": f"{(second_selector << 2) & 0xFFFF:04X}",
        }
        metadata["object_record_hex"] = bytes(
            work[(a4 + offset) & 0xFFFF] for offset in range(0x40)
        ).hex()
        sp = a7 & 0xFFFF
        metadata["stack_window_hex"] = work[
            max(0, sp - 64) : min(0x10000, sp + 16)
        ].hex()

        case_dir = args.output / f"02e49c-{label}"
        case_dir.mkdir()
        (case_dir / "entry.work.bin").write_bytes(work)
        (case_dir / "entry.json").write_text(
            json.dumps(metadata, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        manifest.append(
            {
                "case": case_dir.name,
                "first_selector": f"{first_selector:04X}",
                "second_selector": f"{second_selector:04X}",
                "incoming_ccr_xnzvc": incoming_ccr,
                "a4": f"{a4:08X}",
                "a7": f"{a7:08X}",
                "work_sha256": metadata["work_sha256"],
            }
        )

    (args.output / "manifest.json").write_text(
        json.dumps(
            {
                "scope": (
                    "derived $02E49C selector/CCR/ROM-boundary fixtures "
                    "from one organic target entry; no gameplay/performance claim"
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
    print(f"generated {len(manifest)} $02E49C edge fixtures in {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
