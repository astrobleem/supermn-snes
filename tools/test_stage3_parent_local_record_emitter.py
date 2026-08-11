#!/usr/bin/env python3
"""Regression guard for the parent-local Stage-3 emitter evidence."""

import validate_stage3_parent_local_record_emitter as evidence


def main() -> None:
    report = evidence.collect()
    assert report["result"] == "red"
    assert not report["promotion_eligible"]
    assert report["bounded_three_way"]["result"] == "green"
    assert report["safe_checkpoint_route"]["child_counts"] == {
        "$027AEA": 12,
        "$027B44": 12,
        "$027B7C": 12,
    }
    assert report["fresh_power_on_segment"]["oracle_divergence_count"] == 0
    assert report["fresh_power_on_segment"]["result"] == "green"
    rate = report["sustained_stage3_rate"]
    assert rate["result"] == "red"
    assert rate["native_on_cycles_per_tick"] > rate["budget_cycles_per_tick"]
    print("Stage-3 parent-local record-emitter evidence: fresh segment green, rate red")


if __name__ == "__main__":
    main()
