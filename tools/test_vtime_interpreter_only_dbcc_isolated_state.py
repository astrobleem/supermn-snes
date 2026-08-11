#!/usr/bin/env python3
"""Guard the one-shot nonresumable tick-14746 cross-ROM state result."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
EVIDENCE = (
    ROOT
    / "build/playback-watcher-20260809"
    / "vtime-interpreter-only-e00f-gate-restore-scheduler-0818-mvc-fallback-"
    "choke-gate-dbcc-stride-isolated-start-v1"
)
SOURCE_STATE = EVIDENCE / "old-origin/states/snes-tick-14746.mss"
ROM = (
    ROOT
    / "build/interp-vtime-interpreter-only-e00f-gate-restore-scheduler-0818-"
    "mvc-fallback-choke-gate-dbcc-stride-v1.sfc"
)


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> int:
    report = json.loads((EVIDENCE / "watcher-report.json").read_text(encoding="utf-8"))
    assert set(report) == {
        "first_divergence",
        "mismatch_ranges",
        "specific_symptoms",
        "artifact_filenames",
    }
    first = report["first_divergence"]
    assert first["kind"] == "missing exact interpreted game-update boundary"
    assert first["last_completed_mame_tick"] == 14746
    assert first["requested_entries"] == 1
    assert first["observed_entries"] == 0
    assert first["reason"] == "interpreted_game_update_entry_exact_stop_failed"
    assert first["terminal_virtual_pc"] == "F01B6C"
    assert first["terminal_halt"] == 0xDEAD
    assert report["mismatch_ranges"] == []

    symptoms = report["specific_symptoms"]
    assert symptoms["classification"] == "hardware-boundary/timing"
    assert symptoms["timeout_frames"] == 719
    assert symptoms["scope"] == (
        "isolated forensic continuation; no MAME rerun and no oracle comparison"
    )
    failure = json.loads(
        (EVIDENCE / "fixed-interval/failure.json").read_text(encoding="utf-8")
    )
    assert failure["state"]["boundary_kind"] == "ordinary_paused_boundary"
    assert failure["state"]["resumable_checkpoint"] is False
    assert failure["response"]["exactStopTriggered"] is False
    assert failure["response"]["framesAdvanced"] == 719
    assert (EVIDENCE / "harness.exit_status").read_text().strip() == "0"
    assert (EVIDENCE / "isolated-interval.exit_status").read_text().strip() == "1"
    assert sha256(SOURCE_STATE) == (
        "4aa714ecce192ba6a818f03ea75d97a2c990937bbe87dad4f03626dbde0d4a25"
    )
    assert sha256(ROM) == (
        "7583d110bc5226e2fa1479b848b5a2c16d01c2e15f5bbad5a886cee5ea0670e7"
    )
    for filename in report["artifact_filenames"]:
        assert (EVIDENCE / filename).exists(), filename
    print("VTIME DBcc isolated nonresumable-state result: green")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
