#!/usr/bin/env python3
"""Derive genuine pre-BSR fixtures for Stage-3 bank-$02 native leaves."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path


CALL_BY_TARGET_RETURN = {
    (0x027912, 0x0278F2): (0x0278EE, "61000022"),
    (0x027912, 0x0278FC): (0x0278F8, "61000018"),
    (0x02F542, 0x02F478): (0x02F474, "610000CC"),
    (0x02F542, 0x02F50A): (0x02F506, "6100003A"),
}


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--source", type=Path, action="append", required=True
    )
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        parser.error(f"output already exists: {args.output}")

    sources: list[Path] = []
    for directory in args.source:
        sources.extend(sorted(directory.glob("*/entry.json")))
    if not sources:
        parser.error("--source directories contain no entry fixtures")

    args.output.mkdir(parents=True)
    manifest: list[dict[str, object]] = []
    for metadata_path in sources:
        metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
        target = int(str(metadata["target"]), 16)
        return_pc = int(str(metadata["return_pc"]), 16)
        key = (target, return_pc)
        if key not in CALL_BY_TARGET_RETURN:
            continue

        work_path = metadata_path.with_name("entry.work.bin")
        work = work_path.read_bytes()
        if len(work) != 0x10000 or digest(work) != metadata["work_sha256"]:
            parser.error(f"invalid source work image: {work_path}")
        call_pc, opcode = CALL_BY_TARGET_RETURN[key]

        source_a7 = int(metadata["regs"]["A7"]) & 0xFFFFFFFF
        pre_call_a7 = (source_a7 + 4) & 0xFFFFFFFF
        metadata["target"] = f"{call_pc:06X}"
        metadata["regs"]["A7"] = pre_call_a7
        metadata["a7"] = f"{pre_call_a7 & 0xFFFFFF:06X}"
        metadata["intervention"] = {
            "kind": "focused_pre_bsr_derivation",
            "source_fixture": str(metadata_path.parent.resolve()),
            "source_target": f"{target:06X}",
            "call_pc": f"{call_pc:06X}",
            "callee": f"{target:06X}",
            "return_pc": f"{return_pc:06X}",
            "opcode": opcode,
            "architectural_state_changes": [
                "PC changed from callee entry to genuine call site",
                "A7 advanced by four to its exact pre-call value",
            ],
            "stack_note": (
                "the stale four bytes below pre-call A7 already equal the "
                "genuine return that the tested BSR overwrites"
            ),
            "source_work_sha256": digest(work),
        }
        a7off = pre_call_a7 & 0xFFFF
        metadata["stack_window_hex"] = work[
            max(0, a7off - 64):min(0x10000, a7off + 16)
        ].hex()

        case_dir = args.output / (
            f"{call_pc:06x}-{metadata_path.parent.name}"
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
                "call_pc": f"{call_pc:06X}",
                "callee": f"{target:06X}",
                "return_pc": f"{return_pc:06X}",
                "source": str(metadata_path.parent.resolve()),
                "work_sha256": digest(work),
            }
        )

    expected_calls = {call for call, _opcode in CALL_BY_TARGET_RETURN.values()}
    actual_calls = {int(str(case["call_pc"]), 16) for case in manifest}
    if actual_calls != expected_calls:
        parser.error(
            "fixture sources did not cover every bank-$02 call site: "
            f"got {sorted(actual_calls)}, expected {sorted(expected_calls)}"
        )

    (args.output / "manifest.json").write_text(
        json.dumps(
            {
                "scope": (
                    "pre-call reconstruction from exact callee-entry states; "
                    "tests genuine BSR decode, return materialization, and "
                    "the relocated bank-$02 native dispatch extension"
                ),
                "cases": manifest,
            },
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    print(
        f"generated {len(manifest)} bank-$02 Stage-3 pre-BSR fixtures"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
