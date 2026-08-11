#!/usr/bin/env python3
"""Organic carried-versus-thrown crate differential in all three configs.

The branch starts from an authenticated fresh-campaign safe checkpoint at
completed tick 3000, replays the retained controller movie through the first
crate pickup, and replaces the stock throw with a deterministic Down+Right
carry.  The held arm makes real contact with an ordinary enemy.  The thrown
arm differs only by a one-update Button-1 edge at tick 3248.

Each branch is compared at every exact pre-MOVEM game-update entry from
ticks 3214-3300:

* MAME 0.287 running the original arcade code;
* Nexen with gameplay native roots disabled while scheduler/pacing stays live;
* Nexen with the fresh-boot production gate values preserved.

The focused root validator remains the authority for instruction-by-
instruction terminal register/CCR/stack equality.  This tool proves the
organic controller path and retains complete 64 KiB work-state diagnostics,
while gating game-owned player/collision/health state, M68K registers,
CCR/X, stack/return state, task state, gate firing, and exact-entry cadence.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
import time
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
EVIDENCE = ROOT / "build/playtest-investigation-20260725"
DEFAULT_ROM = ROOT / "build/interp.sfc"
DEFAULT_TIMELINE = EVIDENCE / "full-playback-timeline-v1/timeline.jsonl"
DEFAULT_NEXEN = Path(
    "/mnt/sdc1/Nexen-r5-20260712/bin/linux-x64/Release/"
    "mcp-iram-edge-publish/Nexen"
)
DEFAULT_SAFE_EVENTS = (
    EVIDENCE
    / "fresh-campaign-entrysync-2235a21-to61000-v1/events.jsonl"
)
DEFAULT_MAME_HELD = (
    EVIDENCE / "mame-crate-held-downright-3213-3300-mame0287-v7"
)
DEFAULT_MAME_THROWN = (
    EVIDENCE
    / "mame-crate-thrown-downright-t3248-3213-3300-mame0287-v7"
)
DEFAULT_MAME_SOURCE = (
    EVIDENCE
    / "mame-crate-organic-prethrow-3213-3216-mame0287-v4/summary.json"
)
DEFAULT_BOUNDED_ROOT = (
    EVIDENCE
    / "crate-damage-threeway-current-2235a21-mame0287-v8/summary.json"
)

SAFE_TICK = 3000
RESUME_TICK = SAFE_TICK + 1
BRANCH_TICK = 3214
THROW_TICK = 3248
END_TICK = 3300
HELD_MASK = 0x00A0  # Down+Right, with no attack button.
THROW_MASK = HELD_MASK | 0x0002  # Button 1 is the legitimate throw.
# MAME's forced input port reaches the game-owned input byte three update
# entries after the host edge; Nexen's controller mailbox reaches it in two.
# Apply each SNES host edge one logical entry later so the game-observed
# input, action, collision, and damage states represent the same timeline.
# The arcade branch also exposes one neutral game-input entry while releasing
# the stock Button-1 hold and asserting Down+Right, so reproduce that neutral
# edge explicitly on Nexen.
SNES_BRANCH_INPUT_TICK = BRANCH_TICK + 1
SNES_THROW_INPUT_TICK = THROW_TICK + 1
SNES_THROW_RELEASE_TICK = SNES_THROW_INPUT_TICK + 1
SNES_BRANCH_NEUTRAL_TICK = BRANCH_TICK
INTERPRETED_VIDEO_FRAME_BUDGET_PER_ENTRY = 256
ALL_NATIVE_GATES = (0x072E, 0x071A, 0x0734, 0x0736, 0x073A, 0x073C)
PRODUCTION_GATE_VALUES = {
    0x072E: 0x0001,
    0x071A: 0x0001,
    0x0734: 0x0001,
    0x0736: 0x5EEC,
    0x073A: 0x0001,
    0x073C: 0xA55A,
}
TICK_BOUNDARY = 0x00F5A3
TAKE_VIRTUAL_IRQ = 0x00B404
MILESTONE_TICKS = {
    3214,
    3248,
    3251,
    3252,
    3253,
    3254,
    3255,
    3260,
    3273,
    3274,
    3282,
    3283,
    3300,
}
COLLISION_START = 0x3734
COLLISION_END = 0x3CC4
CRATE_TYPE = 0x8039
HELD_RESPONSE = 0x2000
THROWN_RESPONSE = 0x2001
ENEMY_SLOT_BASE = 0x2BB4
ENEMY_SLOT_STRIDE = 0xAA
ENEMY_SLOT_COUNT = 8
ENEMY_HEALTH_OFFSET = 3
ENEMY_ACTIVE_OFFSET = 0xA8
M68K_PC_IRAM = 0x0040
M68K_GAME_UPDATE_ENTRY = 0x00003A92
NATIVE_ENTRY_PREFIX = bytes.fromhex(
    "c230a5408554a542855622aee500"
)

sys.path.insert(0, str(ROOT / "tools"))
import capture_snes_movie_ticks as snes_capture  # noqa: E402
import replay_mame_controller_campaign as campaign  # noqa: E402
import validate_1e7c0_native as consumer  # noqa: E402
import validate_25110_native as emitter  # noqa: E402
import validate_campaign_work_threeway as work_compare  # noqa: E402
from mame_0287 import identity as mame_identity  # noqa: E402

GAMEPLAY_NATIVE_GATES = tuple(snes_capture.GAMEPLAY_NATIVE_GATES)
INFRASTRUCTURE_NATIVE_GATES = tuple(
    address
    for address in ALL_NATIVE_GATES
    if address not in GAMEPLAY_NATIVE_GATES
)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def same_mame_identity(
    observed: dict[str, Any], expected: dict[str, Any]
) -> bool:
    """Compare the emulator build, not an installation-specific executable path.

    The recovered MAME 0.287 executable is byte-identical to the old Snap
    location but necessarily has a different absolute path.  Retained oracle
    artifacts pin version, executable digest, Snap revision, and the matching
    GNOME content revision; requiring the former path would reject the same
    original-code oracle for a non-semantic host relocation.
    """

    return all(
        observed.get(key) == expected.get(key)
        for key in (
            "version",
            "sha256",
            "snap_revision",
            "gnome_content_revision",
        )
    )


def be16(data: bytes, offset: int) -> int:
    return int.from_bytes(data[offset : offset + 2], "big")


def le16(data: bytes, offset: int) -> int:
    return int.from_bytes(data[offset : offset + 2], "little")


def read_work(m: campaign.McpSession) -> bytes:
    return b"".join(
        bytes(m.read_memory("snesMemory", 0x400000 + offset, 0x4000))
        for offset in range(0, 0x10000, 0x4000)
    )


def first_difference(left: bytes, right: bytes) -> int | None:
    for index, (a, b) in enumerate(zip(left, right, strict=True)):
        if a != b:
            return index
    return None


def collision_records(work: bytes) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for offset in range(COLLISION_START, COLLISION_END, 0x10):
        object_type = be16(work, offset + 0x0A)
        response = be16(work, offset + 0x0C)
        peer = be16(work, offset + 0x0E)
        if (
            object_type == CRATE_TYPE
            or response in (HELD_RESPONSE, THROWN_RESPONSE)
            or peer == CRATE_TYPE
        ):
            records.append(
                {
                    "offset": f"F0{offset:04X}",
                    "active": be16(work, offset),
                    "x1": be16(work, offset + 2),
                    "x2": be16(work, offset + 4),
                    "y1": be16(work, offset + 6),
                    "y2": be16(work, offset + 8),
                    "type": object_type,
                    "response": response,
                    "peer": peer,
                }
            )
    return records


def enemy_slot_states(work: bytes) -> list[dict[str, Any]]:
    return [
        {
            "slot": slot,
            "base": f"F0{base:04X}",
            "health_address": f"F0{base + ENEMY_HEALTH_OFFSET:04X}",
            "active_marker": be16(work, base + ENEMY_ACTIVE_OFFSET),
            "health": work[base + ENEMY_HEALTH_OFFSET],
        }
        for slot in range(ENEMY_SLOT_COUNT)
        for base in [ENEMY_SLOT_BASE + slot * ENEMY_SLOT_STRIDE]
    ]


def enemy_health_transitions(
    states: list[tuple[int, bytes]],
) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for (before_tick, before), (after_tick, after) in zip(
        states, states[1:]
    ):
        for prior, current in zip(
            enemy_slot_states(before),
            enemy_slot_states(after),
            strict=True,
        ):
            if (
                prior["active_marker"]
                and current["active_marker"]
                and current["health"] < prior["health"]
            ):
                result.append(
                    {
                        "tick": after_tick,
                        "previous_tick": before_tick,
                        "slot": current["slot"],
                        "health_address": current["health_address"],
                        "before": prior["health"],
                        "after": current["health"],
                    }
                )
    return result


def has_reciprocal_crate_contact(work: bytes, response: int) -> bool:
    records = collision_records(work)
    return (
        any(
            int(record["active"]) != 0
            and int(record["type"]) == CRATE_TYPE
            and int(record["response"]) == response
            for record in records
        )
        and any(
            int(record["active"]) != 0
            and int(record["peer"]) == CRATE_TYPE
            and int(record["response"]) == response
            for record in records
        )
    )


def player_from_work(
    work: bytes,
    entry: dict[str, Any],
) -> dict[str, int]:
    return {
        "health": be16(work, 0x12B4),
        "previous_input": work[0x12BF],
        "input": work[0x12BE],
        "action": work[0x12DF],
        "flags": work[0x12DE],
        "animation": be16(work, 0x12E8),
        "animation_step": be16(work, 0x12EA),
        "x": be16(work, 0x12E4),
        "y": be16(work, 0x12E0),
        "x1_ctrl_3601": int(entry["x1_ctrl_3601"]),
        "x1_ctrl_3603": int(entry["x1_ctrl_3603"]),
    }


def compare_logical_entry(
    *,
    native_on: bool,
    snapshot: dict[str, Any],
    snes_work: bytes,
    mame_work: bytes,
    mame_entry: dict[str, Any],
    health_offsets: list[int],
    task_floors: list[int],
) -> dict[str, Any]:
    full_differences = [
        offset
        for offset, (snes, mame) in enumerate(
            zip(snes_work, mame_work, strict=True)
        )
        if snes != mame
    ]
    snes_m68k = snapshot["m68k"]
    snes_registers = {
        name: int(value, 16)
        for name, value in snes_m68k["registers"].items()
    }
    mame_registers = {
        name: int(mame_entry[name]) & 0xFFFFFFFF
        for name in snes_registers
    }
    register_mismatches = {
        name: {
            "snes": f"{snes_registers[name]:08X}",
            "mame": f"{mame_registers[name]:08X}",
        }
        for name in snes_registers
        if snes_registers[name] != mame_registers[name]
    }
    snes_ccr = int(snes_m68k["ccr_xnzvc"]) & 0x1F
    mame_ccr = int(mame_entry["SR"]) & 0x1F
    snes_interrupt_mask = int(snes_m68k["interrupt_mask"]) & 7
    mame_interrupt_mask = (int(mame_entry["SR"]) >> 8) & 7
    stack_address = int(
        str(snes_m68k["stack_window"]["address"])[2:], 16
    )
    snes_stack = bytes.fromhex(
        str(snes_m68k["stack_window"]["hex"])
    )
    mame_stack = mame_work[
        stack_address : stack_address + len(snes_stack)
    ]
    snes_return_long = int.from_bytes(snes_stack[32:36], "big")
    physical_sa1_pc = (
        ((int(snapshot["sa1"]["k"]) & 0xFF) << 16)
        | (int(snapshot["sa1"]["pc"]) & 0xFFFF)
    )
    virtual_pc = int(snapshot["m68k_virtual_pc_0040"])
    logical_entry_boundary_exact = (
        (
            physical_sa1_pc
            == campaign.ENTRY_3A92_NATIVE + len(NATIVE_ENTRY_PREFIX)
            and virtual_pc == snes_return_long
        )
        if native_on
        else virtual_pc == M68K_GAME_UPDATE_ENTRY
    )
    snes_player = {
        key: int(value)
        for key, value in snapshot["player"].items()
        if key != "locals_sha256"
    }
    mame_player = player_from_work(mame_work, mame_entry)
    player_mismatches = {
        name: {
            "snes": snes_player[name],
            "mame": mame_player[name],
        }
        for name in mame_player
        if snes_player[name] != mame_player[name]
    }
    collision = work_compare.compare_collision_records(
        snes_work, mame_work
    )
    tasks = work_compare.compare_task_contexts(snes_work, mame_work)
    snes_crate_records = collision_records(snes_work)
    mame_crate_records = collision_records(mame_work)
    snes_health = {
        f"F0{offset:04X}": snes_work[offset]
        for offset in health_offsets
    }
    mame_health = {
        f"F0{offset:04X}": mame_work[offset]
        for offset in health_offsets
    }
    snes_enemy_slots = enemy_slot_states(snes_work)
    mame_enemy_slots = enemy_slot_states(mame_work)
    task_floor_rows = [
        {
            "task": row["task"],
            "saved_sp": row["saved_sp"],
            "floor": f"{int(task_floors[row['task']]):08X}",
            "valid": (
                int(row["saved_sp"], 16) >> 16 == 0x00F0
                and int(row["saved_sp"], 16)
                >= int(task_floors[row["task"]])
            ),
        }
        for row in tasks["left"]
        if row["initialized"]
    ]
    snes_scheduler = {
        "header_0000_0009": snes_work[0:0x0A].hex(),
        "task_mask_0002": be16(snes_work, 2),
        "current_task_0004": be16(snes_work, 4),
        "system_context_pointer_0006": int.from_bytes(
            snes_work[6:10], "big"
        ),
        "selected_context_pointer_004a": int.from_bytes(
            snes_work[0x4A:0x4E], "big"
        ),
    }
    mame_scheduler = {
        "header_0000_0009": mame_work[0:0x0A].hex(),
        "task_mask_0002": be16(mame_work, 2),
        "current_task_0004": be16(mame_work, 4),
        "system_context_pointer_0006": int.from_bytes(
            mame_work[6:10], "big"
        ),
        "selected_context_pointer_004a": int.from_bytes(
            mame_work[0x4A:0x4E], "big"
        ),
    }
    snes_usp = int(snapshot["m68k_usp_00a4"])
    return {
        "full_work": {
            "exact": not full_differences,
            "different_bytes": len(full_differences),
            "first_offsets": [
                f"F0{offset:04X}" for offset in full_differences[:64]
            ],
        },
        "m68k": {
            "registers_exact": not register_mismatches,
            "register_mismatches": register_mismatches,
            "snes_ccr_xnzvc": snes_ccr,
            "mame_ccr_xnzvc": mame_ccr,
            "x_exact": (snes_ccr & 0x10) == (mame_ccr & 0x10),
            "nzvc_exact": (snes_ccr & 0x0F) == (mame_ccr & 0x0F),
            "interrupt_mask_exact": (
                snes_interrupt_mask == mame_interrupt_mask
            ),
            "snes_interrupt_mask": snes_interrupt_mask,
            "mame_interrupt_mask": mame_interrupt_mask,
            "usp_exact": snes_usp == int(mame_entry["USP"]),
            "snes_usp": f"{snes_usp:08X}",
            "mame_usp": f"{int(mame_entry['USP']):08X}",
            # Native-on is stopped after entry_3a92 has copied the caller's
            # continuation from $40/$42 and pushed it.  At that intentional
            # seam the virtual PC therefore equals the pushed return ($070E),
            # while native-off exposes the literal interpreted $003A92 PC.
            "logical_entry_boundary_exact": logical_entry_boundary_exact,
            "physical_sa1_pc": f"{physical_sa1_pc:06X}",
            "virtual_pc": f"{virtual_pc:08X}",
            "live_stack_exact": snes_stack[32:] == mame_stack[32:],
            "popped_stack_residue_exact": (
                snes_stack[:32] == mame_stack[:32]
            ),
            "stack_address": f"F0{stack_address:04X}",
            "snes_stack_sha256": digest(snes_stack),
            "mame_stack_sha256": digest(mame_stack),
            "return_long_exact": snes_stack[32:36] == mame_stack[32:36],
            "snes_return_long": snes_stack[32:36].hex(),
            "mame_return_long": mame_stack[32:36].hex(),
        },
        "player": {
            "exact": not player_mismatches,
            "mismatches": player_mismatches,
            "snes": snes_player,
            "mame": mame_player,
        },
        "collision": {
            "active_records_exact": collision["semantic_equal"],
            "active_rows_snes": collision["active_rows_left"],
            "active_rows_mame": collision["active_rows_right"],
            "active_mismatches": collision["active_mismatches"],
            "inactive_residue_different_bytes": collision[
                "inactive_residue_different_bytes"
            ],
            "crate_records_exact": (
                snes_crate_records == mame_crate_records
            ),
            "snes_crate_records": snes_crate_records,
            "mame_crate_records": mame_crate_records,
        },
        "health": {
            "exact": snes_health == mame_health,
            "snes": snes_health,
            "mame": mame_health,
        },
        "enemy_slots": {
            "exact": snes_enemy_slots == mame_enemy_slots,
            "snes": snes_enemy_slots,
            "mame": mame_enemy_slots,
        },
        "tasks": {
            "saved_sp_exact": tasks["saved_sp_equal"],
            "saved_register_frame_exact": tasks[
                "saved_register_frame_equal"
            ],
            "saved_status_exact": tasks["saved_status_equal"],
            "resume_pc_exact": tasks["resume_pc_equal"],
            "stack_floors_valid": all(
                row["valid"] for row in task_floor_rows
            ),
            "stack_floors": task_floor_rows,
            "mismatches": tasks["mismatches"],
        },
        "scheduler": {
            "exact": snes_scheduler == mame_scheduler,
            "snes": snes_scheduler,
            "mame": mame_scheduler,
        },
        "mame_game_tick_f01c56": int(
            mame_entry["game_tick_f01c56"]
        ),
        "snes_game_tick_f01c56": int(
            snapshot["game_tick_f01c56"]
        ),
        "logical_tick_relation_exact": (
            int(snapshot["tick_0760"])
            == int(mame_entry["game_tick_f01c56"])
            and (
                (int(snapshot["game_tick_f01c56"]) + 1)
                & 0xFFFF
            )
            == int(snapshot["tick_0760"])
        ),
    }


def parse_safe_checkpoint(
    event_path: Path,
    rom_hash: str,
    *,
    allow_rom_migration: bool = False,
) -> tuple[Path, dict[str, Any], dict[str, Any], dict[str, Any]]:
    rows = [
        json.loads(line)
        for line in event_path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    provenance = [
        row for row in rows if row.get("event") == "provenance"
    ]
    safe = [
        row
        for row in rows
        if row.get("event") == "safe_checkpoint"
        and int(row.get("mame_tick", -1)) == SAFE_TICK
    ]
    if len(provenance) != 1 or len(safe) != 1:
        raise RuntimeError("safe lineage lacks unique provenance/checkpoint")
    source_rom_hash = str(provenance[0].get("rom_sha256", ""))
    if provenance[0].get("lineage_kind") != "fresh_power_on_root":
        raise RuntimeError("safe checkpoint is not from a fresh-boot root")
    if source_rom_hash != rom_hash and not allow_rom_migration:
        raise RuntimeError("safe checkpoint is not from this fresh-boot ROM")
    state = dict(safe[0]["state"])
    context = dict(safe[0]["resume_context"])
    context["rom_migration"] = (
        {
            "source_rom_sha256": source_rom_hash,
            "target_rom_sha256": rom_hash,
            "claim": (
                "focused cross-ROM checkpoint diagnostic; not fresh-boot "
                "proof for the target ROM"
            ),
        }
        if source_rom_hash != rom_hash
        else None
    )
    checks = {
        "resumable": state.get("resumable_checkpoint") is True,
        "safe_boundary": (
            state.get("boundary_kind") == "post_entry_safe_snes_boundary"
        ),
        "not_nested": (
            state.get("entry_exact_bundle") is False
            and state.get("nested_sa1_entry_nonresumable") is False
        ),
        "resume_tick": int(context.get("resume_mame_tick", -1))
        == RESUME_TICK,
        "zero_prefix_divergence": int(
            context.get("oracle_divergence_count", -1)
        )
        == 0,
    }
    if not all(checks.values()):
        raise RuntimeError(f"unsafe campaign checkpoint: {checks}")
    state_path = Path(str(state["path"]))
    if not state_path.is_absolute():
        state_path = ROOT / state_path
    state_path = state_path.resolve()
    if not state_path.is_file() or sha256(state_path) != state["sha256"]:
        raise RuntimeError("safe checkpoint file is unauthenticated")
    return state_path, state, context, provenance[0]


def load_current_root_events(
    path: Path,
    *,
    label: str,
    rom_hash: str,
    mame: dict[str, Any],
    expected_total: int,
    expected_cases: set[str],
) -> dict[str, Any]:
    """Authenticate current-ROM focused collision-root proof.

    The emitter and consumer are intentionally separate validators because
    they stop at different architectural terminals.  The organic replay must
    depend on both current-ROM results, rather than an older combined report
    whose ROM lineage cannot prove this target.
    """

    if not path.is_file():
        raise RuntimeError(f"missing {label} root events: {path}")
    rows = [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    provenance = [row for row in rows if row.get("event") == "provenance"]
    summaries = [row for row in rows if row.get("event") == "summary"]
    cases = [row for row in rows if row.get("event") == "case"]
    if len(provenance) != 1 or len(summaries) != 1:
        raise RuntimeError(f"{label}: malformed root event stream")
    source = provenance[0]
    summary = summaries[0]
    observed_cases = {str(row.get("case", "")) for row in cases}
    checks = {
        "current_rom_hash": source.get("rom_sha256") == rom_hash,
        "mame_identity": same_mame_identity(
            dict(source.get("mame") or {}), mame
        ),
        "one_green_summary": (
            summary.get("result") == "green"
            and int(summary.get("green", -1)) == expected_total
            and int(summary.get("red", -1)) == 0
            and int(summary.get("total", -1)) == expected_total
        ),
        "all_cases_green": (
            len(cases) == expected_total
            and all(row.get("result") == "green" for row in cases)
        ),
        "expected_cases": observed_cases == expected_cases,
        "prestates_retained": all(
            isinstance(
                row.get("pre_state")
                or dict(row.get("nexen_boundary") or {}).get("pre_state"),
                dict,
            )
            for row in cases
        ),
    }
    if not all(checks.values()):
        raise RuntimeError(f"{label}: root proof is not current/green: {checks}")
    return {
        "events": str(path.resolve()),
        "events_sha256": sha256(path),
        "provenance": source,
        "summary": summary,
        "checks": checks,
    }


def load_mame_branch(
    path: Path,
    thrown: bool,
    held_mask: int,
    switch_tick: int,
    switch_mask: int,
    mame: dict[str, str],
) -> dict[str, Any]:
    event_path = path / "events.jsonl"
    summary_path = path / "summary.json"
    if not event_path.is_file() or not summary_path.is_file():
        raise RuntimeError(f"missing MAME branch log: {event_path}")
    branch_summary = json.loads(
        summary_path.read_text(encoding="utf-8")
    )
    if (
        branch_summary.get("result") != "green"
        or branch_summary.get("events_sha256") != sha256(event_path)
        or not same_mame_identity(
            dict(branch_summary.get("mame") or {}), mame
        )
        or branch_summary.get("capture_tool_sha256")
        != sha256(ROOT / "tools/capture_mame_crate_branch.py")
        or not all(
            bool(value)
            for value in dict(branch_summary.get("checks", {})).values()
        )
    ):
        raise RuntimeError(f"{path}: unauthenticated branch summary")
    rows = [
        json.loads(line)
        for line in event_path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    provenance = [row for row in rows if row.get("event") == "provenance"]
    summaries = [row for row in rows if row.get("event") == "summary"]
    if len(provenance) != 1 or len(summaries) != 1:
        raise RuntimeError(f"{path}: malformed branch event log")
    expected_throw = THROW_TICK if thrown else 0
    if (
        provenance[0].get("mame_version") != mame["version"]
        or provenance[0].get("mame_sha256") != mame["sha256"]
        or provenance[0].get("mame_snap_revision")
        != mame["snap_revision"]
        or int(provenance[0].get("base_tick", -1)) != 3213
        or int(provenance[0].get("held_mask", -1)) != held_mask
        or int(provenance[0].get("stop_tick", -1)) != END_TICK
        or int(provenance[0].get("throw_tick", -1)) != expected_throw
        or int(provenance[0].get("switch_tick", 0)) != switch_tick
        or int(provenance[0].get("switch_mask", 0)) != switch_mask
        or summaries[0].get("result") != "green"
    ):
        raise RuntimeError(f"{path}: wrong branch configuration")
    entry_list = [
        row for row in rows if row.get("event") == "entry"
    ]
    post_prologue_list = [
        row for row in rows if row.get("event") == "tick_start"
    ]
    completion_list = [
        row for row in rows if row.get("event") == "completion"
    ]
    entry_rows = {
        int(row["tick"]): row
        for row in entry_list
    }
    post_prologue_rows = {
        int(row["tick"]): row
        for row in post_prologue_list
    }
    completion_rows = {
        int(row["tick"]): row
        for row in completion_list
    }
    expected_ticks = set(range(BRANCH_TICK, END_TICK + 1))
    if (
        len(entry_list) != len(expected_ticks)
        or len(post_prologue_list) != len(expected_ticks)
        or len(completion_list) != len(expected_ticks)
        or set(entry_rows) != expected_ticks
        or set(post_prologue_rows) != expected_ticks
        or set(completion_rows) != expected_ticks
    ):
        raise RuntimeError(
            f"{path}: boundary ticks differ: "
            f"entry_missing={sorted(expected_ticks - set(entry_rows))}, "
            f"entry_extra={sorted(set(entry_rows) - expected_ticks)}, "
            "post_prologue_missing="
            f"{sorted(expected_ticks - set(post_prologue_rows))}, "
            "post_prologue_extra="
            f"{sorted(set(post_prologue_rows) - expected_ticks)}"
        )
    row_indices = {id(row): index for index, row in enumerate(rows)}
    for tick in sorted(expected_ticks):
        if not (
            row_indices[id(entry_rows[tick])]
            < row_indices[id(post_prologue_rows[tick])]
            < row_indices[id(completion_rows[tick])]
        ):
            raise RuntimeError(
                f"{path}: tick {tick} boundary order is not "
                "entry -> prologue -> completion"
            )
    expected_host_masks = {}
    for tick in expected_ticks:
        active_held_mask = (
            switch_mask
            if switch_tick and tick >= switch_tick
            else held_mask
        )
        expected_host_masks[tick] = (
            active_held_mask | 0x0002
            if thrown and tick == THROW_TICK
            else active_held_mask
        )
    if any(
        int(row["buttons"]) != expected_host_masks[tick]
        for tick in expected_ticks
        for row in (
            entry_rows[tick],
            post_prologue_rows[tick],
            completion_rows[tick],
        )
    ):
        raise RuntimeError(f"{path}: host input mask sequence drifted")
    required_entry_fields = {
        "player_input",
        "player_previous_input",
        "x1_ctrl_3601",
        "x1_ctrl_3603",
    }
    missing_fields = {
        tick: sorted(required_entry_fields - set(row))
        for tick, row in entry_rows.items()
        if not required_entry_fields <= set(row)
    }
    if missing_fields:
        raise RuntimeError(
            f"{path}: entry rows lack explicit input/X1 state: "
            f"{missing_fields}"
        )
    works: dict[int, bytes] = {}
    work_metadata: dict[int, dict[str, Any]] = {}
    for tick, row in entry_rows.items():
        work_path = path / str(row["work"])
        work = work_path.read_bytes()
        if len(work) != 0x10000:
            raise RuntimeError(f"{work_path}: expected 64 KiB")
        works[tick] = work
        manifest = dict(branch_summary["work_manifest"]).get(
            work_path.name
        )
        if (
            not isinstance(manifest, dict)
            or int(manifest.get("size", -1)) != len(work)
            or manifest.get("sha256") != sha256(work_path)
        ):
            raise RuntimeError(
                f"{path}: work manifest mismatch for {work_path.name}"
            )
        work_metadata[tick] = {
            "path": str(work_path.resolve()),
            "sha256": sha256(work_path),
        }
    boundary_checks: list[dict[str, Any]] = []
    for tick in sorted(expected_ticks):
        entry = entry_rows[tick]
        post = post_prologue_rows[tick]
        entry_work = works[tick]
        post_work = (
            path / str(post["work"])
        ).read_bytes()
        entry_sp = int(entry["A7"]) & 0xFFFFFF
        stack_start = (entry_sp - 0x3C) & 0xFFFFFF
        differences = [
            index
            for index, (left, right) in enumerate(
                zip(entry_work, post_work, strict=True)
            )
            if left != right
        ]
        data_address_registers_same = all(
            int(entry[name]) == int(post[name])
            for name in (
                "USP",
                *(f"D{index}" for index in range(8)),
                *(f"A{index}" for index in range(7)),
            )
        )
        boundary_checks.append(
            {
                "tick": tick,
                "entry_pc_after_opcode_fetch": int(entry["PC"]),
                "post_prologue_pc_at_first_work_read": int(post["PC"]),
                "entry_a7": entry_sp,
                "post_prologue_a7": int(post["A7"]) & 0xFFFFFF,
                "entry_sr": int(entry["SR"]),
                "post_prologue_sr": int(post["SR"]),
                "data_address_registers_same": (
                    data_address_registers_same
                ),
                "sr_privilege_and_interrupt_mask_same": (
                    (int(entry["SR"]) & 0xFFE0)
                    == (int(post["SR"]) & 0xFFE0)
                ),
                "differences_confined_to_movem_frame": all(
                    stack_start - 0xF00000
                    <= index
                    < entry_sp - 0xF00000
                    for index in differences
                ),
                "difference_count": len(differences),
            }
        )
    health_writes = [
        row for row in rows if row.get("event") == "enemy_health_write"
    ]
    contacts = [
        row
        for row in entry_rows.values()
        if has_reciprocal_crate_contact(
            works[int(row["tick"])],
            THROWN_RESPONSE if thrown else HELD_RESPONSE,
        )
    ]
    transitions = enemy_health_transitions(
        [(tick, works[tick]) for tick in sorted(works)]
    )
    return {
        "path": path,
        "events": event_path,
        "events_sha256": sha256(event_path),
        "rows": rows,
        "entries": entry_rows,
        "post_prologue_entries": post_prologue_rows,
        "completion_entries": completion_rows,
        "summary": branch_summary,
        "summary_path": summary_path,
        "summary_sha256": sha256(summary_path),
        "boundary_checks": boundary_checks,
        "works": works,
        "work_metadata": work_metadata,
        "health_writes": health_writes,
        "health_transitions": transitions,
        "contacts": contacts,
    }


def run_logical_entries(
    m: campaign.McpSession,
    count: int,
    *,
    native_on: bool,
    include_loaded_partial_native_entry: bool,
) -> dict[str, Any]:
    """Advance to an exact, configuration-correct pre-MOVEM entry seam.

    The production scheduler calls the native body directly, so native-on
    never exposes $003A92 in the interpreted PC.  Stop just after that body's
    simulated JSR return push.  Gameplay-root-off reaches the same state
    through the rising edge of the IRAM MC68000 PC becoming $003A92 while
    the production scheduler, tick bridge, switch-in, and pacing remain live.
    """

    if count <= 0:
        raise ValueError("logical entry count must be positive")
    campaign.require_paused(m, "logical-entry start")
    before_cpu = dict(m.get_cpu_state("Sa1"))
    before_frame = int(m.get_state().get("frameCount", 0))
    before_pc = (
        ((int(before_cpu.get("k", 0)) & 0xFF) << 16)
        | (int(before_cpu.get("pc", 0)) & 0xFFFF)
    )
    frames_per_entry = (
        campaign.VIDEO_FRAME_BUDGET_PER_TICK
        if native_on
        else INTERPRETED_VIDEO_FRAME_BUDGET_PER_ENTRY
    )
    frame_budget = max(
        campaign.MIN_TICK_VIDEO_FRAME_BUDGET,
        count * frames_per_entry + campaign.MIN_TICK_VIDEO_FRAME_BUDGET,
    )
    if native_on:
        post_push = campaign.ENTRY_3A92_NATIVE + len(
            NATIVE_ENTRY_PREFIX
        )
        if include_loaded_partial_native_entry and not (
            campaign.ENTRY_3A92_NATIVE
            < before_pc
            < post_push
        ):
            raise RuntimeError(
                "authenticated safe checkpoint no longer resumes inside "
                "the expected native $003A92 entry prefix: "
                f"PC={before_pc:06X}"
            )
        physical_occurrences = count + (
            1 if include_loaded_partial_native_entry else 0
        )
        response = dict(
            m.tool(
                "run_to_exact_exec_stop",
                {
                    "address": post_push,
                    "cpuType": "Sa1",
                    "maxFrames": frame_budget,
                    "occurrences": physical_occurrences,
                },
            )
        )
        expected_address = post_push
        boundary = "native_post_simulated_jsr_push_pre_movem"
        extra_checks = (
            int(response.get("observedOccurrences", -1))
            == physical_occurrences
            and int(response.get("requestedOccurrences", -1))
            == physical_occurrences
        )
    else:
        if include_loaded_partial_native_entry:
            raise RuntimeError(
                "loaded native-entry compensation is invalid with gates off"
            )
        response = dict(
            m.tool(
                "run_to_exact_iram_exec_edge",
                {
                    "iramAddress": M68K_PC_IRAM,
                    "value": M68K_GAME_UPDATE_ENTRY,
                    "mask": 0xFFFFFFFF,
                    "maxFrames": frame_budget,
                    "occurrences": count,
                },
            )
        )
        expected_address = int(response.get("address", -1))
        boundary = "interpreted_pc_003a92_rising_edge_pre_movem"
        extra_checks = (
            int(response.get("observedOccurrences", -1)) == count
            and int(response.get("requestedOccurrences", -1)) == count
            and int(response.get("iramAddress", -1)) == M68K_PC_IRAM
            and int(response.get("observedValue", -1))
            == M68K_GAME_UPDATE_ENTRY
            and response.get("predicateMatched") is True
            and response.get("edgeRequired") is True
            and response.get("cleanupPauseApplied") is False
        )
    after_cpu = dict(m.get_cpu_state("Sa1"))
    after_frame = int(m.get_state().get("frameCount", 0))
    after_pc = (
        ((int(after_cpu.get("k", 0)) & 0xFF) << 16)
        | (int(after_cpu.get("pc", 0)) & 0xFFFF)
    )
    if (
        response.get("reason") != "breakpoint"
        or response.get("hit") is not True
        or response.get("isPaused") is not True
        or response.get("exactStopRemoved") is not True
        or response.get("exactStopTriggered") is not True
        or response.get("exactStopBreakDelivered") is not True
        or int(response.get("exactStopHandle", 0)) <= 0
        or int(response.get("triggerAddress", expected_address))
        != expected_address
        or after_pc != expected_address
        or int(response.get("cycleCount", -1))
        != int(after_cpu.get("cycleCount", -2))
        or int(response.get("triggerCycleCount", -1))
        != int(after_cpu.get("cycleCount", -2))
        or int(response.get("endFrame", -1)) != after_frame
        or int(response.get("triggerFrame", -1)) != after_frame
        or not extra_checks
    ):
        raise campaign.CampaignFailure(
            "hardware-boundary/timing",
            {
                "reason": "logical_entry_exact_stop_failed",
                "native_on": native_on,
                "count": count,
                "include_loaded_partial_native_entry": (
                    include_loaded_partial_native_entry
                ),
                "before_pc": f"{before_pc:06X}",
                "after_pc": f"{after_pc:06X}",
                "response": response,
            },
        )
    if campaign.halt16(m):
        raise campaign.CampaignFailure(
            "interpreter_or_native_hle",
            {
                "reason": "interpreter_halt_at_logical_entry",
                "halt": campaign.halt16(m),
                "native_on": native_on,
            },
        )
    return {
        "boundary": boundary,
        "logical_entries": count,
        "physical_occurrences": (
            count
            + (
                1
                if native_on and include_loaded_partial_native_entry
                else 0
            )
        ),
        "before_pc": f"{before_pc:06X}",
        "after_pc": f"{after_pc:06X}",
        "before_frame": before_frame,
        "after_frame": after_frame,
        "video_frames": after_frame - before_frame,
        "before_cycles": int(before_cpu.get("cycleCount", 0)),
        "after_cycles": int(after_cpu.get("cycleCount", 0)),
        "sa1_cycles": (
            int(after_cpu.get("cycleCount", 0))
            - int(before_cpu.get("cycleCount", 0))
        ),
        "response": response,
    }


def compact_notifications(
    rows: list[dict[str, Any]],
    handles: dict[int, str],
    executed_tick: int,
) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for row in rows:
        if row.get("method") != "notifications/mesen/hookFired":
            continue
        params = dict(row.get("params", {}))
        handle = int(params.get("handle", -1))
        if handle not in handles:
            continue
        result.append(
            {
                "kind": handles[handle],
                "executed_tick": executed_tick,
                **{
                    key: params[key]
                    for key in (
                        "address",
                        "value",
                        "pc",
                        "cycleCount",
                        "cpuType",
                        "operation",
                    )
                    if key in params
                },
            }
        )
    return result


def exact_snapshot(
    m: campaign.McpSession,
    tick: int,
    work: bytes,
) -> dict[str, Any]:
    iram = bytes(m.read_memory("Sa1Memory", 0, 0x800))
    state = dict(m.get_state())
    return {
        "tick": tick,
        "frame": int(state.get("frameCount", 0)),
        "sa1": dict(m.get_cpu_state("Sa1")),
        "snes": dict(m.get_cpu_state("Snes")),
        "work_sha256": digest(work),
        "iram_sha256": digest(iram),
        "game_tick_f01c56": be16(work, 0x1C56),
        "tick_0760": le16(iram, campaign.TICK_IRAM),
        "task_mask_f00002": be16(work, 2),
        "halt_004e": le16(iram, 0x4E),
        "m68k_virtual_pc_0040": int.from_bytes(
            iram[M68K_PC_IRAM : M68K_PC_IRAM + 4], "little"
        ),
        "m68k_usp_00a4": (
            le16(iram, 0xA4) | (le16(iram, 0xA6) << 16)
        ),
        "irq_mask_007c": le16(iram, 0x7C) & 7,
        "virtual_irq_pending_00aa": le16(iram, 0xAA),
        "virtual_irq_countdown_00ac": le16(iram, 0xAC),
        "m68k": campaign.register_snapshot(m),
        "player": campaign.player_snapshot(m),
        "collision_records": collision_records(work),
        "gates": {
            f"{address:04x}": le16(iram, address)
            for address in ALL_NATIVE_GATES
        },
    }


def run_snes_branch(
    *,
    args: argparse.Namespace,
    branch_name: str,
    thrown: bool,
    held_mask: int,
    switch_tick: int,
    switch_mask: int,
    native_on: bool,
    port: int,
    state_path: Path,
    state_metadata: dict[str, Any],
    safe_context: dict[str, Any],
    inputs: list[campaign.InputEvent],
    mame_branch: dict[str, Any],
    health_watch_addresses: list[int],
    health_offsets: list[int],
    output: Path,
) -> dict[str, Any]:
    configuration = (
        (
            "snes-native-on"
            if native_on
            else "snes-gameplay-root-off-scheduler-pacing-preserved"
        )
    )
    run_output = output / branch_name / configuration
    run_output.mkdir(parents=True)
    retained = run_output / "work"
    retained.mkdir()
    campaign.configure_dotnet(args.nexen)
    comparisons: list[dict[str, Any]] = []
    hook_events: list[dict[str, Any]] = []
    spans: list[dict[str, Any]] = []
    final_snes_work = b""
    snes_entry_works: list[tuple[int, bytes]] = []
    first_failure_prestate: dict[str, Any] | None = None
    task_floors = [int(value) for value in safe_context["task_floors"]]
    if len(task_floors) != 16:
        raise RuntimeError("safe checkpoint lacks all 16 task-stack floors")

    with campaign.AuditedMcpSession(
        rom=args.rom.resolve(),
        mesen=args.nexen.resolve(),
        cwd=ROOT,
        port=port,
        boot_wait=6.0,
        socket_timeout=300.0,
        stderr_log=run_output / "nexen.stderr.log",
    ) as m:
        campaign.pause_for_startup(m)
        load_response = dict(m.load_state(str(state_path)))
        campaign.require_paused(m, f"{configuration} safe load")
        immediate_public, _immediate_raw = (
            campaign.checkpoint_machine_snapshot(m)
        )
        immediate_exact = (
            immediate_public == state_metadata["resume_validation"]
        )
        if not immediate_exact:
            expected_snapshot = state_metadata["resume_validation"]
            differing = sorted(
                key
                for key in set(immediate_public) | set(expected_snapshot)
                if immediate_public.get(key) != expected_snapshot.get(key)
            )
            expected_diff = {
                key: expected_snapshot.get(key) for key in differing
            }
            observed_diff = {
                key: immediate_public.get(key) for key in differing
            }
            raise RuntimeError(
                f"{configuration}: immediate state mismatch keys={differing} "
                f"expected={expected_diff} observed={observed_diff}"
            )

        gate_values_before = {
            address: int(
                m.read_u16(address, "Sa1Memory")
            )
            for address in ALL_NATIVE_GATES
        }
        mutation_start = len(m.architectural_mutations)
        if not native_on:
            for address in GAMEPLAY_NATIVE_GATES:
                m.write_u16(address, 0, "Sa1Memory")
        configuration_mutations = list(
            m.architectural_mutations[mutation_start:]
        )
        gate_values_after = {
            address: int(
                m.read_u16(address, "Sa1Memory")
            )
            for address in ALL_NATIVE_GATES
        }
        expected_gate_values_after = dict(PRODUCTION_GATE_VALUES)
        if not native_on:
            expected_gate_values_after.update(
                {address: 0 for address in GAMEPLAY_NATIVE_GATES}
            )
        mutation_addresses = [
            int(row.get("arguments", {}).get("address", -1))
            for row in configuration_mutations
        ]
        gate_configuration_green = (
            gate_values_before == PRODUCTION_GATE_VALUES
            and gate_values_after == expected_gate_values_after
            and (
                not configuration_mutations
                if native_on
                else (
                    mutation_addresses == list(GAMEPLAY_NATIVE_GATES)
                    and len(configuration_mutations)
                    == len(GAMEPLAY_NATIVE_GATES)
                )
            )
            and all(
                gate_values_after[address] == PRODUCTION_GATE_VALUES[address]
                for address in INFRASTRUCTURE_NATIVE_GATES
            )
        )
        if not gate_configuration_green:
            raise RuntimeError(
                f"{configuration}: gate setup failed: "
                f"before={gate_values_before}, after={gate_values_after}, "
                f"mutations={configuration_mutations}"
            )

        current_buttons = int(safe_context["current_buttons"])
        campaign.set_held_input(m, current_buttons)
        first_logical_run = True

        def advance(count: int) -> None:
            nonlocal first_logical_run
            spans.append(
                run_logical_entries(
                    m,
                    count,
                    native_on=native_on,
                    include_loaded_partial_native_entry=(
                        native_on and first_logical_run
                    ),
                )
            )
            first_logical_run = False

        advance(1)
        current_tick = RESUME_TICK
        for event in inputs:
            if event.tick <= RESUME_TICK or event.tick >= BRANCH_TICK:
                continue
            advance(event.tick - current_tick)
            current_tick = event.tick
            campaign.set_held_input(m, event.buttons)
            current_buttons = event.buttons
        advance(BRANCH_TICK - current_tick)
        current_tick = BRANCH_TICK

        handles: dict[int, str] = {}
        handles[
            m.add_exec_hook(emitter.ENTRY_NATIVE, cpu_type="Sa1")
        ] = "native_emitter_025110"
        handles[
            m.add_exec_hook(consumer.ENTRY_NATIVE, cpu_type="Sa1")
        ] = "native_consumer_01e7c0"
        handles[
            m.add_exec_hook(TICK_BOUNDARY, cpu_type="Sa1")
        ] = "tick_boundary_00f5a3"
        handles[
            m.add_exec_hook(TAKE_VIRTUAL_IRQ, cpu_type="Sa1")
        ] = "virtual_irq_00b404"
        for address in health_watch_addresses:
            handles[
                m.add_write_hook(address, address, cpu_type="Sa1")
            ] = f"enemy_health_write_{address:06x}"
        m.drain_notifications(timeout=0.05)

        while current_tick <= END_TICK:
            if current_tick == SNES_BRANCH_NEUTRAL_TICK:
                desired_buttons = 0
            elif current_tick < SNES_BRANCH_INPUT_TICK:
                desired_buttons = current_buttons
            else:
                # The MAME route applies its host edge at ``switch_tick``.
                # Arcade input reaches the game byte one logical entry later
                # than the Nexen mailbox, just like the initial/throw edges
                # documented above.  Delay the SNES host switch one entry so
                # the observed $12BE input and movement timeline are equal.
                active_held_mask = (
                    switch_mask
                    if switch_tick and current_tick >= switch_tick + 1
                    else held_mask
                )
                desired_buttons = active_held_mask
                if (
                    thrown
                    and SNES_THROW_INPUT_TICK
                    <= current_tick
                    < SNES_THROW_RELEASE_TICK
                ):
                    desired_buttons = active_held_mask | 0x0002
            if desired_buttons != current_buttons:
                campaign.set_held_input(m, desired_buttons)
                current_buttons = desired_buttons

            work = read_work(m)
            final_snes_work = work
            snes_entry_works.append((current_tick, work))
            oracle = mame_branch["works"][current_tick]
            difference = first_difference(work, oracle)
            snapshot = exact_snapshot(m, current_tick, work)
            logical_entry = compare_logical_entry(
                native_on=native_on,
                snapshot=snapshot,
                snes_work=work,
                mame_work=oracle,
                mame_entry=mame_branch["entries"][current_tick],
                health_offsets=health_offsets,
                task_floors=task_floors,
            )
            comparison = {
                "tick": current_tick,
                "work_exact": difference is None,
                "first_difference": (
                    None if difference is None else f"F0{difference:04X}"
                ),
                "snes_work_sha256": digest(work),
                "mame_work_sha256": digest(oracle),
                "snapshot": snapshot,
                "logical_entry": logical_entry,
            }
            entry_checks = {
                "m68k_registers": logical_entry["m68k"]["registers_exact"],
                "m68k_ccr_x": (
                    logical_entry["m68k"]["x_exact"]
                    and logical_entry["m68k"]["nzvc_exact"]
                    and logical_entry["m68k"]["interrupt_mask_exact"]
                ),
                "m68k_usp": logical_entry["m68k"]["usp_exact"],
                "entry_boundary": logical_entry["m68k"][
                    "logical_entry_boundary_exact"
                ],
                "stack_return": (
                    logical_entry["m68k"]["live_stack_exact"]
                    and logical_entry["m68k"]["return_long_exact"]
                ),
                "player": logical_entry["player"]["exact"],
                "active_collision": logical_entry["collision"][
                    "active_records_exact"
                ],
                "crate_collision": logical_entry["collision"][
                    "crate_records_exact"
                ],
                "enemy_health": logical_entry["health"]["exact"],
                "enemy_slots": logical_entry["enemy_slots"]["exact"],
                "scheduler": logical_entry["scheduler"]["exact"],
                "task_saved_sp": logical_entry["tasks"]["saved_sp_exact"],
                "task_register_frame": logical_entry["tasks"][
                    "saved_register_frame_exact"
                ],
                "task_status": logical_entry["tasks"]["saved_status_exact"],
                "task_resume_pc": logical_entry["tasks"]["resume_pc_exact"],
                "logical_tick_relation": logical_entry[
                    "logical_tick_relation_exact"
                ],
            }
            if first_failure_prestate is None and not all(entry_checks.values()):
                prestate_path = (
                    run_output
                    / f"pre-failure-logical-entry-{current_tick:05d}.mss"
                )
                prestate_response = campaign.save_state(m, prestate_path)
                first_failure_prestate = {
                    "tick": current_tick,
                    "checks_failed": sorted(
                        key for key, value in entry_checks.items() if not value
                    ),
                    "state": prestate_response,
                    "sha256": sha256(prestate_path),
                }
                comparison["pre_failure_state"] = first_failure_prestate
            if current_tick in MILESTONE_TICKS or difference is not None:
                work_path = (
                    retained / f"snes-entry-tick-{current_tick:05d}.work.bin"
                )
                work_path.write_bytes(work)
                comparison["retained_work"] = {
                    "path": str(work_path.resolve()),
                    "sha256": sha256(work_path),
                }
            comparisons.append(comparison)
            if current_tick == END_TICK:
                break

            advance(1)
            rows = list(m.drain_notifications(timeout=0.05))
            hook_events.extend(
                compact_notifications(rows, handles, current_tick)
            )
            current_tick += 1

        for handle in handles:
            m.remove_hook(handle)
        hook_events.extend(
            compact_notifications(
                list(m.drain_notifications(timeout=0.05)),
                handles,
                current_tick,
            )
        )
        final_mutations = list(m.architectural_mutations)

    health_byte_write_events = [
        row
        for row in hook_events
        if row["kind"].startswith("enemy_health_write_")
    ]
    damage_events = [
        row
        for row in health_byte_write_events
        if (int(row.get("value", -1)) & 0xFF) == 0
    ]
    emitter_hits = [
        row
        for row in hook_events
        if row["kind"] == "native_emitter_025110"
    ]
    consumer_hits = [
        row
        for row in hook_events
        if row["kind"] == "native_consumer_01e7c0"
    ]
    tick_boundary_hits = [
        row
        for row in hook_events
        if row["kind"] == "tick_boundary_00f5a3"
    ]
    virtual_irq_hits = [
        row
        for row in hook_events
        if row["kind"] == "virtual_irq_00b404"
    ]
    irq_pending_sequence = [
        int(row["snapshot"]["virtual_irq_pending_00aa"])
        for row in comparisons
    ]
    irq_countdown_sequence = [
        int(row["snapshot"]["virtual_irq_countdown_00ac"])
        for row in comparisons
    ]
    expected_snapshot_gates = {
        f"{address:04x}": value
        for address, value in expected_gate_values_after.items()
    }
    snes_health_transitions = enemy_health_transitions(snes_entry_works)
    mame_health_transitions = mame_branch["health_transitions"]
    health_values = {
        f"F0{offset:04X}": final_snes_work[offset]
        for offset in health_offsets
    }
    expected_response = THROWN_RESPONSE if thrown else HELD_RESPONSE
    snes_contact_ticks = [
        int(row["tick"])
        for row in comparisons
        if has_reciprocal_crate_contact(
            snes_entry_works[
                int(row["tick"]) - BRANCH_TICK
            ][1],
            expected_response,
        )
    ]
    mame_contact_ticks = sorted(
        int(row["tick"]) for row in mame_branch["contacts"]
    )
    checks = {
        "immediate_safe_load_exact": immediate_exact,
        "gate_configuration": gate_configuration_green,
        "all_87_gate_values_stable": all(
            row["snapshot"]["gates"] == expected_snapshot_gates
            for row in comparisons
        ),
        "all_87_logical_entries_retained": (
            len(comparisons) == END_TICK - BRANCH_TICK + 1
        ),
        "all_87_m68k_registers_exact": all(
            row["logical_entry"]["m68k"]["registers_exact"]
            for row in comparisons
        ),
        "all_87_m68k_x_exact": all(
            row["logical_entry"]["m68k"]["x_exact"]
            for row in comparisons
        ),
        "all_87_m68k_nzvc_exact": all(
            row["logical_entry"]["m68k"]["nzvc_exact"]
            for row in comparisons
        ),
        "all_87_interrupt_masks_exact": all(
            row["logical_entry"]["m68k"]["interrupt_mask_exact"]
            for row in comparisons
        ),
        "all_87_m68k_usp_exact": all(
            row["logical_entry"]["m68k"]["usp_exact"]
            for row in comparisons
        ),
        "all_87_logical_entry_boundaries_exact": all(
            row["logical_entry"]["m68k"]["logical_entry_boundary_exact"]
            for row in comparisons
        ),
        "all_87_stack_and_return_exact": all(
            row["logical_entry"]["m68k"]["live_stack_exact"]
            and row["logical_entry"]["m68k"]["return_long_exact"]
            for row in comparisons
        ),
        "all_87_player_states_exact": all(
            row["logical_entry"]["player"]["exact"]
            for row in comparisons
        ),
        "all_87_active_collision_records_exact": all(
            row["logical_entry"]["collision"]["active_records_exact"]
            for row in comparisons
        ),
        "all_87_crate_collision_records_exact": all(
            row["logical_entry"]["collision"]["crate_records_exact"]
            for row in comparisons
        ),
        "all_87_enemy_health_bytes_exact": all(
            row["logical_entry"]["health"]["exact"]
            for row in comparisons
        ),
        "all_87_enemy_slot_states_exact": all(
            row["logical_entry"]["enemy_slots"]["exact"]
            for row in comparisons
        ),
        "all_87_scheduler_headers_exact": all(
            row["logical_entry"]["scheduler"]["exact"]
            for row in comparisons
        ),
        "all_87_task_saved_sp_exact": all(
            row["logical_entry"]["tasks"]["saved_sp_exact"]
            for row in comparisons
        ),
        "all_87_task_saved_register_frames_exact": all(
            row["logical_entry"]["tasks"]["saved_register_frame_exact"]
            for row in comparisons
        ),
        "all_87_task_saved_status_exact": all(
            row["logical_entry"]["tasks"]["saved_status_exact"]
            for row in comparisons
        ),
        "all_87_task_resume_pc_exact": all(
            row["logical_entry"]["tasks"]["resume_pc_exact"]
            for row in comparisons
        ),
        "all_87_task_stack_floors_valid": all(
            row["logical_entry"]["tasks"]["stack_floors_valid"]
            for row in comparisons
        ),
        "all_87_logical_tick_relations_exact": all(
            row["logical_entry"]["logical_tick_relation_exact"]
            for row in comparisons
        ),
        "contact_tick_set_exact": (
            snes_contact_ticks == mame_contact_ticks
        ),
        "active_enemy_health_transitions_exact": (
            snes_health_transitions == mame_health_transitions
        ),
        "expected_active_enemy_health_transitions": (
            mame_health_transitions
            == (
                [
                    {
                        "tick": 3274,
                        "previous_tick": 3273,
                        "slot": 0,
                        "health_address": "F02BB7",
                        "before": 1,
                        "after": 0,
                    },
                    {
                        "tick": 3283,
                        "previous_tick": 3282,
                        "slot": 1,
                        "health_address": "F02C61",
                        "before": 1,
                        "after": 0,
                    },
                ]
                if thrown
                else []
            )
        ),
        "native_root_firing_exact": (
            len(emitter_hits) == END_TICK - BRANCH_TICK
            and len(consumer_hits) == END_TICK - BRANCH_TICK
            if native_on
            else len(emitter_hits) == 0 and len(consumer_hits) == 0
        ),
        "tick_boundary_hook_count_exact": (
            len(tick_boundary_hits) == END_TICK - BRANCH_TICK
        ),
        "virtual_irq_hook_observed": bool(virtual_irq_hits),
        "virtual_irq_pending_clear_at_all_entries": all(
            value == 0 for value in irq_pending_sequence
        ),
        "virtual_irq_countdown_retained_at_all_entries": (
            len(irq_countdown_sequence)
            == END_TICK - BRANCH_TICK + 1
        ),
        "only_declared_gate_mutations": (
            final_mutations == configuration_mutations
        ),
        "halt_zero": all(
            int(row["snapshot"]["halt_004e"]) == 0
            for row in comparisons
        ),
    }
    result = {
        "branch": branch_name,
        "configuration": configuration,
        "result": "green" if all(checks.values()) else "red",
        "checks": checks,
        "load_response": load_response,
        "gate_values_before": {
            f"{key:04x}": value
            for key, value in gate_values_before.items()
        },
        "gate_values_after": {
            f"{key:04x}": value
            for key, value in gate_values_after.items()
        },
        "configuration_mutations": configuration_mutations,
        "runtime_mutations": final_mutations,
        "comparisons": comparisons,
        "hook_events": hook_events,
        "health_byte_write_events": health_byte_write_events,
        "damage_events": damage_events,
        "snes_active_enemy_health_transitions": snes_health_transitions,
        "mame_active_enemy_health_transitions": mame_health_transitions,
        "health_values": health_values,
        "native_emitter_hits": len(emitter_hits),
        "native_consumer_hits": len(consumer_hits),
        "irq_cadence": {
            "tick_boundary_00f5a3_hits": len(tick_boundary_hits),
            "virtual_irq_00b404_hits": len(virtual_irq_hits),
            "pending_00aa_at_entries": irq_pending_sequence,
            "countdown_00ac_at_entries": irq_countdown_sequence,
            "physical_video_frames": sum(
                int(span["video_frames"]) for span in spans
            ),
            "sa1_cycles": sum(int(span["sa1_cycles"]) for span in spans),
            "physical_timing_normalized": False,
        },
        "snes_contact_ticks": snes_contact_ticks,
        "mame_contact_ticks": mame_contact_ticks,
        "entry_spans": spans,
        "first_failure_prestate": first_failure_prestate,
        "diagnostics": {
            "all_87_complete_work_states_exact": all(
                row["work_exact"] for row in comparisons
            ),
            "full_work_difference_counts": {
                str(row["tick"]): row["logical_entry"]["full_work"][
                    "different_bytes"
                ]
                for row in comparisons
            },
            "popped_stack_residue_exact_ticks": [
                int(row["tick"])
                for row in comparisons
                if row["logical_entry"]["m68k"][
                    "popped_stack_residue_exact"
                ]
            ],
        },
    }
    result_path = run_output / "result.json"
    result_path.write_text(
        json.dumps(result, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return {
        **{key: value for key, value in result.items() if key not in {
            "comparisons",
            "hook_events",
            "entry_spans",
        }},
        "result_path": str(result_path.resolve()),
        "result_sha256": sha256(result_path),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--rom", type=Path, default=DEFAULT_ROM)
    parser.add_argument("--timeline", type=Path, default=DEFAULT_TIMELINE)
    parser.add_argument("--nexen", type=Path, default=DEFAULT_NEXEN)
    parser.add_argument("--safe-events", type=Path, default=DEFAULT_SAFE_EVENTS)
    parser.add_argument("--mame-held", type=Path, default=DEFAULT_MAME_HELD)
    parser.add_argument("--mame-thrown", type=Path, default=DEFAULT_MAME_THROWN)
    parser.add_argument(
        "--held-mask",
        type=lambda value: int(value, 0),
        default=HELD_MASK,
        help=(
            "controller mask used after crate pickup (default 0xA0, "
            "Down+Right; use 0x90 for Up+Right flight carry)"
        ),
    )
    parser.add_argument(
        "--switch-tick",
        type=int,
        default=0,
        help=(
            "replace --held-mask at this branch tick; use with --switch-mask "
            "to record a deterministic controller route"
        ),
    )
    parser.add_argument(
        "--switch-mask",
        type=lambda value: int(value, 0),
        default=None,
        help="replacement controller mask for --switch-tick",
    )
    parser.add_argument(
        "--flight-carry-only",
        action="store_true",
        help=(
            "validate a carried Up-flight contact branch only; preserves "
            "the ordinary throw proof as separate evidence"
        ),
    )
    parser.add_argument(
        "--mame-source-summary",
        type=Path,
        default=DEFAULT_MAME_SOURCE,
    )
    parser.add_argument(
        "--bounded-root-summary",
        type=Path,
        default=DEFAULT_BOUNDED_ROOT,
    )
    parser.add_argument(
        "--emitter-root-events",
        type=Path,
        help=(
            "current-ROM validate_25110_native JSONL; together with "
            "--consumer-root-events replaces the historical combined root "
            "summary"
        ),
    )
    parser.add_argument(
        "--consumer-root-events",
        type=Path,
        help=(
            "current-ROM validate_1e7c0_native JSONL; together with "
            "--emitter-root-events replaces the historical combined root "
            "summary"
        ),
    )
    parser.add_argument("--port", type=int, default=9600)
    parser.add_argument(
        "--allow-rom-migration",
        action="store_true",
        help=(
            "permit the authenticated fresh-boot checkpoint to run under a "
            "different target ROM as a focused diagnostic; never fresh-boot "
            "proof for that target"
        ),
    )
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if not 0 <= args.held_mask <= 0x0FFF:
        parser.error("--held-mask must be a 12-bit controller mask")
    if args.switch_tick and not BRANCH_TICK <= args.switch_tick <= END_TICK:
        parser.error("--switch-tick must be zero or inside the branch")
    if (args.switch_tick == 0) != (args.switch_mask is None):
        parser.error("--switch-tick and --switch-mask must be supplied together")
    if args.switch_mask is not None and not 0 <= args.switch_mask <= 0x0FFF:
        parser.error("--switch-mask must be a 12-bit controller mask")
    if args.flight_carry_only and not (
        (args.held_mask | (args.switch_mask or 0)) & 0x0010
    ):
        parser.error(
            "--flight-carry-only requires Up in the initial or switched mask"
        )
    mame = mame_identity()
    current_root_pair = (
        args.emitter_root_events is not None
        or args.consumer_root_events is not None
    )
    if current_root_pair and (
        args.emitter_root_events is None
        or args.consumer_root_events is None
    ):
        parser.error(
            "--emitter-root-events and --consumer-root-events are required "
            "together"
        )
    for label, path in (
        ("ROM", args.rom),
        ("timeline", args.timeline),
        ("Nexen", args.nexen),
        ("safe events", args.safe_events),
        ("MAME held branch", args.mame_held),
        *([] if args.flight_carry_only else [("MAME thrown branch", args.mame_thrown)]),
        ("MAME source summary", args.mame_source_summary),
        *(
            []
            if current_root_pair
            else [("bounded root summary", args.bounded_root_summary)]
        ),
        *(
            [
                ("emitter root events", args.emitter_root_events),
                ("consumer root events", args.consumer_root_events),
            ]
            if current_root_pair
            else []
        ),
    ):
        if not path.exists():
            parser.error(f"missing {label}: {path}")
    if args.output.exists():
        parser.error(f"output already exists: {args.output}")
    if tuple(ALL_NATIVE_GATES) != tuple(snes_capture.ALL_NATIVE_GATES):
        raise RuntimeError(
            "observed production gate set drifted from "
            "capture_snes_movie_ticks.ALL_NATIVE_GATES"
        )
    if tuple(GAMEPLAY_NATIVE_GATES) != tuple(
        snes_capture.GAMEPLAY_NATIVE_GATES
    ):
        raise RuntimeError(
            "gameplay-root-off gate set drifted from "
            "capture_snes_movie_ticks.GAMEPLAY_NATIVE_GATES"
        )
    if set(PRODUCTION_GATE_VALUES) != set(ALL_NATIVE_GATES):
        raise RuntimeError("production gate-value map is incomplete")

    rom_hash = sha256(args.rom)
    rom = args.rom.read_bytes()
    native_entry_file_offset = 0x290000 + (
        campaign.ENTRY_3A92_NATIVE & 0x7FFF
    )
    observed_native_prefix = rom[
        native_entry_file_offset :
        native_entry_file_offset + len(NATIVE_ENTRY_PREFIX)
    ]
    if observed_native_prefix != NATIVE_ENTRY_PREFIX:
        raise RuntimeError(
            "native $003A92 entry prefix changed; the post-JSR-push "
            "boundary must be re-audited: "
            f"expected={NATIVE_ENTRY_PREFIX.hex()}, "
            f"observed={observed_native_prefix.hex()}"
        )
    state_path, state_metadata, safe_context, fresh_provenance = (
        parse_safe_checkpoint(
            args.safe_events,
            rom_hash,
            allow_rom_migration=args.allow_rom_migration,
        )
    )
    inputs, _tick_rows = campaign.load_timeline(
        args.timeline, 221, END_TICK
    )
    switch_mask = args.switch_mask or 0
    mame_held = load_mame_branch(
        args.mame_held,
        False,
        args.held_mask,
        args.switch_tick,
        switch_mask,
        mame,
    )
    mame_thrown = (
        None
        if args.flight_carry_only
        else load_mame_branch(
            args.mame_thrown,
            True,
            args.held_mask,
            args.switch_tick,
            switch_mask,
            mame,
        )
    )
    mame_source = json.loads(
        args.mame_source_summary.read_text(encoding="utf-8")
    )
    source_state = dict(mame_source.get("saved_state") or {})
    source_state_path = Path(str(source_state.get("path", "")))
    source_identity_green = (
        mame_source.get("result") == "green"
        and same_mame_identity(
            {
                "version": mame_source.get("mame_version"),
                "sha256": mame_source.get("mame_sha256"),
                "snap_revision": mame_source.get("mame_snap_revision"),
                "gnome_content_revision": mame_source.get(
                    "mame_gnome_content_revision"
                ),
            },
            mame,
        )
        and mame_source.get("mame_rom_set_sha256")
        == sha256(ROOT / "tools/mame-trace/roms/superman.zip")
        # The retained original-code source capture predates later tooling
        # improvements.  Authenticate its saved MAME state and its recorded
        # immutable capture digests instead of requiring its historical
        # script bytes to equal the current validator source.
        and isinstance(mame_source.get("capture_tool_sha256"), str)
        and len(str(mame_source.get("capture_tool_sha256"))) == 64
        and isinstance(mame_source.get("capture_lua_sha256"), str)
        and len(str(mame_source.get("capture_lua_sha256"))) == 64
        and source_state_path.is_file()
        and sha256(source_state_path) == source_state.get("sha256")
    )
    branch_lineage_green = all(
        branch["summary"]["source_state_sha256"]
        == source_state["sha256"]
        and branch["summary"]["mame_rom_set_sha256"]
        == mame_source["mame_rom_set_sha256"]
        and branch["summary"]["branch_lua_sha256"]
        == sha256(ROOT / "tools/mame-trace/branch_crate_carry.lua")
        for branch in (
            (mame_held,)
            if args.flight_carry_only
            else (mame_held, mame_thrown)
        )
    )
    if not source_identity_green or not branch_lineage_green:
        raise RuntimeError("MAME pre-throw source capture is not green")
    if current_root_pair:
        focused_root_evidence = {
            "kind": "current_rom_split_emitter_consumer",
            "emitter": load_current_root_events(
                args.emitter_root_events,
                label="emitter",
                rom_hash=rom_hash,
                mame=mame,
                expected_total=4,
                expected_cases={
                    "crate-emitter-held-response-2000",
                    "crate-emitter-thrown-response-2001",
                },
            ),
            "consumer": load_current_root_events(
                args.consumer_root_events,
                label="consumer",
                rom_hash=rom_hash,
                mame=mame,
                expected_total=6,
                expected_cases={
                    "crate-consumer-held-response-2000",
                    "crate-consumer-thrown-response-2001",
                },
            ),
        }
    else:
        bounded_root = json.loads(
            args.bounded_root_summary.read_text(encoding="utf-8")
        )
        bounded_events_path = Path(str(bounded_root.get("events", "")))
        if (
            bounded_root.get("result") != "green"
            or int(bounded_root.get("green", -1)) != 12
            or int(bounded_root.get("red", -1)) != 0
            or not bounded_events_path.is_file()
            or bounded_root.get("events_sha256")
            != sha256(bounded_events_path)
            or not same_mame_identity(
                dict(bounded_root.get("mame") or {}), mame
            )
            or bounded_root.get("mame_rom_set_sha256")
            != mame_source["mame_rom_set_sha256"]
        ):
            raise RuntimeError(
                "historical bounded exact root differential is not green12/12"
            )
        focused_root_evidence = {
            "kind": "historical_combined_root",
            "summary": str(args.bounded_root_summary.resolve()),
            "summary_sha256": sha256(args.bounded_root_summary),
            "result": bounded_root["result"],
            "green": bounded_root["green"],
            "red": bounded_root["red"],
        }

    mame_health_writes = (
        [] if mame_thrown is None else mame_thrown["health_writes"]
    )
    health_offsets = [
        ENEMY_SLOT_BASE + slot * ENEMY_SLOT_STRIDE + ENEMY_HEALTH_OFFSET
        for slot in range(ENEMY_SLOT_COUNT)
    ]
    health_watch_addresses = [
        0x400000 | offset for offset in health_offsets
    ]
    mame_branches = (
        (mame_held,)
        if args.flight_carry_only
        else (mame_held, mame_thrown)
    )
    mame_checks = {
        "true_pre_movem_entry_boundaries": all(
            row["entry_pc_after_opcode_fetch"] == 0x003A94
            and row["post_prologue_pc_at_first_work_read"] == 0x003AA4
            and row["post_prologue_a7"] == row["entry_a7"] - 0x3C
            and row["data_address_registers_same"]
            and row["sr_privilege_and_interrupt_mask_same"]
            and row["differences_confined_to_movem_frame"]
            and 0 < row["difference_count"] <= 0x3C
            for branch in mame_branches
            for row in branch["boundary_checks"]
        ),
        "held_real_contact": bool(mame_held["contacts"]),
        "held_zero_health_writes": len(mame_held["health_writes"]) == 0,
        "held_no_active_enemy_health_decrease": (
            mame_held["health_transitions"] == []
        ),
        "x1_controls_retained": all(
            int(row["x1_ctrl_3601"]) == 0x10
            and int(row["x1_ctrl_3603"]) == 0x21
            for branch in mame_branches
            for row in branch["entries"].values()
        ),
        "no_pending_irq_overrun": not any(
            row.get("event") == "pending_irq_overrun"
            for branch in mame_branches
            for row in branch["rows"]
        ),
    }
    if args.flight_carry_only:
        flight_y = [
            int(row["player_y"])
            for row in mame_held["entries"].values()
        ]
        flight_contacts = [
            row for row in mame_held["contacts"]
            if int(row["buttons"]) & 0x0010
        ]
        mame_checks.update(
            {
                # Flight is selected with Up.  The horizontal direction is an
                # intentional part of the recorded route, rather than an
                # undocumented requirement of this validation.
                "flight_control_route_contains_up": bool(
                    (args.held_mask | switch_mask) & 0x0010
                ),
                # This is a collision test, not merely a flying animation
                # test: the carried crate has to be presented to an enemy in
                # the arcade oracle before its no-damage result is meaningful.
                "flight_carried_enemy_contact": bool(flight_contacts),
                "flight_has_material_vertical_progress": (
                    max(flight_y) - min(flight_y) >= 64
                ),
                "flight_input_latency_explicit": (
                    [
                        int(mame_held["entries"][tick]["player_input"])
                        for tick in range(3214, 3218)
                    ][:3]
                    == [0xFE, 0xFE, 0xFF]
                    and int(mame_held["entries"][3217]["player_input"])
                    != 0xFF
                ),
            }
        )
    else:
        assert mame_thrown is not None
        mame_checks.update(
            {
                "held_contact_tick_set": [
                    int(row["tick"]) for row in mame_held["contacts"]
                ]
                == list(range(3253, 3270)),
                "thrown_real_contact": bool(mame_thrown["contacts"]),
                "thrown_contact_begins_at_3255": (
                    int(mame_thrown["contacts"][0]["tick"]) == 3255
                ),
                "thrown_two_health_writes": len(mame_health_writes) == 2,
                "thrown_damage_is_one": all(
                    (int(row["damage_D3"]) & 0xFF)
                    == 1 for row in mame_health_writes
                ),
                "thrown_active_enemy_health_transitions": (
                    mame_thrown["health_transitions"]
                    == [
                        {
                            "tick": 3274,
                            "previous_tick": 3273,
                            "slot": 0,
                            "health_address": "F02BB7",
                            "before": 1,
                            "after": 0,
                        },
                        {
                            "tick": 3283,
                            "previous_tick": 3282,
                            "slot": 1,
                            "health_address": "F02C61",
                            "before": 1,
                            "after": 0,
                        },
                    ]
                ),
                "same_prethrow_state": all(
                    mame_held["works"][tick]
                    == mame_thrown["works"][tick]
                    for tick in range(BRANCH_TICK, THROW_TICK + 1)
                ),
                "arcade_branch_input_latency_explicit": (
            [
                int(mame_held["entries"][tick]["player_input"])
                for tick in range(3214, 3218)
            ]
            == [0xFE, 0xFE, 0xFF, 0xF5]
            and int(mame_thrown["entries"][3250]["player_input"])
            == 0xF5
            and int(mame_thrown["entries"][3251]["player_input"])
            == 0xE5
            and int(mame_thrown["entries"][3252]["player_input"])
            == 0xF5
                ),
            }
        )
    if not all(mame_checks.values()):
        raise RuntimeError(f"MAME branch contract failed: {mame_checks}")

    args.output.mkdir(parents=True)
    configurations: list[dict[str, Any]] = []
    next_port = args.port
    branch_specs = (
        (("flight_carried_contact", False, mame_held),)
        if args.flight_carry_only
        else (
            ("held_contact", False, mame_held),
            ("legitimate_throw", True, mame_thrown),
        )
    )
    for branch_name, thrown, oracle in branch_specs:
        assert oracle is not None
        for native_on in (False, True):
            configurations.append(
                run_snes_branch(
                    args=args,
                    branch_name=branch_name,
                    thrown=thrown,
                    held_mask=args.held_mask,
                    switch_tick=args.switch_tick,
                    switch_mask=switch_mask,
                    native_on=native_on,
                    port=next_port,
                    state_path=state_path,
                    state_metadata=state_metadata,
                    safe_context=safe_context,
                    inputs=inputs,
                    mame_branch=oracle,
                    health_watch_addresses=health_watch_addresses,
                    health_offsets=health_offsets,
                    output=args.output,
                )
            )
            next_port += 1

    cross_configuration_checks: dict[str, bool] = {}
    for branch_name, _thrown, _oracle in branch_specs:
        rows = [
            row
            for row in configurations
            if row["branch"] == branch_name
        ]
        cross_configuration_checks[
            f"{branch_name}_both_snes_configs_green"
        ] = len(rows) == 2 and all(row["result"] == "green" for row in rows)
        if len(rows) == 2:
            by_configuration = {
                row["configuration"]: row for row in rows
            }
            off = by_configuration[
                "snes-gameplay-root-off-scheduler-pacing-preserved"
            ]["irq_cadence"]
            on = by_configuration["snes-native-on"]["irq_cadence"]
            cross_configuration_checks[
                f"{branch_name}_tick_boundary_count_exact_off_on"
            ] = (
                off["tick_boundary_00f5a3_hits"]
                == on["tick_boundary_00f5a3_hits"]
                == END_TICK - BRANCH_TICK
            )
            cross_configuration_checks[
                f"{branch_name}_virtual_irq_count_exact_off_on"
            ] = (
                off["virtual_irq_00b404_hits"]
                == on["virtual_irq_00b404_hits"]
                and off["virtual_irq_00b404_hits"] > 0
            )
            cross_configuration_checks[
                f"{branch_name}_virtual_irq_pending_exact_off_on"
            ] = (
                off["pending_00aa_at_entries"]
                == on["pending_00aa_at_entries"]
            )
            cross_configuration_checks[
                f"{branch_name}_virtual_irq_countdown_exact_off_on"
            ] = (
                off["countdown_00ac_at_entries"]
                == on["countdown_00ac_at_entries"]
            )

    summary = {
        "event": "summary",
        "result": (
            "green"
            if (
                all(mame_checks.values())
                and all(cross_configuration_checks.values())
            )
            else "red"
        ),
        "classification": (
            (
                (
                    "no carried-flight crate-contact discrepancy in the "
                    "tested checkpoint branch: a carried crate remains "
                    "nondamaging while flying into an enemy"
                    if args.flight_carry_only
                    else "no crate-contact discrepancy in the tested "
                    "checkpoint branch: carried contact is nondamaging and "
                    "legitimate throw damage matches original code"
                )
            )
            if (
                all(mame_checks.values())
                and all(cross_configuration_checks.values())
            )
            else (
                "crate three-way discrepancy remains; inspect the red "
                "configuration and do not accept the checkpoint branch"
            )
        ),
        "mame_checks": mame_checks,
        "cross_configuration_checks": cross_configuration_checks,
        "configurations": configurations,
        "health_watch_addresses": [
            f"{address:06X}" for address in health_watch_addresses
        ],
        "health_offsets": [f"F0{offset:04X}" for offset in health_offsets],
        "checkpoint_lineage": {
            "kind": (
                "focused_cross_rom_migration"
                if safe_context["rom_migration"] is not None
                else "fresh_boot_root_checkpoint_continuation"
            ),
            "rom_migration": safe_context["rom_migration"],
            "events": str(args.safe_events.resolve()),
            "events_sha256": sha256(args.safe_events),
            "rom_sha256": fresh_provenance["rom_sha256"],
            "safe_state": str(state_path),
            "safe_state_sha256": sha256(state_path),
        },
        "mame": {
            "version": mame["version"],
            "executable": mame["path"],
            "executable_sha256": mame["sha256"],
            "snap_revision": mame["snap_revision"],
            "gnome_content_revision": mame[
                "gnome_content_revision"
            ],
            "source_capture": str(args.mame_source_summary.resolve()),
            "source_capture_sha256": sha256(args.mame_source_summary),
            "held_events": str(mame_held["events"].resolve()),
            "held_events_sha256": mame_held["events_sha256"],
            "thrown_events": (
                None
                if mame_thrown is None
                else str(mame_thrown["events"].resolve())
            ),
            "thrown_events_sha256": (
                None if mame_thrown is None else mame_thrown["events_sha256"]
            ),
            "branch_lua": str(
                (ROOT / "tools/mame-trace/branch_crate_carry.lua").resolve()
            ),
            "branch_lua_sha256": sha256(
                ROOT / "tools/mame-trace/branch_crate_carry.lua"
            ),
        },
        "nexen_identity": campaign.nexen_identity(args.nexen),
        "rom": str(args.rom.resolve()),
        "rom_sha256": rom_hash,
        "timeline": str(args.timeline.resolve()),
        "timeline_sha256": sha256(args.timeline),
        "focused_collision_root_evidence": focused_root_evidence,
        "scope": (
            "organic controller branch through real contact plus bounded "
            "exact collision-root register/CCR/X/stack differential; "
            "gameplay-root-off preserves scheduler/pacing and reports "
            "physical timing without normalization; MAME IRQ cadence is not "
            "yet compared; not fresh-boot continuation beyond tick 3300 or fps"
        ),
        "flight_carry_only": args.flight_carry_only,
        "held_mask": args.held_mask,
        "switch_tick": args.switch_tick,
        "switch_mask": switch_mask,
        "organic_mame_irq_cadence_proven": False,
        "time_unix": time.time(),
    }
    summary_path = args.output / "summary.json"
    summary_path.write_text(
        json.dumps(summary, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(
        json.dumps(
            {
                "result": summary["result"],
                "mame_checks": mame_checks,
                "cross_configuration_checks": (
                    cross_configuration_checks
                ),
                "summary": str(summary_path.resolve()),
            },
            sort_keys=True,
        ),
        flush=True,
    )
    return 0 if summary["result"] == "green" else 1


if __name__ == "__main__":
    raise SystemExit(main())
