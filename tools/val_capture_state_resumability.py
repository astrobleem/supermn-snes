#!/usr/bin/env python3
"""Regression for checkpoint replay start-state authentication."""

from __future__ import annotations

import json
import tempfile
from pathlib import Path

import capture_snes_movie_ticks as capture


def write_jsonl(path: Path, rows: list[dict]) -> None:
    path.write_text(
        "".join(json.dumps(row, sort_keys=True) + "\n" for row in rows),
        encoding="utf-8",
    )


def expect_rejected(callable_) -> bool:
    try:
        callable_()
    except RuntimeError:
        return True
    return False


def main() -> int:
    with tempfile.TemporaryDirectory(
        prefix="capture-state-resumability-"
    ) as raw_temp:
        temp = Path(raw_temp)
        rom = temp / "rom.sfc"
        wrong_rom = temp / "wrong-rom.sfc"
        timeline = temp / "timeline.jsonl"
        wrong_timeline = temp / "wrong-timeline.jsonl"
        nexen = temp / "Nexen"
        wrong_nexen = temp / "WrongNexen"
        state = temp / "safe.mss"
        continuation_state = temp / "continuation-safe.mss"
        nested = temp / "nested.mss"
        rom.write_bytes(b"rom")
        wrong_rom.write_bytes(b"wrong-rom")
        timeline.write_bytes(b"timeline\n")
        wrong_timeline.write_bytes(b"wrong-timeline\n")
        nexen.write_bytes(b"nexen")
        wrong_nexen.write_bytes(b"wrong-nexen")
        state.write_bytes(b"safe-state")
        continuation_state.write_bytes(b"continuation-safe-state")
        nested.write_bytes(b"nested-state")
        rom_hash = capture.sha256(rom)
        timeline_hash = capture.sha256(timeline)
        nexen_hash = capture.sha256(nexen)
        state_hash = capture.sha256(state)
        continuation_state_hash = capture.sha256(continuation_state)
        nested_hash = capture.sha256(nested)
        emulator_identity = {
            "apphost_sha256": nexen_hash,
            "deps_manifest_sha256": "deps",
            "embedded_native_core_sha256": "core",
            "managed_assembly_sha256": "managed",
            "source_dependencies_zip_sha256": "source",
        }

        safe_events = temp / "safe-events.jsonl"
        write_jsonl(
            safe_events,
            [
                {
                    "event": "provenance",
                    "lineage_kind": "fresh_power_on_root",
                    "rom_sha256": rom_hash,
                    "emulator_sha256": nexen_hash,
                    "emulator_identity": emulator_identity,
                    "mame_timeline_sha256": timeline_hash,
                },
                {
                    "event": "safe_checkpoint",
                    "resume_mame_tick": 3001,
                    "state": {
                        "path": str(state.resolve()),
                        "sha256": state_hash,
                        "resumable_checkpoint": True,
                        "boundary_kind": "post_entry_safe_snes_boundary",
                        "entry_exact_bundle": False,
                        "nested_sa1_entry_nonresumable": False,
                        "synchronous_completed": True,
                        "atomic_rename": True,
                        "live_state_unchanged": True,
                        "active_run_reloaded": False,
                        "active_run_memory_restored": False,
                        "resume_validation": {},
                        "resume_sa1_state": {},
                        "resume_sa1_iram": {},
                    },
                    "resume_context": {
                        "phase": "post_entry_safe_snes_boundary",
                        "mame_tick_completed": 3000,
                        "resume_mame_tick": 3001,
                    },
                },
            ],
        )
        nested_events = temp / "nested-events.jsonl"
        write_jsonl(
            nested_events,
            [
                {
                    "event": "boundary",
                    "save_state": {
                        "sha256": nested_hash,
                        "boundary_kind": "sa1_exact_entry_nested_forensic",
                        "entry_exact_bundle": True,
                        "nested_sa1_entry_nonresumable": True,
                        "resumable_checkpoint": False,
                    },
                }
            ],
        )

        original_nexen_identity = capture.campaign.nexen_identity
        capture.campaign.nexen_identity = (
            lambda _path: dict(emulator_identity)
        )
        try:
            safe = capture.authenticate_start_state(
                state=state,
                state_mame_tick=3000,
                rom=rom,
                timeline=timeline,
                nexen=nexen,
                lineage_events=safe_events,
                allow_forensic_nonresumable_state=False,
            )
            parent_lineage = capture.campaign.validate_resume_lineage(
                safe_events,
                state,
                3001,
                rom_hash,
                {
                    "emulator_sha256": nexen_hash,
                    "mame_timeline_sha256": timeline_hash,
                },
            )
            continuation_events = temp / "continuation-events.jsonl"
            write_jsonl(
                continuation_events,
                [
                    {
                        "event": "provenance",
                        "lineage_kind": "checkpoint_continuation",
                        "rom_sha256": rom_hash,
                        "emulator_sha256": nexen_hash,
                        "emulator_identity": emulator_identity,
                        "mame_timeline_sha256": timeline_hash,
                        "resume_lineage": parent_lineage,
                    },
                    {
                        "event": "safe_checkpoint",
                        "resume_mame_tick": 4001,
                        "state": {
                            "path": str(continuation_state.resolve()),
                            "sha256": continuation_state_hash,
                            "resumable_checkpoint": True,
                            "boundary_kind": (
                                "post_entry_safe_snes_boundary"
                            ),
                            "entry_exact_bundle": False,
                            "nested_sa1_entry_nonresumable": False,
                            "synchronous_completed": True,
                            "atomic_rename": True,
                            "live_state_unchanged": True,
                            "active_run_reloaded": False,
                            "active_run_memory_restored": False,
                            "resume_validation": {},
                            "resume_sa1_state": {},
                            "resume_sa1_iram": {},
                        },
                        "resume_context": {
                            "phase": "post_entry_safe_snes_boundary",
                            "mame_tick_completed": 4000,
                            "resume_mame_tick": 4001,
                        },
                    },
                ],
            )
            transitive_safe = capture.authenticate_start_state(
                state=continuation_state,
                state_mame_tick=4000,
                rom=rom,
                timeline=timeline,
                nexen=nexen,
                lineage_events=continuation_events,
                allow_forensic_nonresumable_state=False,
            )
            completed_tick_off_by_one_rejected = expect_rejected(
                lambda: capture.authenticate_start_state(
                    state=state,
                    state_mame_tick=3001,
                    rom=rom,
                    timeline=timeline,
                    nexen=nexen,
                    lineage_events=safe_events,
                    allow_forensic_nonresumable_state=False,
                )
            )
            wrong_rom_rejected = expect_rejected(
                lambda: capture.authenticate_start_state(
                    state=state,
                    state_mame_tick=3000,
                    rom=wrong_rom,
                    timeline=timeline,
                    nexen=nexen,
                    lineage_events=safe_events,
                    allow_forensic_nonresumable_state=False,
                )
            )
            wrong_timeline_rejected = expect_rejected(
                lambda: capture.authenticate_start_state(
                    state=state,
                    state_mame_tick=3000,
                    rom=rom,
                    timeline=wrong_timeline,
                    nexen=nexen,
                    lineage_events=safe_events,
                    allow_forensic_nonresumable_state=False,
                )
            )
            wrong_emulator_rejected = expect_rejected(
                lambda: capture.authenticate_start_state(
                    state=state,
                    state_mame_tick=3000,
                    rom=rom,
                    timeline=timeline,
                    nexen=wrong_nexen,
                    lineage_events=safe_events,
                    allow_forensic_nonresumable_state=False,
                )
            )
            nested_rejected = expect_rejected(
                lambda: capture.authenticate_start_state(
                    state=nested,
                    state_mame_tick=7561,
                    rom=rom,
                    timeline=timeline,
                    nexen=nexen,
                    lineage_events=nested_events,
                    allow_forensic_nonresumable_state=False,
                )
            )
            nested_override = capture.authenticate_start_state(
                state=nested,
                state_mame_tick=7561,
                rom=rom,
                timeline=timeline,
                nexen=nexen,
                lineage_events=nested_events,
                allow_forensic_nonresumable_state=True,
            )
            unverified_rejected = expect_rejected(
                lambda: capture.authenticate_start_state(
                    state=nested,
                    state_mame_tick=7561,
                    rom=rom,
                    timeline=timeline,
                    nexen=nexen,
                    lineage_events=None,
                    allow_forensic_nonresumable_state=False,
                )
            )
            unverified_override = capture.authenticate_start_state(
                state=nested,
                state_mame_tick=7561,
                rom=rom,
                timeline=timeline,
                nexen=nexen,
                lineage_events=None,
                allow_forensic_nonresumable_state=True,
            )
        finally:
            capture.campaign.nexen_identity = original_nexen_identity

    checks = {
        "safe_lineage_accepted": (
            safe["classification"]
            == "authenticated_post_entry_safe_checkpoint"
            and safe["resumable_checkpoint"] is True
            and safe["production_behavior_evidence"] is True
        ),
        "transitive_safe_lineage_accepted": (
            transitive_safe["resumable_checkpoint"] is True
            and transitive_safe["lineage"]["lineage_kind"]
            == "checkpoint_continuation"
            and transitive_safe["lineage"]["lineage_depth"] == 1
            and transitive_safe["lineage"]["parent_lineage"][
                "lineage_kind"
            ]
            == "fresh_power_on_root"
        ),
        "completed_tick_not_resume_tick": (
            completed_tick_off_by_one_rejected
        ),
        "wrong_rom_rejected": wrong_rom_rejected,
        "wrong_timeline_rejected": wrong_timeline_rejected,
        "wrong_emulator_rejected": wrong_emulator_rejected,
        "nested_state_rejected_by_default": nested_rejected,
        "nested_override_explicitly_forensic": (
            nested_override["classification"]
            == "explicit_nested_entry_forensic_override"
            and nested_override["resumable_checkpoint"] is False
            and nested_override["production_behavior_evidence"] is False
        ),
        "missing_lineage_rejected_by_default": unverified_rejected,
        "missing_lineage_override_explicitly_forensic": (
            unverified_override["classification"]
            == "unverified_forensic_override"
            and unverified_override["resumable_checkpoint"] is False
            and unverified_override["production_behavior_evidence"] is False
        ),
    }
    result = {
        "scope": (
            "pure checkpoint-lineage regression; no emulator or game-state "
            "mutation"
        ),
        "checks": checks,
        "result": "green" if all(checks.values()) else "red",
    }
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0 if result["result"] == "green" else 1


if __name__ == "__main__":
    raise SystemExit(main())
