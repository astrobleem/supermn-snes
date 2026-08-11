#!/usr/bin/env python3
"""Regression guard for the VTIME accelerated-boundary promotion block."""

from __future__ import annotations

import json

from audit_vtime_accelerated_boundaries import DEFAULT_TRACE, audit


def main() -> int:
    trace = json.loads(DEFAULT_TRACE.read_text(encoding="utf-8"))
    expected = "5c7eeb37a1f532180a6c349718ccadb63ab1a30b9af215651b91dd3571c483d9"
    report = audit(trace, expected)
    assert report["result"] == "green", report
    assert report["promotion_blocked"], report
    assert not report["trace_required_missing"], report
    assert len(report["boundaries"]) == 21, report
    assert len(report["uncovered_boundaries"]) == 13, report
    assert len(report["trace_active_entry_labels"]) == 65, report
    assert len(report["trace_unadmitted_entry_labels"]) == 57, report
    for name in ("entry_2e42c", "entry_278e8", "entry_ce4t", "entry_swin"):
        assert name in report["trace_unadmitted_entry_labels"], report
    names = {row["name"] for row in report["uncovered_boundaries"]}
    for name in (
        "move_l_run_collapse",
        "delay_003b84",
        "scheduler_switch_in_000796",
        "idle_pacing_000818",
        "ce4_renderer",
    ):
        assert name in names, report
    assert all(not row["common_clock_covered"] for row in report["boundaries"]), report
    selected = {row["name"] for row in report["selected_ledger_boundaries"]}
    assert "stage3_tick_bridge_02429c" in selected, report
    strategies = {row["name"]: row["required_migration_strategy"] for row in report["boundaries"]}
    assert strategies["move_l_run_collapse"] == "split-at-deadline-or-fallback-to-interpreter", report
    assert strategies["delay_003b84"] == "split-at-deadline-or-fallback-to-interpreter", report
    assert strategies["idle_pacing_000818"] == "observed-video-epoch-to-common-phase-boundary", report
    assert strategies["stage3_tick_bridge_02429c"] == "decoded-path-sensitive-basic-block-ledger", report
    print("VTIME accelerated-boundary inventory regression: green (promotion blocked)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
