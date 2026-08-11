#!/usr/bin/env python3
"""Derive genuine pre-JSR fixtures for the two $02E42C call sites."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path


CALL_BY_RETURN = {
    0x0278E6: (0x0278E2, "4EBA6B48"),
    0x02F2DE: (0x02F2DA, "4EBAF150"),
}


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        parser.error(f"output already exists: {args.output}")
    sources = sorted(args.source.glob("02e42c-*/entry.json"))
    if not sources:
        parser.error("--source contains no $02E42C entry fixtures")

    args.output.mkdir(parents=True)
    manifest: list[dict[str, object]] = []
    for index, metadata_path in enumerate(sources):
        metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
        work_path = metadata_path.with_name("entry.work.bin")
        work = work_path.read_bytes()
        if len(work) != 0x10000 or digest(work) != metadata["work_sha256"]:
            parser.error(f"invalid source work image: {work_path}")
        if int(str(metadata["target"]), 16) != 0x02E42C:
            parser.error(f"unexpected source target: {metadata_path}")
        return_pc = int(str(metadata["return_pc"]), 16)
        if return_pc not in CALL_BY_RETURN:
            parser.error(f"unexpected $02E42C caller return ${return_pc:06X}")
        call_pc, opcode = CALL_BY_RETURN[return_pc]

        source_a7 = int(metadata["regs"]["A7"]) & 0xFFFFFFFF
        pre_call_a7 = (source_a7 + 4) & 0xFFFFFFFF
        metadata["target"] = f"{call_pc:06X}"
        metadata["index"] = index
        metadata["regs"]["A7"] = pre_call_a7
        metadata["a7"] = f"{pre_call_a7 & 0xFFFFFF:06X}"
        metadata["intervention"] = {
            "kind": "focused_pre_pcrel_jsr_derivation",
            "source_fixture": str(metadata_path.parent.resolve()),
            "source_target": "02E42C",
            "call_pc": f"{call_pc:06X}",
            "callee": "02E42C",
            "return_pc": f"{return_pc:06X}",
            "opcode": opcode,
            "architectural_state_changes": [
                "PC changed from callee entry to genuine call site",
                "A7 advanced by four to its exact pre-call value",
            ],
            "stack_note": (
                "the stale four bytes below pre-call A7 already equal the "
                "genuine return that the tested JSR overwrites"
            ),
            "source_work_sha256": digest(work),
        }
        a7off = pre_call_a7 & 0xFFFF
        metadata["stack_window_hex"] = work[
            max(0, a7off - 64):min(0x10000, a7off + 16)
        ].hex()

        case_dir = args.output / f"{call_pc:06x}-{index:02d}"
        case_dir.mkdir()
        (case_dir / "entry.work.bin").write_bytes(work)
        (case_dir / "entry.json").write_text(
            json.dumps(metadata, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        manifest.append(
            {
                "case": case_dir.name,
                "call_pc": f"{call_pc:06X}",
                "return_pc": f"{return_pc:06X}",
                "source": str(metadata_path.parent.resolve()),
                "work_sha256": digest(work),
            }
        )

    (args.output / "manifest.json").write_text(
        json.dumps(
            {
                "scope": (
                    "pre-call reconstruction from exact callee-entry states; "
                    "tests genuine PC-relative JSR decode/return materialization"
                ),
                "cases": manifest,
            },
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    print(f"generated {len(manifest)} $02E42C pre-JSR fixtures")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
