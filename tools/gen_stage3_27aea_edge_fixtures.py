#!/usr/bin/env python3
"""Derive deterministic semantic/guard edges for Stage-3 leaf $027AEA."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path


CASES = (
    # label, first record word, second record word, second class byte,
    # incoming X, first pointer override
    ("first-nonzero", 0x1234, 0x0000, 0x00, 1, None),
    ("both-zero-x1", 0x0000, 0x0000, 0x80, 1, None),
    ("second-30", 0x0000, 0x0030, 0x00, 0, None),
    ("second-50-x1", 0x0000, 0x0050, 0xFF, 1, None),
    ("second-other-class-zero", 0x0000, 0xAB12, 0x00, 0, None),
    ("second-other-class-positive", 0x0000, 0x0012, 0x35, 1, None),
    ("second-other-class-negative", 0x0000, 0x0012, 0x80, 0, None),
    # Arcade code can address its program ROM here; the attempted word write
    # is ignored. The native path must reject this non-work-RAM destination
    # before changing architectural state and let the interpreter reproduce
    # that behavior.
    ("guard-first-pointer-rom-fallback", 0x0000, 0x0012, 0x35, 1, 0x00010000),
)


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def put_be16(work: bytearray, address: int, value: int) -> None:
    offset = address & 0xFFFF
    work[offset : offset + 2] = (value & 0xFFFF).to_bytes(2, "big")


def put_be32(work: bytearray, address: int, value: int) -> None:
    offset = address & 0xFFFF
    work[offset : offset + 4] = (value & 0xFFFFFFFF).to_bytes(4, "big")


def get_be32(work: bytes, address: int) -> int:
    offset = address & 0xFFFF
    return int.from_bytes(work[offset : offset + 4], "big")


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
    if int(str(source["target"]), 16) != 0x027AEA:
        parser.error("source is not a $027AEA fixture")
    source_work = work_path.read_bytes()
    if len(source_work) != 0x10000:
        parser.error("source work image is not 64 KiB")

    a4 = int(source["regs"]["A4"]) & 0xFFFFFFFF
    a7 = int(source["regs"]["A7"]) & 0xFFFFFFFF
    if a4 >> 16 != 0x00F0 or a7 >> 16 != 0x00F0:
        parser.error("source A4/A7 are not canonical work RAM")
    first_pointer = get_be32(source_work, a4 + 0x18)
    second_pointer = get_be32(source_work, a4 + 0x0E)
    for label, pointer in (
        ("first", first_pointer),
        ("second", second_pointer),
    ):
        if pointer >> 16 != 0x00F0 or (pointer & 0xFFFF) > 0x3FF0:
            parser.error(f"source {label} pointer is not safely mapped")

    args.output.mkdir(parents=True)
    manifest: list[dict[str, object]] = []
    for index, (
        label,
        first_word,
        second_word,
        second_class,
        incoming_x,
        first_override,
    ) in enumerate(CASES):
        work = bytearray(source_work)
        metadata = json.loads(json.dumps(source))

        selected_first = (
            first_pointer if first_override is None else first_override
        )
        put_be32(work, a4 + 0x18, selected_first)
        if selected_first >> 16 == 0x00F0:
            put_be16(work, selected_first + 0x0E, first_word)
        put_be16(work, second_pointer + 0x0E, second_word)
        work[(second_pointer + 0x0D) & 0xFFFF] = second_class

        metadata["index"] = index
        metadata["sr"] = (int(source["sr"]) & ~0x1F) | (incoming_x << 4)
        metadata["work_sha256"] = digest(work)
        metadata["intervention"] = {
            "kind": "focused_27aea_semantic_edge",
            "source_fixture": str(args.source.resolve()),
            "source_work_sha256": digest(source_work),
            "first_pointer": f"{selected_first:08X}",
            "first_record_word": f"{first_word:04X}",
            "second_pointer": f"{second_pointer:08X}",
            "second_record_word": f"{second_word:04X}",
            "second_class_byte": f"{second_class:02X}",
            "incoming_x": incoming_x,
        }
        base = a4 & 0xFFFF
        metadata["object_record_hex"] = work[base : base + 0x40].hex()
        sp = a7 & 0xFFFF
        metadata["stack_window_hex"] = work[
            max(0, sp - 64) : min(0x10000, sp + 16)
        ].hex()

        case_dir = args.output / f"027aea-{label}"
        case_dir.mkdir()
        (case_dir / "entry.work.bin").write_bytes(work)
        (case_dir / "entry.json").write_text(
            json.dumps(metadata, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        manifest.append(
            {
                "case": case_dir.name,
                "first_pointer": f"{selected_first:08X}",
                "first_record_word": f"{first_word:04X}",
                "second_record_word": f"{second_word:04X}",
                "second_class_byte": f"{second_class:02X}",
                "incoming_x": incoming_x,
                "work_sha256": metadata["work_sha256"],
            }
        )

    (args.output / "manifest.json").write_text(
        json.dumps(
            {
                "scope": (
                    "derived semantic/guard edge fixtures from one organic "
                    "$027AEA PC-ring entry; no gameplay/performance claim"
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
    print(f"generated {len(manifest)} $027AEA edge fixtures in {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
