#!/usr/bin/env python3
"""Pin the retained synthetic execution result for the VTIME handoff helper."""

from __future__ import annotations

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
REPORT = ROOT / "build/validate-vtime-native-handoff-runtime-v1/summary.json"
ROM_SHA256 = "ace8098e2fd74b739cc735c01e60b0c25c9a05fba9ff1e06e28fe92ab8533792"


def main() -> int:
    report = json.loads(REPORT.read_text(encoding="utf-8"))
    assert report["result"] == "green"
    assert all(report["checks"].values())
    assert report["rom"]["sha256"] == ROM_SHA256
    assert report["helper"] == {"entry": "F2FE40", "no_deadline_stop": "F2FE89"}
    rows = {row["name"]: row for row in report["rows"]}
    assert set(rows) == {"owner_25110", "owner_player", "unknown_owner"}
    for name, owner, debit in (("owner_25110", 3, 14), ("owner_player", 9, 10)):
        row = rows[name]
        assert row["owner"] == owner and row["hit"]["reason"] == "hookFired"
        assert row["before"]["remaining_lo"] - row["after"]["remaining_lo"] == debit
        assert row["after"]["valid"] == 1
        assert row["after"]["pending_block"] == row["after"]["current_block"] == row["after"]["native_owner"] == 0
    unknown = rows["unknown_owner"]
    assert unknown["hit"]["reason"] == "hookFired"
    assert unknown["after"]["valid"] == 0
    assert unknown["after"]["native_owner"] == unknown["owner"] == 0xA5
    print("VTIME native/interpreter handoff runtime regression: green (synthetic, unwired)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
