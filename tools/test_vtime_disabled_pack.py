#!/usr/bin/env python3
"""Assert that a normal ROM cannot execute the VTIME diagnostic path."""

from __future__ import annotations

import argparse
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_ROM = ROOT / "build" / "interp.sfc"
VTIME_ENABLE_FILE_OFFSET = 0x328000  # SA-1 $F2:8000
LEGACY_CONSUME = bytes.fromhex("a5ac3a85ac")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--rom", type=Path, default=DEFAULT_ROM)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    rom = args.rom.read_bytes()
    if len(rom) != 0x400000:
        raise AssertionError(f"unexpected ROM size: {len(rom)}")
    if rom[VTIME_ENABLE_FILE_OFFSET] != 0:
        raise AssertionError("normal ROM has VTIME enabled")
    for offset in (0x00A5, 0x80A5):
        actual = rom[offset : offset + len(LEGACY_CONSUME)]
        if actual != LEGACY_CONSUME:
            raise AssertionError(
                f"legacy countdown seam ${offset:06X} changed: {actual.hex()}"
            )
    print("VTIME disabled-pack regression: green")


if __name__ == "__main__":
    main()
