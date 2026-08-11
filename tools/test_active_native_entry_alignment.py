#!/usr/bin/env python3
"""Regression for qualifying active-ROM native hook symbols."""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="supermn-active-native-alignment-") as temporary:
        output = Path(temporary) / "report.json"
        subprocess.run(
            [
                sys.executable,
                str(ROOT / "tools" / "validate_active_native_entry_alignment.py"),
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
    assert report["classification_events"] == {
        "approved-production-counter-strip": 4,
        "exact-source-bytes": 236,
    }, report
    assert report["classification_labels"] == {
        "approved-production-counter-strip": 2,
        "exact-source-bytes": 63,
    }, report
    assert report["ignored_nonentry_events"] == [
        "player_x_high_write",
        "player_x_low_write",
    ], report
    assert report["checks"]["approved_counter_strips_are_exactly_the_two_known_sites"], report
    assert "$A100" in (ROOT / "tools" / "validate_active_native_entry_alignment.py").read_text(encoding="utf-8")
    print("active production native-entry symbol alignment: green")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
