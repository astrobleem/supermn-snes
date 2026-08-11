#!/usr/bin/env python3
"""Guard the active-ROM Stage-3 fetch-boundary hotspot record.

This is intentionally an artifact regression, not a benchmark.  The retained
profile pauses at every genuine interpreter fetch and can only select future
work; the no-hook checkpoint rate gate remains the performance authority.
"""

from __future__ import annotations

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PROFILE = ROOT / "build/profile-stage3-tick-current-a976-safe14743-v1/profile.json"
ACTIVE_SHA256 = "a9765fbfbd2a0863f093ff1bb887cfd422ecde26e3c46bae0afd56bf8b1dac60"


def main() -> int:
    profile = json.loads(PROFILE.read_text(encoding="utf-8"))
    assert profile["rom_sha256"] == ACTIVE_SHA256, profile
    assert profile["ticks"] == 1, profile
    assert profile["cycles_per_tick"] == 1_936_861.0, profile
    assert profile["frames_per_tick"] == 11.0, profile
    assert profile["genuinely_interpreted_fetches_per_tick"] == 413.0, profile

    fusion = profile["2429c_fusion"]
    assert fusion["entries"] == fusion["hits"] == 1 and fusion["misses"] == 0, fusion
    collision = profile["25110_path"]
    assert collision["entries"] == collision["native_guard_accept"] == 1, collision
    assert collision["stage4_start"] == collision["stage5_wide"] == 1, collision
    assert collision["stage5_select"] == 2, collision
    assert profile["pool_scanners"]["both_entries_observed"] is False, profile

    first = profile["rows"][0]
    assert first["pc"] == "0242BE" and first["cycles"] == 101_454, first
    top_twenty = sum(int(row["cycles"]) for row in profile["rows"][:20])
    assert top_twenty == 781_479 and top_twenty < profile["cycles_per_tick"] // 2, profile
    assert profile["ce4_path_attribution"] == [
        {
            "average_cycles": 10_280.0,
            "cycles": 20_560,
            "cycles_per_tick": 20_560.0,
            "fires": 2,
            "fires_per_tick": 2.0,
            "path": "generic_or_other_hot",
        }
    ], profile
    assert "not fps" in profile["scope"], profile
    print("active a976 Stage-3 fetch-boundary hotspot evidence: retained")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
