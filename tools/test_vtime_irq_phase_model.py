#!/usr/bin/env python3
"""Guard the diagnostic modulo-5 clock and MAME VPA entry mapping."""

from __future__ import annotations

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
BOUNDARY = (
    ROOT
    / "build/playback-watcher-20260810"
    / "vtime-interpreter-only-paced0818-dbcc-resume14001-to15500-v1"
    / "focused-y-write-v1/irq-boundary-ledger-v1/irq-boundary-analysis.json"
)
MAME = (
    ROOT
    / "build/playback-watcher-20260811"
    / "vtime-irq-entry-accounting-migrated14500-to14850-v1"
    / "mame-irq-entry-decomposition.json"
)
BASE = 69_650
STEP = 50
DENOMINATOR = 5_743
INITIAL_BUCKET = 1


def reconstruct_interval(
    phase: int,
) -> tuple[int, int]:
    """Mirror the one-time predecessor-checkpoint reconstruction in vtime.pasm."""

    fractional_phase = 0
    interval_carry = 0
    bucket = INITIAL_BUCKET
    while fractional_phase != phase:
        bucket = (bucket + interval_carry) % 5
        fractional_phase += STEP
        if fractional_phase >= DENOMINATOR:
            fractional_phase -= DENOMINATOR
            interval_carry = 1
        else:
            interval_carry = 0
    return bucket, interval_carry


def current_bucket(phase: int, remain: int) -> int:
    start_bucket, interval_extra = reconstruct_interval(phase)
    return (start_bucket + interval_extra - (remain % 5)) % 5


def main() -> None:
    boundary = json.loads(BOUNDARY.read_text(encoding="utf-8"))
    mame = json.loads(MAME.read_text(encoding="utf-8"))

    first_consume = boundary["candidate_interval"]["consumes"][0]
    assert first_consume["phase"] == 2046
    assert first_consume["remain_before"] == BASE
    start_bucket, interval_extra = reconstruct_interval(first_consume["phase"])
    candidate_bucket = current_bucket(
        first_consume["phase"], first_consume["remain_before"]
    )
    assert start_bucket == 4
    assert interval_extra == 0

    # The retained tick-14500 migration carrier is 47 units into phase 1282.
    # Its interval begins at bucket 2 and therefore completes at bucket 4;
    # this is the compact anchor used by the focused migrated probe.
    migrated_start, migrated_extra = reconstruct_interval(1282)
    assert (migrated_start, migrated_extra) == (2, 0)
    assert current_bucket(1282, 69_603) == 4

    first_mame = mame["interruptions"][0]
    assert first_mame["preceding_instruction"]["opcode"] == "60FE"
    instruction_start = boundary["mame_interval"]["start_cycle"]
    instruction_cycles = first_mame["preceding_instruction"]["cycles"]
    completed_mod10 = (instruction_start + instruction_cycles) % 10
    assert completed_mod10 == 9
    assert candidate_bucket == (completed_mod10 - 1) // 2 == 4

    completed_phases = [1, 3, 5, 7, 9]
    entry_units = [27, 26, 25, 29, 28]
    for phase, units in zip(completed_phases, entry_units, strict=True):
        bucket = (phase - 1) // 2
        assert (bucket + units) % 5 == 2
        assert (phase + 2 * units) % 10 == 5

    source = (ROOT / "src/vtime.pasm").read_text(encoding="utf-8")
    assert "VT_CLOCK_INITIAL_PHASE=$0001" in source
    assert "lda #$001B" in source
    assert "vtime_clock_current_phase:" in source
    assert "sbc VT_TMP" in source
    assert "cmp #$0019" in source
    assert "adc #$0005" in source
    assert "vtime_clock_finish_interval:" in source
    assert "vtime_clock_load_next_deadline:" in source
    assert "jmp vtime_load_next_deadline" in source
    consume = source[source.index("vtime_consume_virtual:"):source.index("vtime_consume_end:")]
    assert "vtime_clock_" not in consume
    charge = source[source.index("vtime_charge_units:"):source.index("vtime_charge_units_due:")]
    assert "vtime_clock_" not in charge
    print("VTIME IRQ phase/VPA model regression: green")


if __name__ == "__main__":
    main()
