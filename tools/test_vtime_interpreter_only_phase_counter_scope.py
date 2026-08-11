#!/usr/bin/env python3
"""Guard the distinction between work `$F01C56` and IRAM `$0760`."""

from __future__ import annotations

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
BASE = (
    ROOT
    / "build/playback-watcher-20260809"
    / "vtime-interpreter-only-e00f-gate-restore-scheduler-0818-mvc-fallback-phase14000-to14250-v1"
)
REPORT = BASE / "mame-compare" / "watcher-report.json"
WRAPPER = BASE / "capture_phase_progression.py"


def main() -> None:
    report = json.loads(REPORT.read_text(encoding="utf-8"))
    first = report["first_divergence"]
    symptoms = report["specific_symptoms"]
    source = WRAPPER.read_text(encoding="utf-8")

    assert first.startswith("NOT_LOCALIZED / NO_NEW_F01C56_LOSS_AT_14001")
    assert "both sides advance one step per target" in first
    assert "separate IRAM $0760 counter observation" in first
    assert "pre-existing one-step candidate offset" in symptoms["phase_words_mame_to_snes"]
    assert "not work F01C56" in symptoms["state"]
    assert "Track the IRAM `$0760` exact-entry counter" in source
    assert '"classification": "first_iram_0760_ordinal_drift"' in source
    assert "first_internal_tick_phase_loss" not in source
    print("interpreter-only phase counters: green scope correction")


if __name__ == "__main__":
    main()
