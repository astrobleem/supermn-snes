#!/usr/bin/env python3
"""Regression guard for the native $027952 -> $027AEA call bridge.

The original 68000 parent performs ``BSR.W $027AEA`` and has a real return at
$027956.  When the guarded Stage-3 parent is native, that child must enter the
guarded table/RTS body directly; sending it through the generic dispatcher
silently falls back because the dispatcher intentionally lacks a global
Stage-3 discriminator.  Gate-off never reaches this source path, and the
callee guard retains its own cold interpreter fallback.
"""

from __future__ import annotations

import argparse
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PARENT_PC = 0x027952
CHILD_PC = 0x027AEA
RETURN_PC = 0x027956
# ``LDA #$7AEA / STA $40 / LDA #$0002 / STA $42 / JML child`` as packed in
# bank $94.  Keep this byte assertion separate from semantic differentials:
# it catches a generator/layout regression before a route probe becomes
# misleadingly quiet again.
DIRECT_TRAILER = bytes.fromhex("a9ea7a8540a9020085425c00c09f")
OLD_DISPATCH_TRAILER = bytes.fromhex("a9ea7a8540a9020085425cb3d100")


def sa1_file_offset(address: int) -> int:
    bank = (address >> 16) & 0xFF
    offset = address & 0xFFFF
    if not 0x92 <= bank <= 0x9F or offset < 0x8000:
        raise ValueError(f"not a packed escape address: ${address:06X}")
    return 0x290000 + (bank - 0x92) * 0x8000 + (offset - 0x8000)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--rom", type=Path)
    args = parser.parse_args()

    program = (ROOT / "data/superman_m68k.bin").read_bytes()
    assert program[PARENT_PC : PARENT_PC + 4] == bytes.fromhex("61000196")
    assert program[RETURN_PC : RETURN_PC + 2] == bytes.fromhex("4a47")

    source = (ROOT / "src" / "escbank2.pasm").read_text(encoding="utf-8")
    marker = "; CALL-BRIDGE bsr.w $27aea -> direct guarded native child;"
    start = source.index(marker)
    end = source.index("br27952_1:", start)
    bridge = source[start:end]
    assert "jml.l $9FC000" in bridge
    assert "jml.l ojmp_hook" not in bridge

    if args.rom is not None:
        rom = args.rom.read_bytes()
        anchor = sa1_file_offset(0x94B600)
        actual = rom.find(DIRECT_TRAILER, anchor, anchor + 0x500)
        assert actual >= anchor, "native $027952 direct-child trailer missing"
        assert rom.find(OLD_DISPATCH_TRAILER, anchor, anchor + 0x500) < 0, (
            "native $027952 still routes $027AEA through ojmp_hook"
        )

    print("Stage-3 $027952 direct $027AEA bridge regression: green")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
