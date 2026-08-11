#!/usr/bin/env python3
"""Inventory legacy per-block charge helpers against a live Stage-3 trace.

This is a static coverage reducer.  A helper call merely establishes that a
bank has an existing block-boundary mechanism; it does not prove that every
active entry reaches one or that its instruction-unit debit is a cycle-accurate
VTIME charge.  The report is therefore planning evidence for the common-clock
work, not a timer or performance acceptance result.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from collections import Counter
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_TRACE = (
    ROOT
    / "build/trace-stage3-active-native-current-5c7e-safe14743-v1.json/trace.json"
)
BANK_SOURCES = {
    0x92: "escbank.pasm",
    0x94: "escbank2.pasm",
    0x97: "escbank3.pasm",
    0x98: "escbank4.pasm",
    0x99: "escbank5.pasm",
    0x95: "escbank6.pasm",
    0x9D: "escbank7.pasm",
    0x9E: "escbank8.pasm",
    0x9F: "escbank9.pasm",
}
CHARGE_CALL = re.compile(r"^\s+jsr(?:\.l)?\s+(esc[0-9]*_?ac_charge(?:_[1-6])?)\s*$", re.MULTILINE)
ENTRY_ADDRESS = re.compile(r"@([0-9A-Fa-f]{6})$")


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def active_banks(trace: dict[str, Any]) -> Counter[int]:
    counts: Counter[int] = Counter()
    for label, count in trace.get("event_counts", {}).items():
        if not int(count) or "@" not in str(label):
            continue
        match = ENTRY_ADDRESS.search(str(label))
        if match is None:
            continue
        bank = int(match.group(1), 16) >> 16
        if bank in BANK_SOURCES:
            counts[bank] += int(count)
    return counts


def audit(trace: dict[str, Any]) -> dict[str, Any]:
    active = active_banks(trace)
    banks: list[dict[str, Any]] = []
    for bank, filename in BANK_SOURCES.items():
        path = ROOT / "src" / filename
        source = path.read_text(encoding="utf-8")
        helpers = CHARGE_CALL.findall(source)
        banks.append(
            {
                "bank": f"{bank:02X}",
                "source": str(path.resolve()),
                "source_sha256": sha256(path),
                "legacy_charge_calls": len(helpers),
                "legacy_charge_helpers": sorted(set(helpers)),
                "active_entry_hits": active[bank],
            }
        )
    active_without_helpers = [
        row["bank"]
        for row in banks
        if row["active_entry_hits"] and not row["legacy_charge_calls"]
    ]
    return {
        "scope": (
            "static native-charge-helper inventory cross-referenced with one "
            "current-ROM Stage-3 entry-labelled native-seam trace; helper presence is not "
            "per-entry reachability, a cycle model, VTIME coverage, rate, or "
            "gameplay acceptance"
        ),
        "trace_rom_sha256": str(trace.get("rom_sha256", "")),
        "trace_active_entry_labelled_seams": sum(
            1
            for label, count in trace.get("event_counts", {}).items()
            if int(count) and "@" in str(label)
        ),
        "trace_active_entry_hits": sum(active.values()),
        "banks": banks,
        "active_banks_without_direct_legacy_charge_helpers": active_without_helpers,
        "current_vtime_native_ledger": ["$97:$025110 only"],
        "promotion_blocked": True,
        "result": "green",
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--trace", type=Path, default=DEFAULT_TRACE)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if not args.trace.is_file():
        parser.error(f"missing trace: {args.trace}")
    if args.output.exists():
        parser.error(f"output exists: {args.output}")
    trace = json.loads(args.trace.read_text(encoding="utf-8"))
    report = audit(trace)
    report["trace"] = str(args.trace.resolve())
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(json.dumps({"result": report["result"], "output": str(args.output)}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
