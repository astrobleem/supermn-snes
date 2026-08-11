#!/usr/bin/env python3
"""Regression guard for the VTIME legacy `$AC` writer inventory."""

from __future__ import annotations

import json
import tempfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]

import audit_vtime_legacy_ac_writers as audit  # noqa: E402


def main() -> None:
    writers = audit.collect()
    unmigrated = [row for row in writers if row["classification"] in audit.UNMIGRATED]
    if len(writers) != 26:
        raise AssertionError(f"expected 26 direct legacy $AC writers, got {len(writers)}")
    if len(unmigrated) != 11:
        raise AssertionError(
            f"expected 11 VTIME-unmigrated $AC writers, got {len(unmigrated)}"
        )
    labels = {(Path(str(row["source"])).name, str(row["label"])) for row in unmigrated}
    required = {
        ("escbank5.pasm", "lh_0818_paced"),
        ("escbank2.pasm", "hce4_leaf_ac_ready"),
        ("escbank8.pasm", "Lfd7be_7"),
    }
    if not required <= labels:
        raise AssertionError(f"missing required unmigrated clock writers: {sorted(required - labels)}")
    with tempfile.TemporaryDirectory() as directory:
        path = Path(directory) / "audit.json"
        report = {
            "writers": writers,
            "unmigrated": unmigrated,
            "common_clock_ready": False,
        }
        path.write_text(json.dumps(report), encoding="utf-8")
        if not path.is_file():
            raise AssertionError("failed to retain audit fixture")
    print("VTIME legacy $AC writer inventory regression: green (promotion blocked)")


if __name__ == "__main__":
    main()
