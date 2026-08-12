#!/usr/bin/env python3
"""Create the exact v7 diagnostic successor with a longer lifetime guard.

The interpreter's production instruction counter is global from boot.  V7
organically reaches the old $08000000 guard near game tick 21,203, where the
guard deliberately writes $CAFE and spins.  This builder authenticates v7 and
changes only the 16-bit high-word threshold in both HiROM mirrors from $0800
to $FFFF.  It does not reset machine state or alter interpreted semantics.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_INPUT = (
    ROOT
    / "build/playback-watcher-20260811/"
    "v7-input-delayed-migrated14745-to14750-v2/run/campaign-rom.sfc"
)
V7_SHA256 = "45c9096dfda3d4203878c18954725ff4814f23f4e28a1e623f3cf07b647e6c72"
PATCH_OFFSETS = (0x005143, 0x00D143)
OLD_THRESHOLD = bytes.fromhex("0008")
NEW_THRESHOLD = bytes.fromhex("ffff")


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", type=Path, default=DEFAULT_INPUT)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    if args.output.exists():
        parser.error(f"output already exists: {args.output}")
    original = args.input.read_bytes()
    if len(original) != 0x400000:
        parser.error(f"expected 4 MiB ROM, got {len(original)} bytes")
    if sha256(original) != V7_SHA256:
        parser.error(
            "refusing non-v7 input: "
            f"{sha256(original)} != {V7_SHA256}"
        )
    for offset in PATCH_OFFSETS:
        actual = original[offset : offset + len(OLD_THRESHOLD)]
        if actual != OLD_THRESHOLD:
            parser.error(
                f"unexpected step-cap threshold at ${offset:06X}: "
                f"{actual.hex()} != {OLD_THRESHOLD.hex()}"
            )

    patched = bytearray(original)
    for offset in PATCH_OFFSETS:
        patched[offset : offset + len(NEW_THRESHOLD)] = NEW_THRESHOLD

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_bytes(patched)
    manifest = {
        "scope": (
            "exact v7 diagnostic successor; interpreter lifetime guard only; "
            "not fresh-boot or production evidence"
        ),
        "input": str(args.input.resolve()),
        "input_sha256": V7_SHA256,
        "output": str(args.output.resolve()),
        "output_sha256": sha256(patched),
        "patches": [
            {
                "file_offset": f"{offset:06X}",
                "before": OLD_THRESHOLD.hex(),
                "after": NEW_THRESHOLD.hex(),
            }
            for offset in PATCH_OFFSETS
        ],
    }
    manifest_path = args.output.with_suffix(args.output.suffix + ".json")
    manifest_path.write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(manifest, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
