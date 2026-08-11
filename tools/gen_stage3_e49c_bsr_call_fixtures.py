#!/usr/bin/env python3
"""Complete the retained $02E49C pre-BSR caller matrix.

Organic Stage-3 capture retained $02E4B8 and $02E524 call boundaries but did
not encounter the sibling $02E4F8 call.  A pre-BSR differential may use the
same legal architectural state at that third instruction: MAME executes the
real BSR bytes, while native-off/on exercise their corresponding dispatch.
This generator preserves every organic case and derives one $02E4F8 case from
each $02E4B8 state.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def write_case(
    output: Path,
    name: str,
    metadata: dict,
    work: bytes,
) -> None:
    case_dir = output / name
    case_dir.mkdir()
    (case_dir / "entry.work.bin").write_bytes(work)
    (case_dir / "entry.json").write_text(
        json.dumps(metadata, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if not args.source.is_dir():
        parser.error(f"missing source fixture directory: {args.source}")
    if args.output.exists():
        parser.error(f"output already exists: {args.output}")

    metadata_paths = sorted(args.source.glob("*/entry.json"))
    if not metadata_paths:
        parser.error("source contains no call fixtures")
    args.output.mkdir(parents=True)
    manifest: list[dict[str, object]] = []
    e4b8_cases: list[tuple[str, dict, bytes]] = []

    for metadata_path in metadata_paths:
        metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
        work = metadata_path.with_name("entry.work.bin").read_bytes()
        if len(work) != 0x10000:
            parser.error(f"short work image: {metadata_path}")
        if digest(work) != metadata["work_sha256"]:
            parser.error(f"work hash mismatch: {metadata_path}")
        name = metadata_path.parent.name
        write_case(args.output, name, metadata, work)
        target = int(str(metadata["target"]), 16)
        manifest.append(
            {
                "case": name,
                "target": f"{target:06X}",
                "kind": "organic",
                "work_sha256": digest(work),
            }
        )
        if target == 0x02E4B8:
            e4b8_cases.append((name, metadata, work))

    if not e4b8_cases:
        parser.error("source lacks $02E4B8 cases to derive")
    for index, (source_name, source_metadata, work) in enumerate(e4b8_cases):
        metadata = json.loads(json.dumps(source_metadata))
        metadata["target"] = "02E4F8"
        metadata["index"] = index
        metadata["intervention"] = {
            "kind": "derived_pre_bsr_caller_boundary",
            "source_case": source_name,
            "source_target": "02E4B8",
            "derived_target": "02E4F8",
            "exact_bsr_bytes": "61A2",
            "semantic_scope": (
                "same legal architectural input at sibling real BSR; "
                "not an organic entry-frequency claim"
            ),
        }
        name = f"02e4f8-derived-{index:02d}"
        write_case(args.output, name, metadata, work)
        manifest.append(
            {
                "case": name,
                "target": "02E4F8",
                "kind": "derived_pre_bsr_boundary",
                "source_case": source_name,
                "work_sha256": digest(work),
            }
        )

    (args.output / "manifest.json").write_text(
        json.dumps(
            {
                "scope": (
                    "complete $02E49C pre-BSR caller matrix: retained organic "
                    "$02E4B8/$02E524 plus derived real-instruction $02E4F8"
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
    print(
        f"generated {len(manifest)} $02E49C pre-BSR fixtures "
        f"in {args.output}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
