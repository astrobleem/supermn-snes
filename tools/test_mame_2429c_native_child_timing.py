#!/usr/bin/env python3
"""Regression guard for the bounded direct-native-child MAME reduction."""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="supermn-2429c-child-mame-") as temporary:
        output = Path(temporary) / "timing.json"
        subprocess.run(
            [
                sys.executable,
                str(ROOT / "tools" / "validate_mame_2429c_native_child_timing.py"),
                "--output",
                str(output),
            ],
            cwd=ROOT,
            check=True,
            capture_output=True,
            text=True,
        )
        report = json.loads(output.read_text(encoding="utf-8"))
    assert report["result"] == "green"
    assert sum(report["observed_counts"].values()) == 124
    assert report["observed_counts"] == {
        "023342": 4, "02334A": 4, "023358": 4, "0235E0": 4,
        "0235F0": 8, "023600": 20, "023632": 20, "02363C": 8,
        "02364C": 4, "023654": 4, "023680": 4, "023E34": 4,
        "023E3C": 4, "0259D6": 16, "025A1C": 16,
    }
    assert len(report["unobserved_dynamic_child_pcs"]) == 4
    print("MAME $02429C direct-native child timing: green (bounded oracle subset)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
