#!/usr/bin/env python3
"""Guard VTIME's BW-RAM state against 65816 absolute-address truncation."""

from __future__ import annotations

import argparse
import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SOURCE = ROOT / "src" / "vtime.pasm"
DEFAULT_BINARY = ROOT / "src" / "vtime.bin"

# STZ, INC, and DEC have no 24-bit-addressing encodings on 65816.  If Poppy
# accepts one against a $40:xxxx VTIME symbol, it emits an absolute instruction
# that aliases SA-1 IRAM $xxxx.  Check both source intent and the assembled
# callable code through the delayed-input bridge before the next metadata table.
STATE_LOW_WORDS = tuple(range(0x4000, 0x4028, 2))
ABSOLUTE_MUTATORS = (0x9C, 0xEE, 0xCE)  # STZ abs, INC abs, DEC abs


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", type=Path, default=DEFAULT_SOURCE)
    parser.add_argument("--binary", type=Path, default=DEFAULT_BINARY)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    source = args.source.read_text(encoding="utf-8")
    if re.search(r"^\s*(?:stz|inc|dec)\s+VT_[A-Z_]+", source, re.MULTILINE | re.IGNORECASE):
        raise AssertionError("VTIME source still has an unencodable long state mutator")

    image = args.binary.read_bytes()
    if len(image) < 0x1000:
        raise AssertionError(f"unexpectedly short VTIME image: {len(image)} bytes")
    code = image[:0x3A00]  # $F2:8000-$B9FF, excluding metadata at $BA00
    aliases = []
    for low_word in STATE_LOW_WORDS:
        suffix = low_word.to_bytes(2, "little")
        for opcode in ABSOLUTE_MUTATORS:
            needle = bytes((opcode,)) + suffix
            offset = code.find(needle)
            if offset >= 0:
                aliases.append(f"${0x8000 + offset:04X}:{needle.hex()}")
    if aliases:
        raise AssertionError("VTIME BW-RAM state aliases SA-1 IRAM: " + ", ".join(aliases))

    # State initialization/update paths must use long stores for every field
    # that this regression introduced or previously repaired.
    for low_word in (
        0x400A,
        0x400C,
        0x4014,
        0x4016,
        0x4018,
        0x401A,
    ):
        long_store = bytes((0x8F,)) + low_word.to_bytes(2, "little") + bytes((0x40,))
        if long_store not in code:
            raise AssertionError(f"missing VTIME long store for $40:{low_word:04X}")

    # Ordinary assembly deliberately leaves the delayed-input island zero so
    # its accepted ROM identity does not change. When the VTIME wrapper emits
    # that helper, require long stores for all four of its private fields.
    input_bridge = image[0x3740:0x3A00]  # $F2:B740-$B9FF
    if any(input_bridge):
        for low_word in (0x4020, 0x4022, 0x4024, 0x4026):
            long_store = (
                bytes((0x8F,))
                + low_word.to_bytes(2, "little")
                + bytes((0x40,))
            )
            if long_store not in input_bridge:
                raise AssertionError(
                    f"missing delayed-input long store for $40:{low_word:04X}"
                )
    print("VTIME long state-write regression: green")


if __name__ == "__main__":
    main()
