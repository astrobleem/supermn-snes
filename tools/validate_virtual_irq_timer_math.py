#!/usr/bin/env python3
"""Regression-test the proposed fractional virtual-IRQ timer arithmetic.

This validates only the timer representation described in
``docs/current/VIRTUAL_IRQ_TIMING.md``.  It does not alter an emulator or make
any claim that the current ROM implements the representation.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from dataclasses import dataclass
from pathlib import Path


BASE_UNITS = 69650
PHASE_INCREMENT = 50
PHASE_DENOMINATOR = 5743


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


@dataclass
class Timer:
    remaining: int
    phase: int = 0

    def reload(self, overshoot: int = 0) -> int:
        self.phase += PHASE_INCREMENT
        extra, self.phase = divmod(self.phase, PHASE_DENOMINATOR)
        self.remaining = BASE_UNITS + extra - overshoot
        if self.remaining <= 0:
            raise AssertionError("overshoot crossed more than one vblank")
        return self.remaining

    def charge(self, units: int) -> int | None:
        if units <= 0:
            raise AssertionError("timer charge must be positive")
        if units < self.remaining:
            self.remaining -= units
            return None
        overshoot = units - self.remaining
        self.remaining = 0
        return overshoot


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--vblank-report", type=Path, required=True)
    parser.add_argument("--branch-report", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    for label, path in (("vblank report", args.vblank_report), ("branch report", args.branch_report)):
        if not path.is_file():
            parser.error(f"missing {label}: {path}")
    if args.output.exists():
        parser.error(f"output already exists: {args.output}")
    vblank = json.loads(args.vblank_report.read_text(encoding="utf-8"))
    branch = json.loads(args.branch_report.read_text(encoding="utf-8"))
    if vblank.get("result") != "green" or branch.get("result") != "green":
        raise RuntimeError("timer math requires green source oracle reports")
    units = vblank["deadline"]["two_cycle_units"]
    if (
        int(units["integer_units"]) != BASE_UNITS
        or int(units["remainder_numerator"]) != PHASE_INCREMENT
        or int(units["remainder_denominator"]) != PHASE_DENOMINATOR
    ):
        raise RuntimeError("MAME clock report no longer matches the timer representation")

    timer = Timer(remaining=BASE_UNITS)
    reloads = [timer.reload() for _ in range(PHASE_DENOMINATOR)]
    expected_total = BASE_UNITS * PHASE_DENOMINATOR + PHASE_INCREMENT
    phase_checks = {
        "phase_returns_to_zero": timer.phase == 0,
        "one_complete_fractional_period_exact": sum(reloads) == expected_total,
        "exactly_50_extra_two_cycle_units": reloads.count(BASE_UNITS + 1) == PHASE_INCREMENT,
        "all_reload_values_fit_17_bits": max(reloads) < (1 << 17),
        "base_does_not_fit_16_bits": BASE_UNITS > 0xFFFF,
    }

    overshoot_timer = Timer(remaining=3, phase=PHASE_DENOMINATOR - PHASE_INCREMENT)
    overshoot = overshoot_timer.charge(5)
    if overshoot is None:
        raise AssertionError("test fixture did not cross the deadline")
    next_remaining = overshoot_timer.reload(overshoot)
    overshoot_checks = {
        "crossing_charge_records_excess": overshoot == 2,
        "next_deadline_uses_hardware_phase": next_remaining == BASE_UNITS - 1,
        "phase_advanced_despite_late_service": overshoot_timer.phase == 0,
    }

    checks = {
        **phase_checks,
        **overshoot_checks,
        "branch_oracle_is_green": branch.get("checks", {}).get("branch_and_dbcc_cycle_rules_match_trace") is True,
    }
    report = {
        "scope": (
            "pure timer-arithmetic regression for the proposed virtual MC68000 clock; "
            "not evidence that a ROM has implemented or accepted the repair"
        ),
        "inputs": {
            "vblank_report": {"path": str(args.vblank_report.resolve()), "sha256": sha256(args.vblank_report)},
            "branch_report": {"path": str(args.branch_report.resolve()), "sha256": sha256(args.branch_report)},
        },
        "representation": {
            "unit": "two MC68000 cycles",
            "base_units": BASE_UNITS,
            "phase_increment": PHASE_INCREMENT,
            "phase_denominator": PHASE_DENOMINATOR,
            "requires_countdown_high_bit": True,
            "requires_overshoot": True,
        },
        "checks": checks,
        "result": "green" if all(checks.values()) else "red",
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({"result": report["result"], "output": str(args.output)}, sort_keys=True))
    return 0 if report["result"] == "green" else 1


if __name__ == "__main__":
    raise SystemExit(main())
