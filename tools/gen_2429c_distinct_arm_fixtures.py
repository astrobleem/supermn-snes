#!/usr/bin/env python3
"""Derive controlled `$02429C` distinct-arm fixtures from an organic entry.

The ordinary Stage-3 movie repeatedly visits only the empty list/object arm.
These fixtures retain the authenticated fresh-lineage entry registers and
work-RAM image, then change only named MC68000 work-RAM fields required to
exercise the unobserved collision-list and root-object branches.  They are
bounded semantic/timing inputs, not organic gameplay evidence or a rate test.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from dataclasses import dataclass
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SOURCE = ROOT / "build/validate-2429c-current-5c7e-live-v1-fixtures"
WORK_SIZE = 0x10000
SOURCE_WORK_SHA256 = "161b44cdd0430ef3e8f191a7653cff58a71790776fac73199d09a1716264a175"


@dataclass(frozen=True)
class Mutation:
    offset: int
    data: bytes
    meaning: str


CASES = (
    (
        "active-child-overlap-and-status-counter",
        (
            Mutation(0x3574, bytes.fromhex("0001"), "activate first $0235E0 outer record"),
            Mutation(0x3576, bytes.fromhex("0020"), "first outer x/minimum"),
            Mutation(0x3578, bytes.fromhex("0040"), "first outer x/maximum"),
            Mutation(0x3556, bytes.fromhex("0001"), "activate first $0235E0 inner record"),
            Mutation(0x3558, bytes.fromhex("0050"), "inner lower bound exceeds outer maximum"),
            Mutation(0x355A, bytes.fromhex("0010"), "inner upper bound is below outer minimum"),
            Mutation(0x357C, bytes.fromhex("0001"), "activate second outer record for pair compare"),
            Mutation(0x357E, bytes.fromhex("0030"), "second outer coordinate exceeds first"),
            Mutation(0x3CB6, bytes.fromhex("01"), "activate first $0259CA record byte"),
            Mutation(0x3CB7, bytes.fromhex("00"), "force post-increment status != 3 at $025A0E"),
        ),
    ),
    (
        "active-root-upper-timer-path",
        (
            Mutation(0x365E + 0x19, bytes.fromhex("01"), "activate first $02429C root object"),
            Mutation(0x365E + 0x16, bytes.fromhex("01"), "select nonzero upper timer path"),
            Mutation(0x365E + 0x10, bytes.fromhex("0000"), "make $0242FE BGT path true"),
            Mutation(0x2932, bytes.fromhex("0002"), "make $024310 BEQ path true"),
        ),
    ),
    (
        "active-root-lower-render-and-expiry-path",
        (
            Mutation(0x365E + 0x19, bytes.fromhex("02"), "activate first root object with state 2"),
            Mutation(0x365E + 0x16, bytes.fromhex("00"), "select zero/lower timer path"),
            Mutation(0x365E + 0x10, bytes.fromhex("0000"), "make $02432C BGT path true"),
            Mutation(0x2932, bytes.fromhex("0002"), "make $02433E BEQ path true"),
            Mutation(0x365E + 0x18, bytes.fromhex("02"), "take $02437E and fall through $024388"),
            Mutation(0x365E + 0x17, bytes.fromhex("01"), "expire counter at $02439A"),
            Mutation(0x1CCC, bytes.fromhex("0000"), "fall through $0243D2 to the final helper"),
        ),
    ),
    (
        "active-child-and-root-alternate-branches",
        (
            # `$02360C` must fall through before `$023618` can execute.  The
            # existing overlap fixture makes $20 > $10 and therefore takes
            # the earlier BGT; this raises only the inner upper bound to take
            # the other real comparison arm.
            Mutation(0x3574, bytes.fromhex("0001"), "activate first $0235E0 outer record"),
            Mutation(0x3576, bytes.fromhex("0020"), "first outer x/minimum"),
            Mutation(0x3578, bytes.fromhex("0040"), "first outer x/maximum"),
            Mutation(0x3556, bytes.fromhex("0001"), "activate first $0235E0 inner record"),
            Mutation(0x3558, bytes.fromhex("0050"), "inner lower bound exceeds outer maximum"),
            Mutation(0x355A, bytes.fromhex("0030"), "inner upper bound admits the $023618 comparison"),
            Mutation(0x357C, bytes.fromhex("0001"), "activate second outer record for pair compare"),
            Mutation(0x357E, bytes.fromhex("0030"), "second outer coordinate exceeds first"),
            Mutation(0x3CB6, bytes.fromhex("01"), "activate first $0259CA record byte"),
            Mutation(0x3CB7, bytes.fromhex("00"), "force post-increment status != 3 at $025A0E"),
            # Root state 1 is active but is not the later CMP.B #2 result, so
            # `$02437E` falls through. State byte 2 then makes `$024388` fall
            # through as well, exercising its distinct BNE timing outcome.
            Mutation(0x365E + 0x19, bytes.fromhex("01"), "activate root object without taking $02437E"),
            Mutation(0x365E + 0x16, bytes.fromhex("00"), "select lower timer path"),
            Mutation(0x365E + 0x10, bytes.fromhex("0000"), "make $02432C BGT path true"),
            Mutation(0x2932, bytes.fromhex("0002"), "make $02433E BEQ path true"),
            Mutation(0x365E + 0x18, bytes.fromhex("02"), "make $024388 BNE path false"),
            Mutation(0x365E + 0x17, bytes.fromhex("01"), "expire counter at $02439A"),
            Mutation(0x1CCC, bytes.fromhex("0000"), "fall through $0243D2 to the final helper"),
        ),
    ),
)


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", type=Path, default=DEFAULT_SOURCE)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    source_meta = args.source / "case-00.json"
    source_work = args.source / "case-00.work.bin"
    if args.output.exists():
        parser.error(f"refusing to overwrite output: {args.output}")
    if not source_meta.is_file() or not source_work.is_file():
        parser.error("source case-00 fixture is missing")
    metadata = json.loads(source_meta.read_text(encoding="utf-8"))
    baseline = source_work.read_bytes()
    if len(baseline) != WORK_SIZE or sha256(source_work) != SOURCE_WORK_SHA256:
        raise RuntimeError("source fixture no longer matches the authenticated organic pre-entry")
    args.output.mkdir(parents=True)
    rows = []
    for index, (name, mutations) in enumerate(CASES):
        work = bytearray(baseline)
        for mutation in mutations:
            end = mutation.offset + len(mutation.data)
            if end > WORK_SIZE:
                raise RuntimeError(f"{name}: mutation outside work RAM")
            work[mutation.offset:end] = mutation.data
        stem = f"case-{index:02d}"
        work_path = args.output / f"{stem}.work.bin"
        work_path.write_bytes(work)
        record = {
            "name": f"synthetic-{name}",
            "tick": metadata["tick"],
            "sr": metadata["sr"],
            "regs": metadata["regs"],
            "work_sha256": sha256(work_path),
            "source": {
                "fixture": str(source_meta.resolve()),
                "work_sha256": SOURCE_WORK_SHA256,
            },
            "mutations": [
                {
                    "address": f"F0{mutation.offset:04X}",
                    "before": baseline[mutation.offset:mutation.offset + len(mutation.data)].hex(),
                    "after": mutation.data.hex(),
                    "meaning": mutation.meaning,
                }
                for mutation in mutations
            ],
        }
        (args.output / f"{stem}.json").write_text(
            json.dumps(record, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
        rows.append(record)
    manifest = {
        "scope": (
            "controlled distinct-arm `$02429C` fixtures derived from one authenticated "
            "organic pre-entry; explicit work-RAM mutations only; not organic gameplay/fps"
        ),
        "source_work_sha256": SOURCE_WORK_SHA256,
        "cases": rows,
    }
    (args.output / "manifest.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(json.dumps({"result": "green", "cases": len(rows), "output": str(args.output)}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
