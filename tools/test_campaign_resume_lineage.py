#!/usr/bin/env python3
"""Focused regression for append-only campaign checkpoint lineage.

A child checkpoint is authenticated by the parent's provenance through the
safe-checkpoint event.  A parent may continue to append observations after
that point; such a tail is useful evidence but cannot alter the serialized
machine state that the child loaded.  This test rejects any return to treating
the mutable whole-log digest as a continuation requirement.
"""

from __future__ import annotations

import importlib.util
import json
import sys
import tempfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CAMPAIGN = ROOT / "tools" / "replay_mame_controller_campaign.py"
SPEC = importlib.util.spec_from_file_location("campaign", CAMPAIGN)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError(f"cannot import {CAMPAIGN}")
campaign = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = campaign
SPEC.loader.exec_module(campaign)


def write_event(stream: Path, event: str, **fields: object) -> None:
    with stream.open("a", encoding="utf-8") as output:
        output.write(json.dumps({"event": event, **fields}, sort_keys=True))
        output.write("\n")


def checkpoint_state(path: Path) -> dict[str, object]:
    path.write_bytes(b"safe checkpoint regression fixture\n")
    return {
        "path": str(path),
        "sha256": campaign.sha256(path),
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
    }


def safe_context(completed: int) -> dict[str, object]:
    return {
        "phase": "post_entry_safe_snes_boundary",
        "mame_tick_completed": completed,
        "resume_mame_tick": completed + 1,
    }


