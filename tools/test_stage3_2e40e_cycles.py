#!/usr/bin/env python3
"""Regression for the exact-MAME `$02E40E` cycle reduction."""

from __future__ import annotations

import analyze_stage3_2e40e_cycles as cycles


def main() -> None:
    report = cycles.reduce(cycles.DEFAULT_ARTIFACT)
    assert report["result"] == "green", report
    assert report["sample_count"] == 72, report
    assert report["cycles_by_path"] == {"80": 28, "94": 44}, report
    failing_tick = [row for row in report["samples"] if row["tick"] == 14746]
    assert len(failing_tick) == 21, report
    assert sum(row["cycles"] == 80 for row in failing_tick) == 7, report
    assert sum(row["cycles"] == 94 for row in failing_tick) == 14, report
    assert all(row["cycles"] in (80, 94) for row in report["samples"]), report
    print("Stage-3 $02E40E exact-MAME cycle regression: green")


if __name__ == "__main__":
    main()
