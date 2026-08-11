#!/usr/bin/env python3
"""Keep Stage-3 direct leaves out of the shared sparse dispatcher.

The bank-$02 dispatcher runs during Stage 1 as well as Stage 3.  Exact PC,
canonical pointer, and stack checks are therefore not a stage discriminator:
the rejected ``387855da`` experiment created a long Stage-1 update burst and
missed the fresh tick-2,958 Button 1 response.  A future route must add and
three-way validate an explicit live-stage discriminator before changing this
test deliberately.
"""

from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "src" / "escbank7.pasm"
BINARY = ROOT / "src" / "escbank7.bin"
DISPATCH_START = 0xDA00 - 0x8000
DISPATCH_END = 0xDAF6 - 0x8000

# Long JML operands that must not be admitted by the shared $9D:DA00 island.
UNPROVEN_STAGE3_JMPS = (
    bytes.fromhex("5c00b694"),  # $027952 -> $94:B600
    bytes.fromhex("5c00bc94"),  # $0279D2 -> $94:BC00
    bytes.fromhex("5c00c294"),  # $02F3BA -> $94:C200
    bytes.fromhex("5c00c09f"),  # $027AEA -> $9F:C000
    bytes.fromhex("5c40cb94"),  # $027B44 -> $94:CB40
    bytes.fromhex("5cc0ce94"),  # $027B7C -> $94:CEC0
)


def main() -> None:
    source = SOURCE.read_text(encoding="utf-8")
    assert "xdd_27b44:" not in source
    assert "xdd_27b7c:" not in source
    assert "cmp #$7B44" not in source
    assert "cmp #$7B7C" not in source

    blob = BINARY.read_bytes()[DISPATCH_START:DISPATCH_END]
    assert blob.startswith(bytes.fromhex("c230a542"))
    assert bytes.fromhex("c92049f02ec95649f02d") in blob, (
        "bank-$02 chain no longer falls through after the admitted routes"
    )
    for encoded in UNPROVEN_STAGE3_JMPS:
        assert encoded not in blob, encoded.hex()
    print("Shared sparse dispatcher Stage-3 provenance guard: green")


if __name__ == "__main__":
    main()
