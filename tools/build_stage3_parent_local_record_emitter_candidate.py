#!/usr/bin/env python3
"""Build a hash-guarded Stage-3 parent-local emitter-route candidate.

Unlike the rejected shared-dispatch experiment, this modifies only the three
existing call bridges inside native `$027952`: its `$027AEA`, `$027B44`, and
`$027B7C` children enter their guarded native wrappers directly.  Interpreted
Stage-1 calls still use the unchanged `$9D:DA00` sparse dispatcher.
"""

from __future__ import annotations

import argparse
import hashlib
from pathlib import Path


ACTIVE_SHA256 = "a9765fbfbd2a0863f093ff1bb887cfd422ecde26e3c46bae0afd56bf8b1dac60"
CHECKSUM_OFFSET = 0xFFDC

BRIDGES = (
    (
        "$027AEA",
        bytes.fromhex("a9ea7a8540a9020085425cb3d100"),
        bytes.fromhex("a9ea7a8540a9020085425c00c09f"),
    ),
    (
        "$027B44",
        bytes.fromhex("a9447b8540a9020085425cb3d100"),
        bytes.fromhex("a9447b8540a9020085425c40cb94"),
    ),
    (
        "$027B7C",
        bytes.fromhex("a97c7b8540a9020085425cb3d100"),
        bytes.fromhex("a97c7b8540a9020085425cc0ce94"),
    ),
)


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def set_checksum(rom: bytearray) -> None:
    rom[CHECKSUM_OFFSET : CHECKSUM_OFFSET + 4] = bytes(4)
    total = sum(rom) & 0xFFFF
    rom[CHECKSUM_OFFSET : CHECKSUM_OFFSET + 2] = ((~total) & 0xFFFF).to_bytes(2, "little")
    rom[CHECKSUM_OFFSET + 2 : CHECKSUM_OFFSET + 4] = total.to_bytes(2, "little")


def build_candidate(active: bytes) -> tuple[bytearray, dict[str, int]]:
    if digest(active) != ACTIVE_SHA256:
        raise RuntimeError("input is not the accepted active a976 ROM")
    candidate = bytearray(active)
    offsets: dict[str, int] = {}
    for label, old, new in BRIDGES:
        count = active.count(old)
        if count != 1:
            raise RuntimeError(f"expected one {label} parent bridge, found {count}")
        offset = active.index(old)
        candidate[offset : offset + len(new)] = new
        offsets[label] = offset
    set_checksum(candidate)

    allowed = set(range(CHECKSUM_OFFSET, CHECKSUM_OFFSET + 4))
    for offset in offsets.values():
        allowed.update(range(offset + 11, offset + 14))
    drift = [
        offset
        for offset, (before, after) in enumerate(zip(active, candidate))
        if before != after and offset not in allowed
    ]
    if drift:
        raise RuntimeError(f"unexpected candidate drift: {drift[:8]}")
    return candidate, offsets


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        parser.error(f"refusing to overwrite output: {args.output}")
    candidate, offsets = build_candidate(args.input.read_bytes())
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_bytes(candidate)
    print(
        "stage3_parent_local_record_emitter_candidate "
        f"input_sha256={ACTIVE_SHA256} output_sha256={digest(candidate)} "
        + " ".join(f"{label}_operand=0x{offset + 11:06X}" for label, offset in offsets.items())
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
