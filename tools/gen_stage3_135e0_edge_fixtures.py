#!/usr/bin/env python3
"""Derive deterministic semantic/guard edges for Stage-3 leaf $0135E0.

The source must be one organically captured active entry.  Derived cases keep
the real register/work-RAM layout and alter only architecturally visible input
state needed to cover the early TST exits, mirrored descriptor transform,
coordinate ADD carry/X behavior, legal A1/A2 aliases, alternate genuine return,
and the native guard's read-only interpreter fallback.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path


CASES = (
    # label, (A1), mirror byte, base word, A2 relation, A0 override, X, return
    ("early-zero-alt-return", 0x0000, 0x00, 0x0040, "original", None, 1, 0x0135D4),
    ("early-negative", 0x8000, 0x00, 0x0040, "original", None, 0, 0x0135AC),
    ("active-carry-alt-return", 0x0001, 0x00, 0xFFFF, "original", None, 0, 0x0135D4),
    ("active-mirrored", 0x0001, 0x80, 0x0040, "original", None, 1, 0x0135AC),
    ("mirrored-carry", 0x0001, 0x80, 0xFFFF, "original", None, 0, 0x0135AC),
    ("a2-alias-a1", 0x0001, 0x00, 0x0040, "a1", None, 1, 0x0135AC),
    ("a2-overlaps-a1-plus-2", 0x0001, 0x00, 0x0040, "a1+2", None, 0, 0x0135AC),
    # $01:FFF4 is readable arcade ROM, but +$0C crosses the native body's
    # bounded descriptor window.  The native entry must reject before writes
    # and restart the original instruction in the interpreter.
    ("guard-a0-boundary-fallback", 0x0001, 0x00, 0x0040, "original", 0x01FFF4, 1, 0x0135D4),
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
    if int(str(source["target"]), 16) != 0x0135E0:
        parser.error("source is not a $0135E0 fixture")
    source_work = work_path.read_bytes()
    if len(source_work) != 0x10000:
        parser.error("source work image is not 64 KiB")

    regs = source["regs"]
    a0 = int(regs["A0"]) & 0xFFFFFFFF
    a1 = int(regs["A1"]) & 0xFFFFFFFF
    a6 = int(regs["A6"]) & 0xFFFFFFFF
    a7 = int(regs["A7"]) & 0xFFFFFFFF
    if a0 >> 16 != 0x0001:
        parser.error(f"source A0 is not bank-$01 arcade ROM: ${a0:08X}")
    for name, address in (("A1", a1), ("A6", a6), ("A7", a7)):
        if address >> 16 != 0x00F0:
            parser.error(f"source {name} is not canonical work RAM: ${address:08X}")

    args.output.mkdir(parents=True)
    manifest: list[dict[str, object]] = []
    for index, (
        label,
        input_word,
        mirror,
        base_word,
        a2_relation,
        a0_override,
        incoming_x,
        return_pc,
    ) in enumerate(CASES):
        work = bytearray(source_work)
        metadata = json.loads(json.dumps(source))

        put_be16(work, a1, input_word)
        work[(a6 - 0x24) & 0xFFFF] = mirror
        put_be16(work, a6 - 0x1E, base_word)
        if a2_relation == "a1":
            a2_pointer = a1
            put_be32(work, a6 - 0x54, a2_pointer)
        elif a2_relation == "a1+2":
            a2_pointer = (a1 + 2) & 0xFFFFFFFF
            put_be32(work, a6 - 0x54, a2_pointer)
        else:
            a2_pointer = int.from_bytes(
                work[(a6 - 0x54) & 0xFFFF : ((a6 - 0x54) & 0xFFFF) + 4],
                "big",
            )
        put_be32(work, a7, return_pc)

        metadata["index"] = index
        metadata["return_pc"] = f"{return_pc:06X}"
        metadata["regs"]["A0"] = a0 if a0_override is None else a0_override
        metadata["sr"] = (int(source["sr"]) & ~0x1F) | (incoming_x << 4)
        metadata["work_sha256"] = digest(work)
        metadata["intervention"] = {
            "kind": "focused_135e0_semantic_edge",
            "source_fixture": str(args.source.resolve()),
            "source_work_sha256": digest(source_work),
            "input_word": f"{input_word:04X}",
            "mirror_byte": f"{mirror:02X}",
            "base_word": f"{base_word:04X}",
            "a2_relation": a2_relation,
            "a2_pointer": f"{a2_pointer:08X}",
            "a0": f"{metadata['regs']['A0']:08X}",
            "incoming_x": incoming_x,
            "other_incoming_ccr_bits": 0,
            "return_pc": f"{return_pc:06X}",
        }
        a4 = int(metadata["regs"]["A4"]) & 0xFFFF
        metadata["object_record_hex"] = bytes(
            work[(a4 + offset) & 0xFFFF] for offset in range(0x40)
        ).hex()
        metadata["stack_window_hex"] = work[
            max(0, (a7 & 0xFFFF) - 64) : min(0x10000, (a7 & 0xFFFF) + 16)
        ].hex()

        case_dir = args.output / f"0135e0-{label}"
        case_dir.mkdir()
        (case_dir / "entry.work.bin").write_bytes(work)
        (case_dir / "entry.json").write_text(
            json.dumps(metadata, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        manifest.append(
            {
                "case": case_dir.name,
                "input_word": f"{input_word:04X}",
                "mirror_byte": f"{mirror:02X}",
                "base_word": f"{base_word:04X}",
                "a2_relation": a2_relation,
                "a0": f"{metadata['regs']['A0']:08X}",
                "incoming_x": incoming_x,
                "return_pc": f"{return_pc:06X}",
                "work_sha256": metadata["work_sha256"],
            }
        )

    (args.output / "manifest.json").write_text(
        json.dumps(
            {
                "scope": (
                    "derived semantic/guard edge fixtures from one organic "
                    "$0135E0 PC-ring entry; no gameplay/performance claim"
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
    print(f"generated {len(manifest)} $0135E0 edge fixtures in {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
