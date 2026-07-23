#!/usr/bin/env python3
"""Build a lab-only conditional debug-freeze ROM for $01F2E4.

The input must be the retained PC_RING=1 reference ROM.  Its ordinary debugger
freeze matches only the fetched 68K PC, but $01F2E4 has more than one caller.
This size-neutral patch redirects the marker setup through the verified-zero
$00:93EE seam and also checks that the real emulated JSR frame returns to
$01:7644.  Other $01F2E4 calls immediately return from dbg_fetch and execute.

This is an exact-fixture capture instrument, never production or FPS evidence.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_ROM = (
    ROOT / "build/playability-20260720/2bda-fast-pc-ring-v1/interp.sfc"
)
PC_RING_CALL_OFFSETS = (0x00EB, 0x80EB)
EXPECTED_PC_RING_CALL = bytes.fromhex("2081e2")
FREEZE_PATCH_OFFSETS = (0x62C6, 0xE2C6)
EXPECTED_FREEZE_SETUP = bytes.fromhex("a901008d12079c1407")
FREEZE_REDIRECT = bytes.fromhex("4cee93eaeaeaeaeaea")
EXTENSION_OFFSETS = (0x13EE, 0x93EE)
EXTENSION = bytes.fromhex(
    # ldx $3c; read/check BE return high word == $0001
    "a63cbf000040ebc90100d016"
    # read/check BE return low word == $7644
    "bf020040ebc94476d00c"
    # matching caller: marker=1, release=0, enter stable df_spin
    "a901008d12079c14074ccfe2"
    # nonmatching caller: restore X and return from dbg_fetch
    "4cd7e2"
)


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
    for offset in FREEZE_PATCH_OFFSETS:
        actual = original[offset : offset + len(EXPECTED_FREEZE_SETUP)]
        if actual != EXPECTED_FREEZE_SETUP:
            parser.error(
                f"unexpected dbg_fetch freeze bytes at file ${offset:06X}: "
                f"expected {EXPECTED_FREEZE_SETUP.hex()}, got {actual.hex()}"
            )
    for offset in EXTENSION_OFFSETS:
        actual = original[offset : offset + len(EXTENSION)]
        if actual != bytes(len(EXTENSION)):
            parser.error(
                f"conditional-freeze seam is not zero at file ${offset:06X}: "
                f"got {actual.hex()}"
            )

    patched = bytearray(original)
    for offset in FREEZE_PATCH_OFFSETS:
        patched[offset : offset + len(FREEZE_REDIRECT)] = FREEZE_REDIRECT
    for offset in EXTENSION_OFFSETS:
        patched[offset : offset + len(EXTENSION)] = EXTENSION

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_bytes(patched)
    manifest = {
        "scope": (
            "PC_RING=1 conditional $01F2E4 debug freeze requiring real "
            "$017644 JSR return; fixture-capture lab only; not fps"
        ),
        "input_rom": str(args.rom.resolve()),
        "input_sha256": sha256(original),
        "output_rom": str(args.output.resolve()),
        "output_sha256": sha256(patched),
        "fetched_pc": "01F2E4",
        "required_stack_return": "00017644",
        "patches": [
            {
                "file_offset": f"{offset:06X}",
                "before": EXPECTED_FREEZE_SETUP.hex(),
                "after": FREEZE_REDIRECT.hex(),
            }
            for offset in FREEZE_PATCH_OFFSETS
        ],
        "extensions": [
            {
                "file_offset": f"{offset:06X}",
                "before": bytes(len(EXTENSION)).hex(),
                "after": EXTENSION.hex(),
            }
            for offset in EXTENSION_OFFSETS
        ],
    }
    args.output.with_suffix(args.output.suffix + ".json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(manifest, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
