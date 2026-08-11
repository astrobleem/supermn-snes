#!/usr/bin/env python3
"""Prevent a partial Stage-3 VTIME ledger from being called a clock repair.

The input is a non-mutating ``trace_player_native_tick.py --all-entry-hooks``
record from the authenticated Stage-3 lineage.  A single trace does not prove
all whole-game paths; it does prove which native/HLE paths the proposed clock
would leave uncharged in this active update.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_TRACE = (
    ROOT
    / "build/trace-stage3-active-native-current-5c7e-safe14743-v1.json/"
    "trace.json"
)
CHARGE_PROFILES = {
    # The ordinary ROM has VTIME disabled.  This profile exists so an auditor
    # cannot mistake a source ledger for an active production clock.
    "ordinary": (),
    # First opt-in diagnostic: only the bank-$97 $025110 ledger.
    "esc3": ("entry_25110",),
    # Later opt-in diagnostic: the $025110 ledger plus the six generated
    # Stage-3 player bodies.  It is still intentionally incomplete.
    "esc3_player": (
        "entry_25110",
        "entry_13282t",
        "entry_13314t",
        "entry_1337et",
        "entry_133eat",
        "entry_13468t",
        "entry_13538t",
    ),
}
REQUIRED_ACTIVE = (
    "entry_13282t",
    "entry_13314t",
    "entry_1337et",
    "entry_133eat",
    "entry_13468t",
    "entry_13538t",
    "entry_2429c",
    "entry_ce4t",
    "entry_swin",
    "entry_swo",
    "entry_25110",
)


def active_entries(trace: dict[str, Any]) -> dict[str, int]:
    """Collapse hook-address aliases while retaining their aggregate hits."""

    entries: dict[str, int] = {}
    for label, count in trace.get("event_counts", {}).items():
        if not int(count) or "@" not in label:
            continue
        name = str(label).split("@", 1)[0]
        if name.startswith("player_"):
            continue
        entries[name] = entries.get(name, 0) + int(count)
    return entries


def is_currently_charged(name: str, prefixes: tuple[str, ...]) -> bool:
    return any(name.startswith(prefix) for prefix in prefixes)


def audit(
    trace: dict[str, Any], expected_rom_sha256: str | None,
    profile: str = "esc3",
) -> dict[str, Any]:
    if profile not in CHARGE_PROFILES:
        raise ValueError(f"unknown VTIME profile: {profile}")
    prefixes = CHARGE_PROFILES[profile]
    rom_sha256 = str(trace.get("rom_sha256", ""))
    entries = active_entries(trace)
    missing = [name for name in REQUIRED_ACTIVE if name not in entries]
    required_uncovered = [
        name
        for name in REQUIRED_ACTIVE
        if name in entries and not is_currently_charged(name, prefixes)
    ]
    active_uncovered = {
        name: count
        for name, count in sorted(entries.items())
        if not is_currently_charged(name, prefixes)
    }
    hash_ok = expected_rom_sha256 is None or rom_sha256 == expected_rom_sha256
    result = "green" if hash_ok and not missing and required_uncovered else "red"
    return {
        "scope": (
            "active-native VTIME coverage inventory for one named diagnostic "
            "profile; establishes whether that incomplete ledger can be "
            "promoted. Not a "
            "cycle model, MAME differential, rate, or gameplay acceptance."
        ),
        "rom_sha256": rom_sha256,
        "expected_rom_sha256": expected_rom_sha256,
        "active_entry_labels": len(entries),
        "active_entry_hits": sum(entries.values()),
        "profile": profile,
        "currently_charged_prefixes": list(prefixes),
        "required_active": list(REQUIRED_ACTIVE),
        "required_missing": missing,
        "required_uncovered": required_uncovered,
        "active_uncovered": active_uncovered,
        "promotion_blocked": bool(required_uncovered),
        "result": result,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--trace", type=Path, default=DEFAULT_TRACE)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--expected-rom-sha256")
    parser.add_argument("--profile", choices=sorted(CHARGE_PROFILES), default="esc3")
    args = parser.parse_args()
    if not args.trace.is_file():
        parser.error(f"missing trace: {args.trace}")
    if args.output.exists():
        parser.error(f"output exists: {args.output}")
    trace = json.loads(args.trace.read_text(encoding="utf-8"))
    report = audit(trace, args.expected_rom_sha256, args.profile)
    report["trace"] = str(args.trace.resolve())
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(json.dumps({"result": report["result"], "output": str(args.output)}))
    return 0 if report["result"] == "green" else 1


if __name__ == "__main__":
    raise SystemExit(main())
