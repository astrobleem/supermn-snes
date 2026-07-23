#!/usr/bin/env python3
"""Build a diagnostic A/B reference with only the $02A86E xlat arm disabled.

The input must be a ``PC_RING=1`` build so ``validate_tick_mame_ab.py`` can
freeze both arms at the exact first $000818 boundary.  The output changes the
immediate operand of the fixed bank-$94 direct arm from $A86E to $FFFF; the
generic xlat lookup then misses that page and retains legal interpretation.

This is an injected semantic-reference ROM, never a production or fps result.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_ROM = ROOT / "build/interp.sfc"
PC_RING_CALL_OFFSETS = (0x00EB, 0x80EB)
EXPECTED_PC_RING_CALL = bytes.fromhex("2081e2")
ARM_IMMEDIATE_OFFSET = 0x2A7911
EXPECTED_ARM_IMMEDIATE = bytes.fromhex("6ea8")
DISABLED_ARM_IMMEDIATE = bytes.fromhex("ffff")


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--rom", type=Path, default=DEFAULT_ROM)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    if not args.rom.is_file():
        parser.error(f"missing input ROM: {args.rom}")
    if args.output.exists():
        parser.error(f"output already exists: {args.output}")

    original = args.rom.read_bytes()
    if len(original) != 0x400000:
        parser.error(f"expected 4 MiB ROM, got {len(original)} bytes")
    for offset in PC_RING_CALL_OFFSETS:
        actual = original[offset : offset + len(EXPECTED_PC_RING_CALL)]
        if actual != EXPECTED_PC_RING_CALL:
            parser.error(
                f"input is not PC_RING=1 at file ${offset:06X}: "
                f"expected {EXPECTED_PC_RING_CALL.hex()}, got {actual.hex()}"
            )
    actual = original[
        ARM_IMMEDIATE_OFFSET : ARM_IMMEDIATE_OFFSET
        + len(EXPECTED_ARM_IMMEDIATE)
    ]
    if actual != EXPECTED_ARM_IMMEDIATE:
        parser.error(
            f"unexpected $02A86E arm bytes at file ${ARM_IMMEDIATE_OFFSET:06X}: "
            f"expected {EXPECTED_ARM_IMMEDIATE.hex()}, got {actual.hex()}"
        )

    patched = bytearray(original)
    patched[
        ARM_IMMEDIATE_OFFSET : ARM_IMMEDIATE_OFFSET
        + len(DISABLED_ARM_IMMEDIATE)
    ] = DISABLED_ARM_IMMEDIATE

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_bytes(patched)
    manifest = {
        "scope": (
            "PC_RING=1 injected A/B reference with only the $02A86E direct "
            "xlat arm disabled; not production and not fps"
        ),
        "input_rom": str(args.rom.resolve()),
        "input_sha256": sha256(original),
        "output_rom": str(args.output.resolve()),
        "output_sha256": sha256(patched),
        "patch": {
            "file_offset": f"{ARM_IMMEDIATE_OFFSET:06X}",
            "before": EXPECTED_ARM_IMMEDIATE.hex(),
            "after": DISABLED_ARM_IMMEDIATE.hex(),
        },
    }
    args.output.with_suffix(args.output.suffix + ".json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(manifest, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
