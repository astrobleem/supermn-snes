#!/usr/bin/env python3
"""Pin the bounded Stage-3 scheduler-fallback negative and its valid scope."""

from __future__ import annotations

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
RUN_ROOT = ROOT / "build/playback-watcher-20260809"
V1 = (
    RUN_ROOT
    / "vtime-interpreter-only-e00f-gate-restore-scheduler-fallback-seam-v1"
    / "watcher-report.json"
)
V2 = (
    RUN_ROOT
    / "vtime-interpreter-only-e00f-gate-restore-scheduler-fallback-seam-v2"
    / "watcher-report.json"
)


def load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def main() -> None:
    stale = load(V1)
    valid = load(V2)

    stale_rows = stale["specific_symptoms"]["boundaries"]
    assert all(row["gates"]["0736"] == "0x5EEC" for row in stale_rows)
    assert all(row["gates"]["073c"] == "0xA55A" for row in stale_rows)
    assert "no direct path-fired-before-mutation evidence" in (
        stale["specific_symptoms"]["fallback_observability"]["observable"]
    )

    symptom = valid["specific_symptoms"]
    assert symptom["classification"] == (
        "valid ROM-migrated forensic comparison; not fresh-boot or acceptance evidence"
    )
    assert symptom["identity"]["candidate_rom_sha256"] == (
        "60087042d9b0ecc48525258033009a634085deb661899724d917b8df78266ae9"
    )
    assert symptom["identity"]["state_sha256"] == (
        "5ccbc5096c50e301331bd67e382e54c1e4d2afbdd31fd75405f8f5bb4102bfec"
    )
    zero_gates = {name: "0x0000" for name in ("071a", "073a", "0736", "073c")}
    assert all(row["gates"] == zero_gates for row in symptom["boundaries"])
    assert all(row["halt"] == 0 for row in symptom["boundaries"])
    assert [row["task15_equal"] for row in symptom["boundaries"]] == [
        True,
        True,
        False,
        False,
    ]

    first = valid["first_divergence"]
    assert first["kind"] == "authoritative_task15_frame"
    assert first["mame_tick"] == 14746
    assert first["mame"] == {
        "pc": "000259B0",
        "return_pc": "000242BE",
        "saved_sp": "00F001C0",
        "sr": "2400",
    }
    assert first["snes"] == {
        "pc": "0002429C",
        "return_pc": "0000044E",
        "saved_sp": "00F001C4",
        "sr": "2404",
    }
    assert [row["bytes"] for row in valid["mismatch_ranges"]] == [21, 21, 78, 81]
    assert "not directly instrumented" in symptom["fallback_observability"]
    print("interpreter-only Stage-3 scheduler-fallback evidence: green negative")


if __name__ == "__main__":
    main()
