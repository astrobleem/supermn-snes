#!/usr/bin/env python3
"""Regression for the Stage-3 native charge-helper inventory."""

from __future__ import annotations

import json

from audit_native_charge_helpers import DEFAULT_TRACE, audit


def by_bank(report: dict[str, object]) -> dict[str, dict[str, object]]:
    return {row["bank"]: row for row in report["banks"]}  # type: ignore[index]


def main() -> int:
    report = audit(json.loads(DEFAULT_TRACE.read_text(encoding="utf-8")))
    banks = by_bank(report)
    assert report["result"] == "green", report
    assert report["promotion_blocked"], report
    assert report["trace_active_entry_labelled_seams"] == 65, report
    assert banks["92"]["active_entry_hits"] > 0, report
    assert banks["92"]["legacy_charge_calls"] == 0, report
    assert banks["97"]["active_entry_hits"] > 0, report
    assert banks["97"]["legacy_charge_calls"] == 226, report
    assert banks["9F"]["active_entry_hits"] > 0, report
    assert banks["9F"]["legacy_charge_calls"] > 0, report
    assert "92" in report["active_banks_without_direct_legacy_charge_helpers"], report
    print("Stage-3 native charge-helper inventory regression: green")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
