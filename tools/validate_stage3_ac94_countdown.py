#!/usr/bin/env python3
"""Prove the legacy countdown unit at the Stage-3 variable-work trigger.

This is deliberately a failure-characterization guard, not a timer-repair
test.  It joins the authenticated native route trace to the original-MAME
``$02E40E`` cycle reduction.  The current ROM's native helper visibly charges
the three basic blocks by 3, 2, and 5 countdown units (one per MC68000
instruction), while the original leaf costs 80 or 94 MC68000 cycles.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
EXPECTED_ROM_SHA256 = "5c7eeb37a1f532180a6c349718ccadb63ab1a30b9af215651b91dd3571c483d9"
DEFAULT_ROM = ROOT / "build" / "interp.sfc"
DEFAULT_TRACE = ROOT / "build" / "trace-stage3-ac94-countdown-current-5c7e-v1"
DEFAULT_MAME_LEDGER = ROOT / "build" / "analyze-stage3-2e40e-cycles-current-5c7e-v1.json"

LOW = 0x00AC
HIGH = 0x00AD
SITES = (("ac94_D548", 3), ("ac94_D567", 2), ("ac94_D586", 5))
HELPER = "ac94_helper"


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def required_restore(summary: dict[str, Any]) -> None:
    restored = dict(summary.get("loaded_state_validation", {}))
    if summary.get("result") != "green":
        raise RuntimeError("countdown route trace did not complete")
    if not (
        restored.get("authenticated")
        and restored.get("public_state_equal")
        and restored.get("sa1_iram_equal")
        and not restored.get("architectural_mutations_before_validation")
    ):
        raise RuntimeError("countdown trace lacks an authenticated non-mutating restore")


def load_events(path: Path) -> list[dict[str, Any]]:
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line
    ]


def validate_trace(summary: dict[str, Any], events: list[dict[str, Any]]) -> list[dict[str, int | str]]:
    """Return the exact countdown transactions at each `$02E40E` block."""

    boundaries = list(summary.get("boundaries", []))
    if not boundaries or int(boundaries[0].get("mame_tick", -1)) != 14743:
        raise RuntimeError("countdown trace does not begin at tick 14743")
    countdown = int(boundaries[0].get("virtual_irq_countdown", -1))
    if countdown != 28667:
        raise RuntimeError(f"unexpected initial legacy countdown: {countdown}")

    # Hooks expose each word store as low then high byte writes.  Model the
    # same starting state the state-authenticated trace observed.
    bytes_at_ac = {LOW: countdown & 0xFF, HIGH: countdown >> 8}
    transactions: list[dict[str, int | str]] = []
    site_cost = dict(SITES)

    for index, event in enumerate(events):
        label = str(event.get("label", ""))
        if label not in site_cost:
            if label == "legacy_ac":
                address = int(event.get("address", -1))
                if address not in bytes_at_ac:
                    raise RuntimeError(f"unexpected legacy countdown address: {address:#x}")
                bytes_at_ac[address] = int(event.get("value", -1)) & 0xFF
            continue

        before = bytes_at_ac[LOW] | (bytes_at_ac[HIGH] << 8)
        expected = [HELPER, "legacy_ac", "legacy_ac"]
        following = events[index + 1 : index + 4]
        if [str(row.get("label", "")) for row in following] != expected:
            raise RuntimeError(f"{label} is not followed by helper and word store")
        helper, low_write, high_write = following
        if int(low_write.get("address", -1)) != LOW or int(high_write.get("address", -1)) != HIGH:
            raise RuntimeError(f"{label} does not store $AC low then high")
        start_cycle = int(event.get("cycleCount", -1))
        deltas = [
            int(helper.get("cycleCount", -1)) - start_cycle,
            int(low_write.get("cycleCount", -1)) - start_cycle,
            int(high_write.get("cycleCount", -1)) - start_cycle,
        ]
        if deltas != [7, 32, 33]:
            raise RuntimeError(f"unexpected native helper timing after {label}: {deltas}")
        after = int(low_write["value"]) | (int(high_write["value"]) << 8)
        charged = (before - after) & 0xFFFF
        if charged != site_cost[label]:
            raise RuntimeError(
                f"{label} charged {charged}, expected {site_cost[label]} instruction units"
            )
        if int(event.get("interval_end_mame_tick", -1)) != 14746:
            raise RuntimeError(f"{label} appeared outside red tick 14746")
        transactions.append(
            {
                "site": label,
                "before": before,
                "after": after,
                "charged_instruction_units": charged,
                "interval_end_mame_tick": 14746,
            }
        )

        # The main loop will visit those writes again, but update the model
        # immediately so a consecutive 3/2/5 block sees the post-helper word.
        bytes_at_ac[LOW] = int(low_write["value"]) & 0xFF
        bytes_at_ac[HIGH] = int(high_write["value"]) & 0xFF

    if len(transactions) != 36:
        raise RuntimeError(f"expected 36 red-tick block charges, got {len(transactions)}")
    expected_sites = [label for _repeat in range(12) for label, _cost in SITES]
    if [str(row["site"]) for row in transactions] != expected_sites:
        raise RuntimeError("red tick did not retain twelve ordered 3/2/5 charge triples")
    return transactions


def validate(rom: Path, trace_dir: Path, mame_ledger: Path) -> dict[str, Any]:
    if sha256(rom) != EXPECTED_ROM_SHA256:
        raise RuntimeError("validator is pinned to the active 5c7e production ROM")
    summary_path = trace_dir / "summary.json"
    events_path = trace_dir / "events.jsonl"
    if not summary_path.is_file() or not events_path.is_file():
        raise RuntimeError(f"incomplete countdown trace artifact: {trace_dir}")
    if not mame_ledger.is_file():
        raise RuntimeError(f"missing exact-MAME leaf ledger: {mame_ledger}")

    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    required_restore(summary)
    if summary.get("rom_sha256") != EXPECTED_ROM_SHA256:
        raise RuntimeError("countdown trace targets a different ROM")
    if int(summary.get("event_count", -1)) != 22836:
        raise RuntimeError("unexpected countdown trace event count")
    events = load_events(events_path)
    if len(events) != int(summary["event_count"]):
        raise RuntimeError("countdown event log is incomplete")
    transactions = validate_trace(summary, events)

    ledger = json.loads(mame_ledger.read_text(encoding="utf-8"))
    if ledger.get("result") != "green" or ledger.get("rules") != {
        "d0_below_7": 80,
        "d0_at_least_7": 94,
    }:
        raise RuntimeError("exact-MAME `$02E40E` leaf ledger changed")
    samples = [row for row in ledger.get("samples", []) if row.get("tick") == 14746]
    if len(samples) != 21:
        raise RuntimeError(f"expected 21 MAME `$02E40E` samples in red tick, got {len(samples)}")
    cycle_counts = {int(row["cycles"]) for row in samples}
    if cycle_counts != {80, 94}:
        raise RuntimeError(f"unexpected exact-MAME leaf costs: {cycle_counts}")

    return {
        "result": "green",
        "scope": (
            "authenticated current-ROM countdown-unit characterization plus exact-MAME "
            "leaf ledger; a green result preserves the mixed-clock failure and does "
            "not accept a timer repair"
        ),
        "rom": str(rom),
        "rom_sha256": EXPECTED_ROM_SHA256,
        "trace": str(trace_dir),
        "trace_summary_sha256": sha256(summary_path),
        "trace_events_sha256": sha256(events_path),
        "mame_ledger": str(mame_ledger),
        "mame_ledger_sha256": sha256(mame_ledger),
        "authenticated_nonmutating_restore": True,
        "initial_legacy_countdown": 28667,
        "red_tick_02e40e_transactions": len(transactions),
        "legacy_instruction_charge_triple": [cost for _site, cost in SITES],
        "exact_mame_leaf_cycles": [80, 94],
        "exact_mame_red_tick_samples": 21,
        "classification": (
            "legacy instruction-count countdown versus MC68000 cycle-clock mismatch; "
            "not a safe native-only `$02E40E` patch because native-off fails too"
        ),
        "timer_fix_accepted": False,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--rom", type=Path, default=DEFAULT_ROM)
    parser.add_argument("--trace", type=Path, default=DEFAULT_TRACE)
    parser.add_argument("--mame-ledger", type=Path, default=DEFAULT_MAME_LEDGER)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        parser.error(f"output already exists: {args.output}")
    report = validate(args.rom.resolve(), args.trace.resolve(), args.mame_ledger.resolve())
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({"result": report["result"], "output": str(args.output.resolve())}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
