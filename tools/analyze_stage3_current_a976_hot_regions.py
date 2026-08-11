#!/usr/bin/env python3
"""Classify the retained active-ROM Stage-3 hotspot sample by source region.

The input is intentionally the fetch-boundary profile, whose rows attribute
the elapsed SA-1 span to the preceding MC68000 PC.  These sums are therefore
lower-bound selection data for logical-PC regions, not native basic-block
costs, FPS, or a claim that a region alone explains the current rate miss.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
PROFILE = ROOT / "build/profile-stage3-tick-current-a976-safe14743-v1/profile.json"
ACTIVE_SHA256 = "a9765fbfbd2a0863f093ff1bb887cfd422ecde26e3c46bae0afd56bf8b1dac60"
REGIONS = (
    (
        "box_and_collision_record_emitters",
        0x027B00,
        0x027C00,
        "shared guarded Stage-3 record-emitter family",
    ),
    (
        "draw_dispatch_and_indirect_callers",
        0x02E40E,
        0x02E55C,
        "draw selector, argument construction, and indirect draw caller family",
    ),
    (
        "task15_2429c_root",
        0x02429C,
        0x0243E4,
        "Stage-3 task-15 root and direct children attributed at their call PC",
    ),
    (
        "scheduler_and_idle",
        0x000700,
        0x000820,
        "scheduler scan/select and idle loop",
    ),
)


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--profile", type=Path, default=PROFILE)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        parser.error(f"refusing to overwrite output: {args.output}")
    return args


def main() -> int:
    args = parse_args()
    profile: dict[str, Any] = json.loads(args.profile.read_text(encoding="utf-8"))
    if profile.get("rom_sha256") != ACTIVE_SHA256:
        raise RuntimeError("profile is not the accepted active a976 production ROM")
    if profile.get("ticks") != 1:
        raise RuntimeError("this reducer expects exactly one retained profile tick")
    total = int(profile["cycles_per_tick"])
    rows = profile["rows"]
    if total <= 0 or not isinstance(rows, list):
        raise RuntimeError("profile does not contain a usable hotspot row set")
    covered_pcs: set[str] = set()
    regions = []
    for name, start, end, meaning in REGIONS:
        selected = [row for row in rows if start <= int(row["pc"], 16) < end]
        cycles = sum(int(row["cycles"]) for row in selected)
        covered_pcs.update(str(row["pc"]) for row in selected)
        regions.append(
            {
                "name": name,
                "logical_pc_range": f"${start:06X}-${end - 1:06X}",
                "meaning": meaning,
                "cycles": cycles,
                "fraction_of_complete_tick": cycles / total,
                "observed_row_count": len(selected),
            }
        )
    row_cycles = sum(int(row["cycles"]) for row in rows)
    accounted = sum(int(row["cycles"]) for row in rows if str(row["pc"]) in covered_pcs)
    report = {
        "scope": (
            "active-ROM one-tick logical-PC hotspot region reduction; rows are "
            "fetch-boundary attribution and establish optimization selection only"
        ),
        "profile": str(args.profile.resolve()),
        "profile_sha256": sha256(args.profile),
        "rom_sha256": profile["rom_sha256"],
        "complete_tick_cycles": total,
        "profiled_row_cycles": row_cycles,
        "profiled_row_fraction_of_complete_tick": row_cycles / total,
        "regions": regions,
        "assigned_profiled_row_cycles": accounted,
        "assigned_fraction_of_complete_tick": accounted / total,
        "unassigned_cycles_in_top_rows": row_cycles - accounted,
        "not_proven": [
            "native 65816 basic-block cost within any listed logical region",
            "that an optimization of one region cures the rate miss",
            "FPS, fresh-boot rate, or common-clock correctness",
        ],
        "result": "green",
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({"result": "green", "output": str(args.output.resolve())}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
