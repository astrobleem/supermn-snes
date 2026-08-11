#!/usr/bin/env python3
"""Regress the variable-work trigger in the current Stage-3 IRQ failure.

This validates the *reproduction*, not a repair.  It reads the authenticated
three-update native-on route trace and proves that the red update has the
extra three `$02E40E` legacy-charge blocks.  The separate exact three-way
gate remains the authority for MAME/native-off/native-on architectural state.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from collections import Counter
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
EXPECTED_ROM_SHA256 = "5c7eeb37a1f532180a6c349718ccadb63ab1a30b9af215651b91dd3571c483d9"
DEFAULT_ROM = ROOT / "build" / "interp.sfc"
DEFAULT_TRACE = ROOT / "build" / "trace-stage3-ac94-callers-current-5c7e-v1"
EXPECTED_TICKS = (14744, 14745, 14746)
HELPER = "ac94_helper"
RED_ONLY = ("ac94_D548", "ac94_D567", "ac94_D586")


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def active_rom_charge_sites(rom: Path) -> list[int]:
    """Return bank-$94 JSR sites that target the stable legacy helper $8022."""

    data = rom.read_bytes()
    bank_start = 0x2A0000
    bank_end = bank_start + 0x8000
    needle = bytes((0x20, 0x22, 0x80))  # JSR $8022
    return [
        0x8000 + (offset - bank_start)
        for offset in range(bank_start, bank_end - len(needle) + 1)
        if data[offset : offset + len(needle)] == needle
    ]


def counts_by_tick(events: list[dict[str, Any]]) -> dict[int, Counter[str]]:
    result: dict[int, Counter[str]] = {
        tick: Counter() for tick in EXPECTED_TICKS
    }
    for event in events:
        tick = int(event.get("interval_end_mame_tick", -1))
        if tick not in result:
            continue
        label = str(event.get("label", ""))
        if label.startswith("ac94_"):
            result[tick][label] += 1
    return result


def validate(rom: Path, trace_dir: Path) -> dict[str, Any]:
    summary_path = trace_dir / "summary.json"
    events_path = trace_dir / "events.jsonl"
    if not summary_path.is_file() or not events_path.is_file():
        raise RuntimeError(f"incomplete trace artifact: {trace_dir}")
    if sha256(rom) != EXPECTED_ROM_SHA256:
        raise RuntimeError("validator is pinned to the active 5c7e production ROM")

    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    restored = dict(summary.get("loaded_state_validation", {}))
    if summary.get("result") != "green":
        raise RuntimeError("route trace did not complete")
    if not (
        restored.get("authenticated")
        and restored.get("public_state_equal")
        and restored.get("sa1_iram_equal")
        and not restored.get("architectural_mutations_before_validation")
    ):
        raise RuntimeError("route trace did not authenticate a non-mutating restore")

    events = [
        json.loads(line)
        for line in events_path.read_text(encoding="utf-8").splitlines()
        if line
    ]
    per_tick = counts_by_tick(events)
    helper_counts = [per_tick[tick][HELPER] for tick in EXPECTED_TICKS]
    if helper_counts != [140, 140, 176]:
        raise RuntimeError(f"unexpected helper counts: {helper_counts}")
    red_only_counts = {
        label: [per_tick[tick][label] for tick in EXPECTED_TICKS]
        for label in RED_ONLY
    }
    if any(counts != [0, 0, 12] for counts in red_only_counts.values()):
        raise RuntimeError(f"unexpected $02E40E block counts: {red_only_counts}")
    if helper_counts[-1] - helper_counts[0] != sum(
        counts[-1] - counts[0] for counts in red_only_counts.values()
    ):
        raise RuntimeError("red helper delta is not wholly accounted for by $02E40E")

    charge_sites = active_rom_charge_sites(rom)
    if len(charge_sites) != 82:
        raise RuntimeError(f"expected 82 active-ROM bank-$94 charge sites, got {len(charge_sites)}")
    for site in (0xD548, 0xD567, 0xD586):
        if site not in charge_sites:
            raise RuntimeError(f"missing expected $02E40E charge site ${site:04X}")

    return {
        "result": "green",
        "scope": (
            "authenticated current-ROM Stage-3 variable-work failure reproduction; "
            "a green result preserves the trigger and does not approve a timer repair"
        ),
        "rom": str(rom),
        "rom_sha256": EXPECTED_ROM_SHA256,
        "trace": str(trace_dir),
        "trace_summary_sha256": sha256(summary_path),
        "trace_events_sha256": sha256(events_path),
        "authenticated_nonmutating_restore": True,
        "active_rom_bank94_legacy_charge_sites": [f"{site:04X}" for site in charge_sites],
        "helper_counts_by_interval_end_tick": dict(zip(EXPECTED_TICKS, helper_counts)),
        "red_only_02e40e_blocks": red_only_counts,
        "classification": (
            "variable-work trigger in a mixed instruction-count/cycle-clock route; "
            "not a native-only or one-leaf root cause"
        ),
        "timer_fix_accepted": False,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--rom", type=Path, default=DEFAULT_ROM)
    parser.add_argument("--trace", type=Path, default=DEFAULT_TRACE)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        parser.error(f"output already exists: {args.output}")
    report = validate(args.rom.resolve(), args.trace.resolve())
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({"result": report["result"], "output": str(args.output.resolve())}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