def main() -> None:
    predecessors = (
        "da9f120aa46067c01841122f5055524c02e0d3d4da20ae04522a8ab40ed67974",
        "889e1b2ba99489f40c4a00d7e11235dbcd23bc5e6244a87df9325ecf00be8062",
        "bd6ace3df65ad56cb0cdd7b4578a39bcbdf315f936611abc5e83099acd75107f",
        "2030c2135c724b172670f4322630bbaa9112ef3e941e64dc478d8d1043e179a6",
        "efdb1da62e85e8f20e7f55d95014faed324ac8f47618981f4f93f4c4dd43e426",
        "b1e0c365af00852b79c0153fec5bae4b45bd59955943dde91c5226e41067be91",
        "20a6d8bce98b9d77a73e8588d010fc6c19706ef600850845c62e7fa294e570c2",
        "6903fb0307a3c60a1c24d3a10528204ce987dd90d0e977c55242e64a3ada431b",
    )
    for predecessor in predecessors:
        if not campaign.allowed_resume_identity_mismatch(
            "campaign_script_sha256", "current-runner", predecessor
        ):
            raise AssertionError(
                "finite predecessor runner lost resume compatibility: "
                f"{predecessor}"
            )
    if campaign.allowed_resume_identity_mismatch(
        "campaign_script_sha256", "current-runner", "arbitrary-runner"
    ):
        raise AssertionError("arbitrary runner drift was accepted")
    retained_emulator = {
        "executable": "/retained/Nexen",
        "apphost_sha256": "apphost",
        "managed_assembly_sha256": "managed",
        "source_dependencies_zip": "/retained/UI/Dependencies.zip",
        "source_dependencies_zip_sha256": "source",
        "embedded_native_core_sha256": "native",
    }
    relocated_emulator = {
        **retained_emulator,
        "source_dependencies_zip": "/archive/Dependencies.zip",
    }
    if not campaign.allowed_resume_identity_mismatch(
        "emulator_identity",
        relocated_emulator,
        retained_emulator,
        allow_rom_migration=True,
    ):
        raise AssertionError("authenticated dependency archive relocation rejected")
    changed_source = {
        **relocated_emulator,
        "source_dependencies_zip_sha256": "different-source",
    }
    if campaign.allowed_resume_identity_mismatch(
        "emulator_identity",
        changed_source,
        retained_emulator,
        allow_rom_migration=True,
    ):
        raise AssertionError("dependency archive hash drift was accepted")

    expected = {
        "identity": "campaign-tail-append-regression",
        "native_symbol_table_sha256": "old-symbol-table",
    }
    rom_sha256 = "test-rom-sha256"
    with tempfile.TemporaryDirectory(prefix="campaign-lineage-") as temp:
        directory = Path(temp)
        root_events = directory / "root.jsonl"
        root_state = checkpoint_state(directory / "root.mss")
        write_event(
            root_events,
            "provenance",
            rom_sha256=rom_sha256,
            identity=expected["identity"],
            native_symbol_table_sha256=expected[
                "native_symbol_table_sha256"
            ],
            lineage_kind="fresh_power_on_root",
            time_unix=0,
        )
        write_event(
            root_events,
            "safe_checkpoint",
            resume_mame_tick=2,
            state=root_state,
            resume_context=safe_context(1),
        )
        root_lineage = campaign.validate_resume_lineage(
            root_events,
            Path(root_state["path"]),
            2,
            rom_sha256,
            expected,
        )

        child_events = directory / "child.jsonl"
        child_state = checkpoint_state(directory / "child.mss")
        write_event(
            child_events,
            "provenance",
            rom_sha256=rom_sha256,
            identity=expected["identity"],
            native_symbol_table_sha256=expected[
                "native_symbol_table_sha256"
            ],
            lineage_kind="checkpoint_continuation",
            resume_lineage=root_lineage,
        )
        write_event(
            child_events,
            "safe_checkpoint",
            resume_mame_tick=3,
            state=child_state,
            resume_context=safe_context(2),
        )

        # This is the historical failure: a parent appended an observation
        # after the child had loaded its already-safe state.
        write_event(root_events, "post_checkpoint_observation", tick=2)
        accepted = campaign.validate_resume_lineage(
            child_events, Path(child_state["path"]), 3, rom_sha256, expected
        )
        if accepted["checkpoint_sha256"] != child_state["sha256"]:
            raise AssertionError("child checkpoint was not authenticated")

        candidate_expected = {
            **expected,
            "native_symbol_table_sha256": "candidate-symbol-table",
        }
        migrated = campaign.validate_resume_lineage(
            child_events,
            Path(child_state["path"]),
            3,
            "candidate-rom-sha256",
            candidate_expected,
            allow_rom_migration=True,
        )
        migration = migrated["rom_migration"]
        if not isinstance(migration, dict):
            raise AssertionError("cross-ROM migration was not retained")
        if migration["checkpoint_rom_sha256"] != rom_sha256:
            raise AssertionError("checkpoint ROM identity was lost")
        if migration["selected_rom_sha256"] != "candidate-rom-sha256":
            raise AssertionError("candidate ROM identity was lost")
        if migrated["fresh_boot_rom_sha256"] != rom_sha256:
            raise AssertionError("fresh root identity changed during migration")
        symbol_exception = migrated["identity_compatibility_exceptions"].get(
            "native_symbol_table_sha256"
        )
        if symbol_exception != {
            "expected": "candidate-symbol-table",
            "observed": "old-symbol-table",
        }:
            raise AssertionError(
                f"candidate symbol exception was not audited: {symbol_exception}"
            )
        if migrated["lineage_has_rom_migration"] is not True:
            raise AssertionError("migrated lineage scope was not retained")

        migrated_child_events = directory / "migrated-child.jsonl"
        migrated_child_state = checkpoint_state(
            directory / "migrated-child.mss"
        )
        write_event(
            migrated_child_events,
            "provenance",
            rom_sha256="candidate-rom-sha256",
            identity=candidate_expected["identity"],
            native_symbol_table_sha256=candidate_expected[
                "native_symbol_table_sha256"
            ],
            lineage_kind="checkpoint_continuation",
            resume_lineage=migrated,
        )
        write_event(
            migrated_child_events,
            "safe_checkpoint",
            resume_mame_tick=4,
            state=migrated_child_state,
            resume_context=safe_context(3),
        )
        continued_migration = campaign.validate_resume_lineage(
            migrated_child_events,
            Path(migrated_child_state["path"]),
            4,
            "candidate-rom-sha256",
            candidate_expected,
        )
        if continued_migration["rom_migration"] is not None:
            raise AssertionError("same-candidate child requested another refresh")
        if continued_migration["lineage_has_rom_migration"] is not True:
            raise AssertionError("migrated ancestry was lost on continuation")

    print("campaign resume lineage append-tail regression: green")


if __name__ == "__main__":
    main()
