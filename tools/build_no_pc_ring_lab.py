#!/usr/bin/env python3
"""Strip per-fetch PC-ring logging from an explicitly instrumented ROM.

The normal production pack already disables these calls.  This compatibility lab
accepts a ROM built with ``PC_RING=1 bash tools/build_interp.sh`` and replaces only
that three-byte JSR with three NOPs in both ROM mirrors.  It leaves source files and
``build/interp.sfc`` untouched so paired checkpoint measurements can isolate the
diagnostic tax.

This ROM cannot support PC-ring attribution or debugger PC-freeze.  It is a
local performance experiment, not production evidence or an fps result.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_ROM = ROOT / "build/interp.sfc"
CALL_OFFSETS = (0x00EB, 0x80EB)
EXPECTED_CALL = bytes.fromhex("2081e2")  # jsr dbg_fetch ($E281)
NOP_CALL = bytes.fromhex("eaeaea")


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
    for offset in CALL_OFFSETS:
        actual = original[offset : offset + len(EXPECTED_CALL)]
        if actual != EXPECTED_CALL:
            parser.error(
                f"unexpected ifetch bytes at file ${offset:06X}: "
                f"expected {EXPECTED_CALL.hex()}, got {actual.hex()}"
            )

    patched = bytearray(original)
    for offset in CALL_OFFSETS:
        patched[offset : offset + len(NOP_CALL)] = NOP_CALL

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_bytes(patched)
    manifest = {
        "scope": "size-neutral strip of PC_RING=1 checkpoint ROM; not fps",
        "input_rom": str(args.rom.resolve()),
        "input_sha256": sha256(original),
        "output_rom": str(args.output.resolve()),
        "output_sha256": sha256(patched),
        "patches": [
            {
                "file_offset": f"{offset:06X}",
                "before": EXPECTED_CALL.hex(),
                "after": NOP_CALL.hex(),
            }
            for offset in CALL_OFFSETS
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
