#!/usr/bin/env python3
"""Reconstruct the rejected Stage-3 record-emitter routing experiment.

The accepted ``a976`` image predates two already-assembled native pieces:

* the guarded $027952 -> $027AEA BSR child bridge; and
* the sparse bank-$02 dispatcher cases for $027B44/$027B7C.

The experiment is deliberately not a production builder: a fresh power-on
replay shows that this shared dispatcher also sees Stage-1 calls.  It is kept
only to reproduce and regression-test the rejected ROM exactly while source
continues to reject ungated Stage-3 routes.  The tool patches only the bounded
experiment bytes into the accepted input and refreshes the SNES header checksum.
"""

from __future__ import annotations

import argparse
import hashlib
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
ACTIVE_SHA256 = "a9765fbfbd2a0863f093ff1bb887cfd422ecde26e3c46bae0afd56bf8b1dac60"
ESC7_FILE_BASE = 0x2E8000
# The preceding ``jmp xdd_bank1`` encodes a 16-bit local destination.  Moving
# the bank-$02 chain grows xdd_bank1 by 18 bytes, so include that one operand
# in the otherwise compact dispatcher replacement window.
DISPATCH_START = 0xDA0F - 0x8000
DISPATCH_END = 0xDB08 - 0x8000
CHECKSUM_OFFSET = 0xFFDC

PARENT_OLD = bytes.fromhex("a9ea7a8540a9020085425cb3d100")
PARENT_NEW = bytes.fromhex("a9ea7a8540a9020085425c00c09f")
OLD_DISPATCH_PREFIX = bytes.fromhex("d6dac90000d04ba540c9bed7")
NEW_DISPATCH_PREFIX = bytes.fromhex(
    "e8dac90000d04ba540c9bed7"
)
NEW_EMITTER_ROUTE_PREFIX = bytes.fromhex(
    "c9447bf009c97c7bd0bc5cc0ce945c40cb94c92049f02ec95649f02d"
)
EMITTER_INSERT = bytes.fromhex("c9447bf009c97c7bd0bc5cc0ce945c40cb94")
EMITTER_INSERT_OFFSET = 0xDA9B - 0x8000 - DISPATCH_START
# The last compact-chain BNE remains targeted at xdd_miss before the inserted
# leaves, so its signed displacement grows by the inserted eighteen bytes.
FINAL_MISS_BRANCH_ACTIVE_OFFSET = 0xDABD - 0x8000 - DISPATCH_START
FINAL_MISS_BRANCH_ACTIVE = 0xA3
FINAL_MISS_BRANCH_REJECTED = 0x91
REJECTED_SHA256 = "387855daec19244788aec05bfaca3b471399844131a768733b3d917a87448219"


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def set_checksum(rom: bytearray) -> None:
    rom[CHECKSUM_OFFSET : CHECKSUM_OFFSET + 4] = bytes(4)
    total = sum(rom) & 0xFFFF
    rom[CHECKSUM_OFFSET : CHECKSUM_OFFSET + 2] = ((~total) & 0xFFFF).to_bytes(
        2, "little"
    )
    rom[CHECKSUM_OFFSET + 2 : CHECKSUM_OFFSET + 4] = total.to_bytes(2, "little")


def build_candidate(active: bytes) -> tuple[bytearray, int]:
    if digest(active) != ACTIVE_SHA256:
        raise RuntimeError("input is not the accepted active a976 ROM")

    parent_count = active.count(PARENT_OLD)
    if parent_count != 1:
        raise RuntimeError(f"expected one old $027952 child bridge, found {parent_count}")
    parent_offset = active.index(PARENT_OLD)

    active_bank = active[ESC7_FILE_BASE : ESC7_FILE_BASE + 0x8000]
    if active_bank[DISPATCH_START : DISPATCH_START + len(OLD_DISPATCH_PREFIX)] != OLD_DISPATCH_PREFIX:
        raise RuntimeError("accepted $9D dispatcher anchor changed")
    active_window = active_bank[DISPATCH_START:DISPATCH_END]
    if active_window[EMITTER_INSERT_OFFSET:EMITTER_INSERT_OFFSET + 3] != bytes.fromhex("c92049"):
        raise RuntimeError("accepted dispatcher emitter-chain anchor changed")
    if active_window[FINAL_MISS_BRANCH_ACTIVE_OFFSET] != FINAL_MISS_BRANCH_ACTIVE:
        raise RuntimeError("accepted dispatcher final-miss branch changed")
    # This is a byte-for-byte reconstruction of the rejected assembler result:
    # moving xdd_bank1 grows the preceding target by 18 bytes, then moves the
    # old bank-$02 chain right by those 18 bytes and consumes only its zero pad.
    dispatcher_window = bytearray(active_window)
    dispatcher_window[0] = NEW_DISPATCH_PREFIX[0]
    shifted = EMITTER_INSERT + active_window[EMITTER_INSERT_OFFSET:]
    dispatcher_window[EMITTER_INSERT_OFFSET:] = shifted[: len(dispatcher_window) - EMITTER_INSERT_OFFSET]
    dispatcher_window[
        FINAL_MISS_BRANCH_ACTIVE_OFFSET + len(EMITTER_INSERT)
    ] = FINAL_MISS_BRANCH_REJECTED
    if dispatcher_window[: len(NEW_DISPATCH_PREFIX)] != NEW_DISPATCH_PREFIX:
        raise RuntimeError("rejected dispatcher prefix reconstruction changed")
    if dispatcher_window[
        EMITTER_INSERT_OFFSET:EMITTER_INSERT_OFFSET + len(NEW_EMITTER_ROUTE_PREFIX)
    ] != NEW_EMITTER_ROUTE_PREFIX:
        raise RuntimeError("rejected sparse-route reconstruction changed")

    candidate = bytearray(active)
    candidate[parent_offset : parent_offset + len(PARENT_NEW)] = PARENT_NEW
    start = ESC7_FILE_BASE + DISPATCH_START
    end = ESC7_FILE_BASE + DISPATCH_END
    candidate[start:end] = dispatcher_window
    set_checksum(candidate)

    if digest(candidate) != REJECTED_SHA256:
        raise RuntimeError("rejected candidate reconstruction hash changed")

    allowed = set(range(parent_offset + 11, parent_offset + 14))
    allowed.update(range(start, end))
    allowed.update(range(CHECKSUM_OFFSET, CHECKSUM_OFFSET + 4))
    drift = [
        offset
        for offset, (before, after) in enumerate(zip(active, candidate))
        if before != after and offset not in allowed
    ]
    if drift:
        raise RuntimeError(f"unexpected candidate drift: {drift[:8]}")
    return candidate, parent_offset


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        parser.error(f"refusing to overwrite output: {args.output}")
    candidate, parent_offset = build_candidate(args.input.read_bytes())
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_bytes(candidate)
    print(
        "rejected_stage3_record_emitter_route_experiment "
        f"input_sha256={ACTIVE_SHA256} output_sha256={digest(candidate)} "
        f"parent_operand_offset=0x{parent_offset + 11:06X} "
        f"dispatcher_window=0x{ESC7_FILE_BASE + DISPATCH_START:06X}-"
        f"0x{ESC7_FILE_BASE + DISPATCH_END - 1:06X}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
