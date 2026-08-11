#!/usr/bin/env python3
"""Focused regression for the Stage-3 VTIME-promotion coverage gate."""

from __future__ import annotations

import json

from audit_stage3_vtime_coverage import DEFAULT_TRACE, audit


def main() -> int:
    trace = json.loads(DEFAULT_TRACE.read_text(encoding="utf-8"))
    rom_sha = "5c7eeb37a1f532180a6c349718ccadb63ab1a30b9af215651b91dd3571c483d9"
    ordinary_report = audit(trace, rom_sha, "ordinary")
    assert ordinary_report["result"] == "green", ordinary_report
    assert ordinary_report["promotion_blocked"], ordinary_report
    assert "entry_25110" in ordinary_report["required_uncovered"], ordinary_report
    report = audit(trace, rom_sha, "esc3")
    assert report["result"] == "green", report
    assert report["promotion_blocked"], report
    assert "entry_25110" not in report["required_uncovered"], report
    for name in (
        "entry_13282t",
        "entry_13314t",
        "entry_1337et",
        "entry_133eat",
        "entry_13468t",
        "entry_13538t",
        "entry_ce4t",
        "entry_swin",
        "entry_swo",
    ):
        assert name in report["required_uncovered"], report
    player_report = audit(
        trace,
        rom_sha,
        "esc3_player",
    )
    assert player_report["result"] == "green", player_report
    assert player_report["promotion_blocked"], player_report
    for name in (
        "entry_13282t",
        "entry_13314t",
        "entry_1337et",
        "entry_133eat",
        "entry_13468t",
        "entry_13538t",
        "entry_25110",
    ):
        assert name not in player_report["required_uncovered"], player_report
    for name in ("entry_2429c", "entry_ce4t", "entry_swin", "entry_swo"):
        assert name in player_report["required_uncovered"], player_report
    print("Stage-3 VTIME promotion-coverage regression: green (promotion blocked)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
