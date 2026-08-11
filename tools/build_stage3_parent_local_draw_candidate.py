#!/usr/bin/env python3
"""Add `$027952`'s `$02E524` child bridge to the parent-local candidate."""

from __future__ import annotations

import argparse
import hashlib
from pathlib import Path

import build_stage3_parent_local_record_emitter_candidate as base


ROOT = Path(__file__).resolve().parents[1]
INPUT_SHA256 = "0453ef75077e24eae188e606532512f25604fa3e84bfeb1954dadbe2b26ceebf"
PARENT_START = 0x2A3600
PARENT_END = 0x2A3B00
OLD = bytes.fromhex("a924e58540a9020085425cb3d100")
NEW = bytes.fromhex("a924e58540a9020085425c90e19d")


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def build_candidate(parent_local: bytes) -> tuple[bytearray, int]:
    if digest(parent_local) != INPUT_SHA256:
        raise RuntimeError("input is not the validated parent-local candidate")
    offsets = [
        offset
        for offset in range(PARENT_START, PARENT_END - len(OLD) + 1)
        if parent_local.startswith(OLD, offset)
    ]
    if offsets != [0x2A39C0]:
        raise RuntimeError(f"expected one parent $02E524 bridge, found {offsets}")
    offset = offsets[0]
    candidate = bytearray(parent_local)
    candidate[offset:offset + len(NEW)] = NEW
    base.set_checksum(candidate)
    allowed = set(range(offset + 11, offset + 14))
    allowed.update(range(base.CHECKSUM_OFFSET, base.CHECKSUM_OFFSET + 4))
    drift = [
        index
        for index, (before, after) in enumerate(zip(parent_local, candidate))
        if before != after and index not in allowed
    ]
    if drift:
        raise RuntimeError(f"unexpected candidate drift: {drift[:8]}")
    return candidate, offset


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        parser.error(f"refusing to overwrite output: {args.output}")
    candidate, offset = build_candidate(args.input.read_bytes())
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_bytes(candidate)
    print(f"stage3_parent_local_draw_candidate output_sha256={digest(candidate)} operand=0x{offset + 11:06X}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
