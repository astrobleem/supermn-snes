#!/usr/bin/env python3
"""Derive an interpreter-only VTIME diagnostic from an authenticated image.

The VTIME mode byte is packed at HiROM file offset ``$328000``.  Bit 0 enables
the virtual clock and bit 1 makes unowned gameplay and scheduler shortcuts
decline to the interpreter once the clock has initialized.  This builder
changes only ``$01`` to ``$03`` and records the exact one-byte derivation; it
does not claim the result is playable or promotable.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path


VTIME_ENABLE_OFFSET = 0x328000
ROM_SIZE = 0x400000


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base", type=Path, required=True)
    parser.add_argument("--base-sha256", required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--manifest", type=Path, required=True)
    args = parser.parse_args()
    if not args.base.is_file():
        parser.error(f"missing base ROM: {args.base}")
    for label, path in (("output", args.output), ("manifest", args.manifest)):
        if path.exists():
            parser.error(f"refusing to overwrite {label}: {path}")
    return args


def main() -> int:
    args = parse_args()
    base = args.base.read_bytes()
    base_hash = sha256_bytes(base)
    if len(base) != ROM_SIZE:
        raise RuntimeError(f"expected {ROM_SIZE} bytes, got {len(base)}")
    if base_hash != args.base_sha256.lower():
        raise RuntimeError(
            f"base hash mismatch: expected {args.base_sha256}, got {base_hash}"
        )
    if base[VTIME_ENABLE_OFFSET] != 0x01:
        raise RuntimeError(
            "base is not an enabled normal-VTIME image: "
            f"offset {VTIME_ENABLE_OFFSET:#x} is {base[VTIME_ENABLE_OFFSET]:#04x}"
        )

    candidate = bytearray(base)
    candidate[VTIME_ENABLE_OFFSET] = 0x03
    changed = [
        index
        for index, (before, after) in enumerate(zip(base, candidate))
        if before != after
    ]
    if changed != [VTIME_ENABLE_OFFSET]:
        raise RuntimeError(f"unexpected changed offsets: {changed}")

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_bytes(candidate)
    candidate_hash = sha256_bytes(candidate)
    manifest = {
        "scope": (
            "one-byte interpreter-only VTIME diagnostic derived from an "
            "authenticated normal-VTIME image; not production or gameplay acceptance"
        ),
        "base": {
            "path": str(args.base.resolve()),
            "sha256": base_hash,
            "bytes": len(base),
        },
        "output": {
            "path": str(args.output.resolve()),
            "sha256": candidate_hash,
            "bytes": len(candidate),
        },
        "change": {
            "file_offset": f"{VTIME_ENABLE_OFFSET:06X}",
            "before": "01",
            "after": "03",
            "meaning": (
                "VTIME enabled plus post-initialization interpreter-only "
                "gameplay/scheduler fallback"
            ),
        },
        "changed_bytes": 1,
    }
    args.manifest.parent.mkdir(parents=True, exist_ok=True)
    args.manifest.write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(json.dumps({"output": str(args.output.resolve()), "sha256": candidate_hash, "manifest": str(args.manifest.resolve())}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
