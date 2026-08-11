#!/usr/bin/env python3
"""Regression guard for complete bounded `$02429C` fixture timing coverage."""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="supermn-2429c-fixture-timing-") as temporary:
        output = Path(temporary) / "coverage.json"
        subprocess.run(
            [
                sys.executable,
                str(ROOT / "tools" / "validate_mame_2429c_fixture_cycle_coverage.py"),
                "--output",
                str(output),
            ],
            cwd=ROOT,
            check=True,
            capture_output=True,
            text=True,
        )
        report = json.loads(output.read_text(encoding="utf-8"))
    assert report["result"] == "green", report
    assert report["promotion_blocked"] is True, report
    assert report["semantic_triple_differential"] == {
        "fixtures": 4,
        "configurations_per_fixture": 3,
        "green": 12,
        "total": 12,
        "all_register_ccr_stack_work_checks_green": True,
    }, report
    assert report["root_dynamic"]["complete"] is True, report
    assert len(report["root_dynamic"]["expected"]) == 14, report
    assert report["direct_native_child_dynamic"]["complete"] is True, report
    assert len(report["direct_native_child_dynamic"]["expected"]) == 19, report
    assert report["targeted_new_outcomes"] == {
        "fixture": "synthetic-active-child-and-root-alternate-branches",
        "root_024388_observed": True,
        "child_023618_observed": True,
    }, report
    assert "common virtual MC68000 clock" in report["not_proven"], report
    print("$02429C fixture timing coverage regression: green (bounded promotion block retained)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
