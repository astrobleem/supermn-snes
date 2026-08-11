#!/usr/bin/env python3
"""Derive alternate-call-site fixtures for the Stage-3 $0135E0 BSR shim.

The organic checkpoint reaches the $0135A8 call repeatedly but not the
alternate $0135D0 call in a practical capture window.  Both callers enter the
same leaf with the same architectural convention.  This generator reuses each
organic pre-BSR state, changes only the injected call PC to $0135D0, and marks
the intervention explicitly.  The three-way validator executes the genuine
arcade BSR opcode at that PC in every configuration.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        parser.error(f"output already exists: {args.output}")

    sources = sorted(args.source.glob("0135a8-*/entry.json"))
    if not sources:
        parser.error("--source contains no 0135a8-*/entry.json fixtures")
    args.output.mkdir(parents=True)
    manifest: list[dict[str, object]] = []
    for index, metadata_path in enumerate(sources):
        work_path = metadata_path.with_name("entry.work.bin")
        work = work_path.read_bytes()
        if len(work) != 0x10000:
            parser.error(f"source work image is not 64 KiB: {work_path}")
        metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
        if int(str(metadata["target"]), 16) != 0x0135A8:
            parser.error(f"unexpected source target: {metadata_path}")
        if digest(work) != metadata["work_sha256"]:
            parser.error(f"source work hash mismatch: {work_path}")

        metadata["target"] = "0135D0"
        metadata["return_pc"] = "0135D4"
        metadata["index"] = index
        metadata["intervention"] = {
            "kind": "focused_alternate_bsr_call_pc",
            "source_fixture": str(metadata_path.parent.resolve()),
            "source_target": "0135A8",
            "derived_target": "0135D0",
            "genuine_opcode": "6100000E",
            "callee": "0135E0",
            "return_pc": "0135D4",
            "architectural_state_changes": ["PC only"],
            "source_work_sha256": digest(work),
        }

        case_dir = args.output / f"0135d0-{index:02d}"
        case_dir.mkdir()
        (case_dir / "entry.work.bin").write_bytes(work)
        (case_dir / "entry.json").write_text(
            json.dumps(metadata, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        manifest.append(
            {
                "case": case_dir.name,
                "source": str(metadata_path.parent.resolve()),
                "work_sha256": digest(work),
            }
        )

    (args.output / "manifest.json").write_text(
        json.dumps(
            {
                "scope": (
                    "focused PC-only derivation of the genuine $0135D0 BSR "
                    "call from organic $0135A8 pre-BSR states; no gameplay or "
                    "fresh-boot claim"
                ),
                "cases": manifest,
            },
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    print(f"generated {len(manifest)} alternate $0135D0 BSR fixtures")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
