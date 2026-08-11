#!/usr/bin/env python3
"""Derive deterministic branch/guard fixtures for Stage-3 body $01337E."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path


# label, -$50 flag, -$68 flag, initial -$6C counter, incoming X,
# optional A5/A6/A7 low-word override.
CASES = (
    ("both-flags-zero", 0x0000, 0x0000, 0x0000, 0, None, None, None),
    ("flag50-nonzero", 0x0001, 0x0000, 0x0000, 1, None, None, None),
    ("counter4-to5", 0x0000, 0x0001, 0x0004, 0, None, None, None),
    ("counter5-to6", 0x0000, 0x0001, 0x0005, 1, None, None, None),
    ("counter9-to10", 0x0000, 0x0001, 0x0009, 0, None, None, None),
    ("counter10-to11", 0x0000, 0x0001, 0x000A, 1, None, None, None),
    ("counter-wrap", 0x0000, 0x0001, 0xFFFF, 1, None, None, None),
    ("counter-signed-wrap", 0x0000, 0x0001, 0x7FFF, 0, None, None, None),
    ("signed-flag-decay", 0x0000, 0x8000, 0x000A, 1, None, None, None),
    ("flag50-counter4", 0x0001, 0x0001, 0x0004, 0, None, None, None),
    ("guard-a7-high-edge", 0x0001, 0x0000, 0x0000, 1, None, None, 0x3FFC),
)

A6_WORD_DELTAS = (-0x6C, -0x68, -0x58, -0x50, -0x18)


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def get_be16(work: bytes, address: int) -> int:
    offset = address & 0xFFFF
    return int.from_bytes(work[offset : offset + 2], "big")


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
    if int(str(source["target"]), 16) != 0x01337E:
        parser.error("source is not a $01337E fixture")
    source_work = work_path.read_bytes()
    if len(source_work) != 0x10000:
        parser.error("source work image is not 64 KiB")

    source_a5 = int(source["regs"]["A5"]) & 0xFFFFFFFF
    source_a6 = int(source["regs"]["A6"]) & 0xFFFFFFFF
    source_a7 = int(source["regs"]["A7"]) & 0xFFFFFFFF
    if (
        source_a5 != 0x00F00000
        or source_a6 >> 16 != 0x00F0
        or source_a7 >> 16 != 0x00F0
    ):
        parser.error("source A5/A6/A7 do not have the expected canonical shape")
    callback = get_be32(source_work, source_a5 + 0x1C8A)
    if callback != 0x00000CE4:
        parser.error(f"unexpected organic callback ${callback:08X}")

    args.output.mkdir(parents=True)
    manifest: list[dict[str, object]] = []
    for index, (
        label,
        flag50,
        flag68,
        counter,
        incoming_x,
        a5_low,
        a6_low,
        a7_low,
    ) in enumerate(CASES):
        work = bytearray(source_work)
        metadata = json.loads(json.dumps(source))

        a5 = source_a5 if a5_low is None else 0x00F00000 | a5_low
        a6 = source_a6 if a6_low is None else 0x00F00000 | a6_low
        a7 = source_a7 if a7_low is None else 0x00F00000 | a7_low

        if a5 != source_a5:
            put_be32(work, a5 + 0x1C8A, callback)
        if a6 != source_a6:
            for delta in A6_WORD_DELTAS:
                put_be16(
                    work,
                    a6 + delta,
                    get_be16(source_work, source_a6 + delta),
                )
        if a7 != source_a7:
            put_be32(work, a7, 0x0001337C)

        put_be16(work, a6 - 0x50, flag50)
        put_be16(work, a6 - 0x68, flag68)
        put_be16(work, a6 - 0x6C, counter)

        metadata["index"] = index
        metadata["regs"]["A5"] = a5
        metadata["regs"]["A6"] = a6
        metadata["regs"]["A7"] = a7
        # MOVE.W and the argument setup must preserve nontrivial upper words.
        metadata["regs"]["D0"] = 0xA1A10000 | (
            int(source["regs"]["D0"]) & 0xFFFF
        )
        metadata["regs"]["D1"] = 0xB2B20000 | (
            int(source["regs"]["D1"]) & 0xFFFF
        )
        metadata["regs"]["D2"] = 0xC3C30000 | (
            int(source["regs"]["D2"]) & 0xFFFF
        )
        metadata["sr"] = (int(source["sr"]) & ~0x1F) | (incoming_x << 4)
        metadata["a7"] = f"{a7:08X}"
        metadata["work_sha256"] = digest(work)
        metadata["intervention"] = {
            "kind": "focused_1337e_branch_guard_edge",
            "source_fixture": str(args.source.resolve()),
            "source_work_sha256": digest(source_work),
            "flag_a6_minus_50": f"{flag50:04X}",
            "flag_a6_minus_68": f"{flag68:04X}",
            "counter_a6_minus_6c_initial": f"{counter:04X}",
            "incoming_x": incoming_x,
            "a5": f"{a5:08X}",
            "a6": f"{a6:08X}",
            "a7": f"{a7:08X}",
            "callback": f"{callback:08X}",
            "d0_d1_d2_high_words": ["A1A1", "B2B2", "C3C3"],
        }
        a4 = int(metadata["regs"]["A4"]) & 0xFFFF
        metadata["object_record_hex"] = work[a4 : a4 + 0x40].hex()
        sp = a7 & 0xFFFF
        metadata["stack_window_hex"] = work[
            max(0, sp - 64) : min(0x10000, sp + 16)
        ].hex()

        case_dir = args.output / f"01337e-{label}"
        case_dir.mkdir()
        (case_dir / "entry.work.bin").write_bytes(work)
        (case_dir / "entry.json").write_text(
            json.dumps(metadata, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        manifest.append(
            {
                "case": case_dir.name,
                "flag50": f"{flag50:04X}",
                "flag68": f"{flag68:04X}",
                "counter": f"{counter:04X}",
                "incoming_x": incoming_x,
                "a5": f"{a5:08X}",
                "a6": f"{a6:08X}",
                "a7": f"{a7:08X}",
                "work_sha256": metadata["work_sha256"],
            }
        )

    (args.output / "manifest.json").write_text(
        json.dumps(
            {
                "scope": (
                    "derived $01337E branch, signed-counter, register-residue, "
                    "and canonical guard-edge fixtures from one organic "
                    "PC-ring entry; no gameplay/performance claim"
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
    print(f"generated {len(manifest)} $01337E edge fixtures in {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
