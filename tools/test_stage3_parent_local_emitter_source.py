#!/usr/bin/env python3
"""Guard the source-level Stage-3 parent-local child bridges.

The direct leaves are legal only after the native `$027952` parent has rebuilt
the original BSR return.  Keeping them here, instead of `$9D:DA00`, preserves
the Stage-1 interpreter path that shares those child PCs.
"""

from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "src" / "escbank2.pasm"
BINARY = ROOT / "src" / "escbank2.bin"


def main() -> None:
    source = SOURCE.read_text(encoding="utf-8")
    draw = source.index("; CALL-BRIDGE jsr $2e524(pc)")
    first = source.index("; CALL-BRIDGE bsr.w $27b44")
    second = source.index("; CALL-BRIDGE bsr.w $27b7c")
    assert "jml.l $9DE190" in source[draw:first]
    assert "jml.l $94CB40" in source[first:second]
    assert "jml.l $94CEC0" in source[second:source.index("br27952_6:", second)]

    blob = BINARY.read_bytes()
    for address, bridge in (
        (0xB9C0, bytes.fromhex("a924e58540a9020085425c90e19d")),
        (0xBA01, bytes.fromhex("a9447b8540a9020085425c40cb94")),
        (0xBA42, bytes.fromhex("a97c7b8540a9020085425cc0ce94")),
    ):
        offset = address - 0x8000
        assert blob[offset:offset + len(bridge)] == bridge, f"{address:04X}"
    print("Stage-3 parent-local record-emitter source bridges: green")


if __name__ == "__main__":
    main()
