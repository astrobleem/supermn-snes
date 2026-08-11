#!/usr/bin/env python3
"""Create a byte-minimal `$02429C/$0259CA` terminal-TST.B candidate.

The source workspace also contains several explicitly unaccepted VTIME and
escape experiments.  A normal rebuild therefore cannot isolate the two
terminal-CCR repairs for a fresh replay.  This builder starts from the
hash-pinned ordinary ROM and changes only the two native branch sites, their
previously zero-filled bank-$99 tail island, and the SNES checksum fields.
It is validation infrastructure, never a substitute for the source build.
"""

from __future__ import annotations

import argparse
import hashlib
from pathlib import Path


ACCEPTED_SHA256 = "5c7eeb37a1f532180a6c349718ccadb63ab1a30b9af215651b91dd3571c483d9"
CHECKSUM_OFFSET = 0xFFDC

# File offsets are SA-1 bank-$99 offsets $868D/$96E3/$FD00 plus the packed
# $2C0000 bank base.  Each five-byte replacement is size-neutral: the native
# TST.B flag materializer enters the tail island and jumps to the old arm.
PATCHES = (
    (0x2C868D, bytes.fromhex("d0034c2f8b"), bytes.fromhex("4c00fdeaea")),
    (0x2C96E3, bytes.fromhex("d0034c5e98"), bytes.fromhex("4c1cfdeaea")),
    (
        0x2CFD00,
        bytes(0x38),
        bytes.fromhex(
            "64706472646e646029ff00f00a298000f002e6704c9286e6604c2f8b"
            "64706472646e646029ff00f00a298000f002e6704ce896e6604c5e98"
        ),
    ),
)


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def set_checksum(rom: bytearray) -> None:
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
    observed = sha256(original)
    if observed != ACCEPTED_SHA256:
        parser.error(
            "input identity is not the accepted production ROM: "
            f"{observed} != {ACCEPTED_SHA256}"
        )

    candidate = bytearray(original)
    changed = 0
    for offset, old, new in PATCHES:
        actual = bytes(candidate[offset : offset + len(old)])
        if actual != old:
            parser.error(
                f"unexpected bytes at file ${offset:06X}: "
                f"{actual.hex()} != {old.hex()}"
            )
        candidate[offset : offset + len(old)] = new
        changed += len(old)
    header_before = bytes(candidate[CHECKSUM_OFFSET : CHECKSUM_OFFSET + 4])
    set_checksum(candidate)
    header_changed = bytes(candidate[CHECKSUM_OFFSET : CHECKSUM_OFFSET + 4]) != header_before

    # No accidental ROM-pack drift is allowed: only the declared payload and
    # its four checksum bytes may differ from the accepted input.
    allowed = {
        index
        for offset, old, _new in PATCHES
        for index in range(offset, offset + len(old))
    }
    allowed.update(range(CHECKSUM_OFFSET, CHECKSUM_OFFSET + 4))
    drift = [
        index
        for index, (before, after) in enumerate(zip(original, candidate))
        if before != after and index not in allowed
    ]
    if drift:
        parser.error(f"unexpected candidate drift outside payload: {drift[:8]}")

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_bytes(candidate)
    print(
        "2429c_tstb_ccr_candidate "
        f"input_sha256={observed} output_sha256={sha256(candidate)} "
        f"payload_bytes={changed} checksum_changed={header_changed}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
