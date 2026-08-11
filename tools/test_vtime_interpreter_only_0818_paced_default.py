#!/usr/bin/env python3
"""Guard the default VTIME-paced `$0818` path and its fresh bisect."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
EVIDENCE = ROOT / "build/playback-watcher-20260810/fresh-credit-bisect-v1"
FRESH_250 = (
    ROOT
    / "build/playback-watcher-20260810"
    / "vtime-interpreter-only-paced0818-dbcc-fresh-to250-calibrated-v1"
)
RESUME_806 = (
    ROOT
    / "build/playback-watcher-20260810"
    / "vtime-interpreter-only-paced0818-dbcc-resume251-to806-v2"
)
RESUME_1100 = (
    ROOT
    / "build/playback-watcher-20260810"
    / "vtime-interpreter-only-paced0818-dbcc-resume807-to1100-v1"
)
RESUME_3000 = (
    ROOT
    / "build/playback-watcher-20260810"
    / "vtime-interpreter-only-paced0818-dbcc-resume1101-to3000-v2"
)
CANDIDATE = (
    ROOT
    / "build/interp-vtime-interpreter-only-e00f-gate-restore-scheduler-0818-"
    "paced-mvc-fallback-choke-gate-dbcc-stride-v1.sfc"
)


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> int:
    candidate = CANDIDATE.read_bytes()
    assert sha256(CANDIDATE) == (
        "14e920eb84a5ab44bff902b941f8926c42cab11f39e4537a88d2c4ad0e608750"
    )
    assert candidate[0x328000] == 0x03  # enabled + interpreter-only
    assert candidate[0x2CFBB0:0x2CFBC4] == bytes.fromhex(
        "af0080f2290400f0045cc0f5002200fb995c9bf5"
    )
    assert candidate[0x2CFBA1:0x2CFBA6] == bytes.fromhex("2200b4f2ea")
    assert sha256(ROOT / "build/interp.sfc") == (
        "2dadd12cba0f2a90b0bfeef9e6ef4f8722a6ba46650677c59b85eb9087e430dd"
    )

    report = json.loads(
        (EVIDENCE / "watcher-report-v2.json").read_text(encoding="utf-8")
    )
    bracket = report["first_divergence"]["adjacent_bracket"]
    assert bracket["green_credit_side"]["rom_sha256"].startswith("60087042")
    assert bracket["green_credit_side"]["credits"] == 8
    assert bracket["zero_credit_side"]["rom_sha256"].startswith("7a22b819")
    assert bracket["zero_credit_side"]["credits"] == 0
    assert bracket["stage"] == "diagnostic-only $0818 pre-mutation fallback gateway"

    state = json.loads(
        (EVIDENCE / "zero-advance-7a22-report.json").read_text(encoding="utf-8")
    )["specific_symptoms"]["zero_advance_state"]
    assert state["pacing"] == {
        "arm": 0,
        "epoch": 65,
        "last_release": 0,
        "debt": 0,
    }
    assert state["request_ack"] == {"request": 64, "ack": 0}
    assert state["credits"] == 0
    assert state["scpu"]["stopState"] == "Running"
    assert state["sa1"]["stopState"] == "Running"

    calibration = json.loads(
        (
            ROOT
            / "build/playback-watcher-20260810"
            / "vtime-interpreter-only-paced0818-dbcc-credit-calibration-v2"
            / "watcher-report.json"
        ).read_text(encoding="utf-8")
    )
    target = calibration["first_divergence"]["target_row"]
    assert target == {
        "video_frame": 9432,
        "delta_frames": 2179,
        "credits": 8,
        "tick_0760": 168,
        "rng_f0170e": 2716,
    }
    assert calibration["specific_symptoms"]["corrected_credited_wait_frames"] == 3224

    fresh = json.loads(
        (FRESH_250 / "watcher-report.json").read_text(encoding="utf-8")
    )
    assert fresh["first_divergence"] == {
        "kind": "none_through_bounded_run",
        "mame_tick_reached": 250,
        "oracle_divergence_count": 0,
    }
    assert fresh["mismatch_ranges"] == []
    symptoms = fresh["specific_symptoms"]
    assert symptoms["result"] == "partial-green"
    assert symptoms["credited_prompt"]["coin_pulses_accepted"] == "8/8"
    assert symptoms["credited_prompt"]["credited_wait_frames"] == 3224
    assert symptoms["gameplay_origin"] == {
        "mame_tick": 221,
        "mame_rng_0858": 200,
        "requested_entries": 1,
        "observed_entries": 1,
        "route": "interpreted_iram",
        "virtual_pc": "003A92",
    }
    assert symptoms["end"]["mame_tick"] == 250
    assert symptoms["end"]["neutral_gameplay_ticks"] == 29
    assert symptoms["end"]["oracle_divergence_count"] == 0
    checkpoint = symptoms["safe_checkpoint"]
    checkpoint_dir = FRESH_250 / "run/states"
    expected_state_sha = (
        "ba6f04907d203c41ebc788f9349c2020bb84f22d855fc9c2b2e2dfbe38448653"
    )
    expected_iram_sha = (
        "8950c547eec8e31a68cac091fa45c5b3100ce5172b4cef537e91d8de37ce57c7"
    )
    assert checkpoint["resumable_checkpoint"] is True
    assert checkpoint["boundary_kind"] == "post_entry_safe_snes_boundary"
    assert checkpoint["zero_additional_entries"] is True
    safe_events = [
        json.loads(line)
        for line in (FRESH_250 / "run/events.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()
        if json.loads(line).get("event") == "safe_checkpoint"
    ]
    assert len(safe_events) == 1
    assert safe_events[0]["mame_tick"] == 250
    assert safe_events[0]["resume_mame_tick"] == 251
    assert safe_events[0]["resume_context"]["mame_tick_completed"] == 250
    assert safe_events[0]["resume_context"]["resume_mame_tick"] == 251
    assert safe_events[0]["state"]["sha256"] == expected_state_sha
    for suffix in ("", ".repeat-1", ".repeat-2"):
        assert sha256(checkpoint_dir / f"safe-checkpoint-00250{suffix}.mss") == (
            expected_state_sha
        )
        assert sha256(
            checkpoint_dir / f"safe-checkpoint-00250{suffix}.mss.sa1-iram.bin"
        ) == expected_iram_sha

    resume = json.loads(
        (RESUME_806 / "watcher-report.json").read_text(encoding="utf-8")
    )
    assert resume["first_divergence"]["kind"] == (
        "none through resumed MAME tick 806"
    )
    assert resume["first_divergence"]["oracle_divergences"] == 0
    assert resume["mismatch_ranges"] == []
    resume_symptoms = resume["specific_symptoms"]
    assert resume_symptoms["coverage"]["segment_entries"] == (
        "555 requested/observed interpreted entries"
    )
    assert resume_symptoms["coverage"]["cumulative_entries"] == (
        "584/584 including the authenticated 250-tick prefix"
    )
    assert resume_symptoms["terminal"]["halt"] == 0
    assert resume_symptoms["safe_checkpoint"]["resumable"] is True
    expected_806_state_sha = (
        "fe4a54092b40787fa1dffca7f227d7f9312a1542bde487627f99beeda7e066df"
    )
    expected_806_iram_sha = (
        "f5cba5ea913f94b2bc5209da734d1ab9667d6ca2ad3959b2945f012c26fd4a79"
    )
    resume_events = [
        json.loads(line)
        for line in (RESUME_806 / "run/events.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()
        if json.loads(line).get("event") == "safe_checkpoint"
    ]
    assert len(resume_events) == 1
    assert resume_events[0]["mame_tick"] == 806
    assert resume_events[0]["resume_mame_tick"] == 807
    assert resume_events[0]["state"]["sha256"] == expected_806_state_sha
    assert (
        resume_events[0]["state"]["resume_sa1_iram"]["sha256"]
        == expected_806_iram_sha
    )
    resume_states = RESUME_806 / "run/states"
    for suffix in ("", ".repeat-1", ".repeat-2"):
        assert sha256(resume_states / f"safe-checkpoint-00806{suffix}.mss") == (
            expected_806_state_sha
        )
        assert sha256(
            resume_states / f"safe-checkpoint-00806{suffix}.mss.sa1-iram.bin"
        ) == expected_806_iram_sha

    resume_1100 = json.loads(
        (RESUME_1100 / "watcher-report.json").read_text(encoding="utf-8")
    )
    assert resume_1100["first_divergence"]["kind"] == (
        "none through resumed MAME tick 1100"
    )
    assert resume_1100["first_divergence"]["oracle_divergences"] == 0
    assert resume_1100["mismatch_ranges"] == []
    symptoms_1100 = resume_1100["specific_symptoms"]
    assert symptoms_1100["coverage"]["segment_entries"] == (
        "293 requested/observed interpreted entries"
    )
    assert symptoms_1100["coverage"]["cumulative_entries"] == (
        "877/877 including the authenticated prefix"
    )
    assert symptoms_1100["coverage"]["player_reference_green"] == 12
    assert symptoms_1100["coverage"]["player_reference_red"] == 0
    assert symptoms_1100["coverage"]["real_input_transitions"] == 6
    assert symptoms_1100["terminal"]["halt"] == 0
    expected_1100_state_sha = (
        "27207e5f414062e449ffa4dc2712a1607817022b73a5969a5b1613fd5f0fbef9"
    )
    expected_1100_iram_sha = (
        "5cb96e4f00177531b7ff0c4f1c0df4ff1192d2e77d891064d85359734b8d35a7"
    )
    events_1100 = [
        json.loads(line)
        for line in (RESUME_1100 / "run/events.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()
        if json.loads(line).get("event") == "safe_checkpoint"
    ]
    assert len(events_1100) == 1
    assert events_1100[0]["mame_tick"] == 1100
    assert events_1100[0]["resume_mame_tick"] == 1101
    assert events_1100[0]["state"]["sha256"] == expected_1100_state_sha
    assert (
        events_1100[0]["state"]["resume_sa1_iram"]["sha256"]
        == expected_1100_iram_sha
    )
    states_1100 = RESUME_1100 / "run/states"
    for suffix in ("", ".repeat-1", ".repeat-2"):
        assert sha256(states_1100 / f"safe-checkpoint-01100{suffix}.mss") == (
            expected_1100_state_sha
        )
        assert sha256(
            states_1100 / f"safe-checkpoint-01100{suffix}.mss.sa1-iram.bin"
        ) == expected_1100_iram_sha

    resume_3000 = json.loads(
        (RESUME_3000 / "watcher-report.json").read_text(encoding="utf-8")
    )
    assert resume_3000["first_divergence"] is None
    assert resume_3000["mismatch_ranges"] == []
    symptoms_3000 = resume_3000["specific_symptoms"]
    assert symptoms_3000["result"] == "partial-green"
    assert symptoms_3000["harness_exit_status"] == 0
    assert symptoms_3000["emulator_launched"] is True
    assert symptoms_3000["nexen_managed_dll_sha256"] == (
        "7e15c1d8ac5157be5df8c6419ffc91ee84f662454c0a15d4edde457258e3ebc6"
    )
    assert symptoms_3000["resume_mame_tick"] == 1101
    assert symptoms_3000["mame_end_tick_reached"] == 3000
    assert symptoms_3000["segment_entries"]["requested"] == 1899
    assert symptoms_3000["segment_entries"]["observed"] == 1899
    cumulative = symptoms_3000[
        "cumulative_lineage_entries_from_calibrated_tick250"
    ]
    assert cumulative == {"requested": 2776, "observed": 2776}
    assert symptoms_3000["oracle_divergences"] == 0
    assert symptoms_3000["player_references"] == {"green": 168, "red": 0}
    assert symptoms_3000["input_transitions"] == 84
    assert symptoms_3000["death_references"] == {"green": 2, "red": 0}
    assert symptoms_3000["end"]["halt"] == 0
    assert symptoms_3000["end"]["minimum_task_stack_margin"] == 138
    assert (RESUME_3000 / "harness.exit_status").read_text().strip() == "0"

    expected_checkpoints = {
        1500: (
            "2bc18e328d81931d1fa977507f26cf4f778de4d6f23d2b54d6be67948d93e05a",
            "4111d2d5f73ee72fa46523cb56ec29178f7d7265d5077a9ec78d345e5c623166",
        ),
        2000: (
            "54f7f81b398a5a5ed60faca867636eac523512613af61c5e1b314bad4533b7e0",
            "60e8d4095a32d57ee230991d6001c3646de48ab29c165d5dee4482c3a47accbf",
        ),
        2500: (
            "dbd37db11e1c422f78ce71196d20666c7ed313750cd6d9fe5fa1a7fe63a6515e",
            "d07474ebc9d89c7635545e7badd2efe0b4dc147b11a6227d0721fda6a22d79b0",
        ),
        3000: (
            "47dc58a19558fa1a9c2ccea0f251d0ba199d4f6d0e721419efbd8bac810a45e8",
            "4ee691019a2dbaa913f337532d64d5a0c663fa4986d24bb0d2071d7667ccfe8c",
        ),
    }
    checkpoint_rows = symptoms_3000["checkpoints"]
    assert {int(tick) for tick in checkpoint_rows} == set(expected_checkpoints)
    safe_events_3000 = {
        int(row["mame_tick"]): row
        for row in (
            json.loads(line)
            for line in (RESUME_3000 / "run/events.jsonl")
            .read_text(encoding="utf-8")
            .splitlines()
        )
        if row.get("event") == "safe_checkpoint"
    }
    assert set(safe_events_3000) == set(expected_checkpoints)
    states_3000 = RESUME_3000 / "run/states"
    for tick, (state_sha, iram_sha) in expected_checkpoints.items():
        row = checkpoint_rows[str(tick)]
        assert row["state_sha256"] == state_sha
        assert row["iram_sha256"] == iram_sha
        assert row["repeated_state_and_iram_identical"] is True
        assert row["resumable"] is True
        event = safe_events_3000[tick]
        assert event["resume_mame_tick"] == tick + 1
        assert event["state"]["sha256"] == state_sha
        assert event["state"]["resume_sa1_iram"]["sha256"] == iram_sha
        for suffix in ("", ".repeat-1", ".repeat-2"):
            stem = f"safe-checkpoint-{tick:05d}{suffix}.mss"
            assert sha256(states_3000 / stem) == state_sha
            assert sha256(states_3000 / f"{stem}.sa1-iram.bin") == iram_sha
    print("VTIME default paced-$0818 and fresh-bisect regression: green")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
