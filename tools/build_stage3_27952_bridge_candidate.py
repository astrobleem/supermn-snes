#!/usr/bin/env python3
"""Create a byte-minimal accepted-ROM candidate for one Stage-3 bridge.

This does not replace ``tools/build_interp.sh`` and must never be promoted as
a source build.  It exists because the accepted production ROM and the current
source candidate differ for the separately blocked virtual-IRQ experiment.
For a bounded route experiment, retain the accepted ROM byte-for-byte except
for the three-byte address operand of the verified ``JML`` at native $027952,
plus the required SNES checksum fields.
"""

from __future__ import annotations

import argparse
import hashlib
from pathlib import Path


OLD = bytes.fromhex("a9ea7a8540a9020085425cb3d100")
NEW = bytes.fromhex("a9ea7a8540a9020085425c00c09f")
# The original candidate was built from the preserved 5c7e predecessor.
# a976 is the current production image: it contains only the separately
# accepted terminal-CCR correction and retains this bridge byte-for-byte.  Do
# not silently accept an arbitrary dirty source build just because the anchor
# happens to occur in it.
ACCEPTED_INPUT_SHA256 = {
    "5c7eeb37a1f532180a6c349718ccadb63ab1a30b9af215651b91dd3571c483d9": "5c7e-predecessor",
    "a9765fbfbd2a0863f093ff1bb887cfd422ecde26e3c46bae0afd56bf8b1dac60": "a976-active",
}
CHECKSUM_OFFSET = 0xFFDC


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def set_checksum(rom: bytearray) -> None:
    """Write the LoROM header complement/checksum after a byte-local patch."""

    rom[CHECKSUM_OFFSET : CHECKSUM_OFFSET + 4] = bytes(4)
    total = sum(rom) & 0xFFFF
    complement = (~total) & 0xFFFF
    rom[CHECKSUM_OFFSET : CHECKSUM_OFFSET + 2] = complement.to_bytes(2, "little")
    rom[CHECKSUM_OFFSET + 2 : CHECKSUM_OFFSET + 4] = total.to_bytes(2, "little")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        parser.error(f"refusing to overwrite output: {args.output}")
    original = args.input.read_bytes()
    observed = digest(original)
    source_name = ACCEPTED_INPUT_SHA256.get(observed)
    if source_name is None:
        parser.error(
            "input identity is not a permitted accepted ROM: "
            f"{observed} not in {', '.join(ACCEPTED_INPUT_SHA256)}"
        )
    count = original.count(OLD)
    if count != 1:
        parser.error(f"expected one old bridge trailer, found {count}")
    offset = original.index(OLD)
    candidate = bytearray(original)
    candidate[offset : offset + len(OLD)] = NEW
    set_checksum(candidate)

    # No pack/layout drift is allowed: the direct JML address and its four
    # checksum bytes are the complete candidate surface.
    # The first eleven bytes are a fixed setup sequence.  Only the 24-bit
    # destination operand of its final JML may differ.
    allowed = set(range(offset + 11, offset + 14))
    allowed.update(range(CHECKSUM_OFFSET, CHECKSUM_OFFSET + 4))
    drift = [
        index
        for index, (before, after) in enumerate(zip(original, candidate))
        if before != after and index not in allowed
    ]
    if drift:
        parser.error(f"unexpected candidate drift outside bridge/checksum: {drift[:8]}")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_bytes(candidate)
    print(
        "stage3_27952_bridge_candidate "
        f"input={source_name} input_sha256={observed} output_sha256={digest(candidate)} "
        f"file_offset=0x{offset:06X} payload_bytes=3 checksum_bytes=4"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
