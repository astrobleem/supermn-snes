#!/usr/bin/env python3
"""Build an exact-entry capture ROM for the native $00C172 coroutine.

The lab replaces the first instruction at SA-1 $94:9D7E with a two-byte
``bra $``.  After an organic checkpoint reaches the native entry, the SA-1
stays on the entry PC so an external pause can capture the untouched register
file and work RAM.  This is a diagnostic ROM only; it cannot advance gameplay
and is never performance or playability evidence.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_ROM = ROOT / "build" / "interp.sfc"
ENTRY = 0x949D7E
FILE_OFFSET = 0x2A0000 + (ENTRY & 0xFFFF) - 0x8000
SPIN = bytes.fromhex("80fe")


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
    source = (ROOT / "src" / "escbank2.bin").read_bytes()
    source_offset = (ENTRY & 0xFFFF) - 0x8000
    expected = source[source_offset : source_offset + len(SPIN)]
    actual = original[FILE_OFFSET : FILE_OFFSET + len(SPIN)]
    if actual != expected:
        parser.error(
            f"ROM/source mismatch at SA-1 ${ENTRY:06X}: "
            f"ROM={actual.hex()} source={expected.hex()}"
        )

    patched = bytearray(original)
    patched[FILE_OFFSET : FILE_OFFSET + len(SPIN)] = SPIN
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_bytes(patched)
    manifest = {
        "scope": "organic exact-entry $C172 capture lab; not fps",
        "input_rom": str(args.rom.resolve()),
        "input_sha256": sha256(original),
        "output_rom": str(args.output.resolve()),
        "output_sha256": sha256(patched),
        "entry": f"{ENTRY:06X}",
        "file_offset": f"{FILE_OFFSET:06X}",
        "before": expected.hex(),
        "after": SPIN.hex(),
    }
    args.output.with_suffix(args.output.suffix + ".json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(manifest, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
