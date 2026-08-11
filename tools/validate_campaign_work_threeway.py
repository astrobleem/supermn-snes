#!/usr/bin/env python3
"""Compare one fresh-lineage campaign tick across MAME/native-off/native-on.

The three inputs are produced by ``capture_mame_movie_ticks.py`` and
``capture_snes_movie_ticks.py``.  This validator deliberately separates
game-owned records from scheduler/presentation scratch: a slower native-off
arm receives many more virtual IRQ opportunities before the same game-tick
boundary, so its active task stack and renderer source residue need not match
the production arm even when the completed gameplay state does.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any


WORK_SIZE = 0x10000
GAMEPLAY_REGIONS = {
    # These are the game-owned records exercised by the retained campaign.
    # Do not widen this to $0100-$0FFF: that range also contains most of the
    # coroutine stacks, including saved RTE status/PC frames.
    "primary_enemy_record": (0x02DA, 0x034A),
    "boss_record_window": (0x0A50, 0x0AE0),
    "player_record": (0x12A2, 0x1312),
    "rng_state": (0x170E, 0x1710),
}
DIAGNOSTIC_REGIONS = {
    "scheduler_header": (0x0000, 0x004A),
    "task_stack_and_locals": (0x004A, 0x1712),
    "renderer_source": (0x1712, 0x3000),
    # $025110 uses five adjacent collision/response lists.  The earlier
    # $39F4 limit covered only the first two and silently omitted the
    # $3A54/$3A74 Stage-2 rows that drive player wall response.
    "collision_table_raw_including_inactive_residue": (0x3734, 0x3CC4),
    "work_tail": (0x3F00, 0x4000),
    "upper_48k": (0x4000, 0x10000),
}
TASK_CONTEXT_OFFSET = 0x000A
TASK_CONTEXT_COUNT = 16
TASK_REGISTER_BYTES = 15 * 4
COLLISION_START = 0x3734
COLLISION_END = 0x3CC4
COLLISION_RECORD_SIZE = 0x10
REGISTERS = tuple(
    [f"D{index}" for index in range(8)]
    + [f"A{index}" for index in range(8)]
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--mame-dir", type=Path, required=True)
    parser.add_argument("--native-off-dir", type=Path, required=True)
    parser.add_argument("--native-on-dir", type=Path, required=True)
    parser.add_argument("--pre-tick", type=int, required=True)
    parser.add_argument("--post-tick", type=int, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument(
        "--allow-forensic-nonresumable-captures",
        action="store_true",
        help=(
            "diagnostic only: compare captures whose summaries do not prove "
            "an authenticated safe checkpoint; result is labeled "
            "forensic_only and cannot be green production evidence"
        ),
    )
    args = parser.parse_args()
    if args.post_tick != args.pre_tick + 1:
        parser.error("--post-tick must immediately follow --pre-tick")
    if args.output.exists():
        parser.error(f"output already exists: {args.output}")
    return args


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def read_work(path: Path) -> bytes:
    data = path.read_bytes()
    if len(data) != WORK_SIZE:
        raise RuntimeError(
            f"{path}: expected {WORK_SIZE} bytes, observed {len(data)}"
        )
    return data


def differing_offsets(left: bytes, right: bytes) -> list[int]:
    return [
        offset
        for offset, (lhs, rhs) in enumerate(zip(left, right, strict=True))
        if lhs != rhs
    ]


def be16(data: bytes, offset: int = 0) -> int:
    return int.from_bytes(data[offset : offset + 2], "big")


def be32(data: bytes, offset: int = 0) -> int:
    return int.from_bytes(data[offset : offset + 4], "big")


def decode_task_contexts(work: bytes) -> list[dict[str, Any]]:
    contexts = []
    for task in range(TASK_CONTEXT_COUNT):
        saved_sp = be32(work, TASK_CONTEXT_OFFSET + task * 4)
        row: dict[str, Any] = {
            "task": task,
            "saved_sp": f"{saved_sp:08X}",
            "initialized": saved_sp != 0,
        }
        offset = saved_sp & 0xFFFF
        frame_end = offset + TASK_REGISTER_BYTES + 6
        if saved_sp >> 16 == 0x00F0 and frame_end <= WORK_SIZE:
            saved_sr = be16(work, offset + TASK_REGISTER_BYTES)
            row.update(
                {
                    "saved_sr": f"{saved_sr:04X}",
                    "saved_ccr_xnzvc": saved_sr & 0x1F,
                    "saved_interrupt_mask": (saved_sr >> 8) & 7,
                    "resume_pc": (
                        f"{be32(work, offset + TASK_REGISTER_BYTES + 2):08X}"
                    ),
                    "register_frame_hex": work[
                        offset : offset + TASK_REGISTER_BYTES
                    ].hex(),
                    "frame_hex": work[
                        offset : offset + TASK_REGISTER_BYTES + 6
                    ].hex(),
                }
            )
        contexts.append(row)
    return contexts


def compare_task_contexts(left: bytes, right: bytes) -> dict[str, Any]:
    left_rows = decode_task_contexts(left)
    right_rows = decode_task_contexts(right)
    mismatches = []
    for left_row, right_row in zip(left_rows, right_rows, strict=True):
        fields = {}
        for field in (
            "saved_sp",
            "saved_sr",
            "saved_ccr_xnzvc",
            "saved_interrupt_mask",
            "resume_pc",
            "register_frame_hex",
        ):
            if left_row.get(field) != right_row.get(field):
                fields[field] = {
                    "left": left_row.get(field),
                    "right": right_row.get(field),
                }
        if fields:
            mismatches.append({"task": left_row["task"], "fields": fields})
    return {
        "saved_sp_equal": all(
            left_row["saved_sp"] == right_row["saved_sp"]
            for left_row, right_row in zip(
                left_rows, right_rows, strict=True
            )
        ),
        "saved_status_equal": all(
            left_row.get("saved_sr") == right_row.get("saved_sr")
            for left_row, right_row in zip(
                left_rows, right_rows, strict=True
            )
        ),
        "saved_register_frame_equal": all(
            left_row.get("register_frame_hex")
            == right_row.get("register_frame_hex")
            for left_row, right_row in zip(
                left_rows, right_rows, strict=True
            )
        ),
        "resume_pc_equal": all(
            left_row.get("resume_pc") == right_row.get("resume_pc")
            for left_row, right_row in zip(
                left_rows, right_rows, strict=True
            )
        ),
        "mismatches": mismatches,
        "left": left_rows,
        "right": right_rows,
    }


def compare_collision_records(left: bytes, right: bytes) -> dict[str, Any]:
    active_mismatches = []
    inactive_residue_offsets = []
    active_rows_left = 0
    active_rows_right = 0
    for offset in range(
        COLLISION_START, COLLISION_END, COLLISION_RECORD_SIZE
    ):
        left_row = left[offset : offset + COLLISION_RECORD_SIZE]
        right_row = right[offset : offset + COLLISION_RECORD_SIZE]
        left_active = be16(left_row) != 0
        right_active = be16(right_row) != 0
        active_rows_left += int(left_active)
        active_rows_right += int(right_active)
        if left_active or right_active:
            if left_row != right_row:
                active_mismatches.append(
                    {
                        "address": f"F0{offset:04X}",
                        "left": left_row.hex(),
                        "right": right_row.hex(),
                    }
                )
            continue
        inactive_residue_offsets.extend(
            offset + relative
            for relative, (lhs, rhs) in enumerate(
                zip(left_row[2:], right_row[2:], strict=True), start=2
            )
            if lhs != rhs
        )
    return {
        "semantic_equal": not active_mismatches,
        "active_rows_left": active_rows_left,
        "active_rows_right": active_rows_right,
        "active_mismatches": active_mismatches,
        "inactive_residue_different_bytes": len(inactive_residue_offsets),
        "inactive_residue_first_offsets": [
            f"{offset:04X}" for offset in inactive_residue_offsets[:32]
        ],
    }


def compare_work(left: bytes, right: bytes) -> dict[str, Any]:
    offsets = differing_offsets(left, right)
    regions = {}
    for name, (start, end) in {
        **GAMEPLAY_REGIONS,
        **DIAGNOSTIC_REGIONS,
    }.items():
        region_offsets = [
            offset for offset in offsets if start <= offset < end
        ]
        regions[name] = {
            "different_bytes": len(region_offsets),
            "equal": not region_offsets,
            "first_offsets": [
                f"{offset:04X}" for offset in region_offsets[:32]
            ],
        }
    return {
        "different_bytes": len(offsets),
        "equal": not offsets,
        "first_offsets": [f"{offset:04X}" for offset in offsets[:64]],
        "regions": regions,
        "task_contexts": compare_task_contexts(left, right),
        "collision_records": compare_collision_records(left, right),
    }


def read_snes_boundaries(
    directory: Path, ticks: tuple[int, int]
) -> dict[int, dict[str, Any]]:
    path = directory / "captures.jsonl"
    rows = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        row = json.loads(line)
        if row.get("event") != "boundary":
            continue
        tick = int(row["mame_tick"])
        if tick in ticks:
            rows[tick] = row
    if set(rows) != set(ticks):
        raise RuntimeError(
            f"{path}: captured ticks {sorted(rows)}, expected {list(ticks)}"
        )
    return rows


def read_snes_summary(directory: Path) -> dict[str, Any]:
    path = directory / "summary.json"
    if not path.is_file():
        raise RuntimeError(f"missing SNES capture summary: {path}")
    return json.loads(path.read_text(encoding="utf-8"))


def read_mame_boundaries(
    directory: Path, ticks: tuple[int, int]
) -> dict[int, dict[str, Any]]:
    path = directory / "capture.jsonl"
    rows = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        row = json.loads(line)
        if row.get("event") != "boundary":
            continue
        tick = int(row["tick"])
        if tick in ticks:
            rows[tick] = row
    if set(rows) != set(ticks):
        raise RuntimeError(
            f"{path}: captured ticks {sorted(rows)}, expected {list(ticks)}"
        )
    return rows


def normalize_mame_registers(row: dict[str, Any]) -> dict[str, str]:
    return {
        name: f"{int(row[name]) & 0xFFFFFFFF:08X}" for name in REGISTERS
    }


def compare_registers(
    left: dict[str, str], right: dict[str, str]
) -> dict[str, Any]:
    mismatches = {
        name: {"left": left[name], "right": right[name]}
        for name in REGISTERS
        if left[name] != right[name]
    }
    return {
        "equal": not mismatches,
        "mismatches": mismatches,
    }


def player_projection(row: dict[str, Any]) -> dict[str, int]:
    player = row["player"]
    return {
        name: int(player[name])
        for name in ("health", "x", "y", "action")
    }


def main() -> int:
    args = parse_args()
    ticks = (args.pre_tick, args.post_tick)

    paths: dict[str, Path] = {}
    work: dict[str, bytes] = {}
    for tick, phase in zip(ticks, ("pre", "post"), strict=True):
        paths[f"mame_{phase}"] = (
            args.mame_dir / f"mame-tick-{tick:05d}.work.bin"
        )
        paths[f"native_off_{phase}"] = (
            args.native_off_dir / f"snes-tick-{tick:05d}.work.bin"
        )
        paths[f"native_on_{phase}"] = (
            args.native_on_dir / f"snes-tick-{tick:05d}.work.bin"
        )
    for name, path in paths.items():
        if not path.is_file():
            raise RuntimeError(f"missing {name}: {path}")
        work[name] = read_work(path)

    native_off = read_snes_boundaries(args.native_off_dir, ticks)
    native_on = read_snes_boundaries(args.native_on_dir, ticks)
    native_off_summary = read_snes_summary(args.native_off_dir)
    native_on_summary = read_snes_summary(args.native_on_dir)
    capture_resumability = {
        "native_off": native_off_summary.get("state_resumability", {}),
        "native_on": native_on_summary.get("state_resumability", {}),
    }
    safe_capture_lineage = all(
        isinstance(row, dict)
        and row.get("resumable_checkpoint") is True
        and row.get("explicit_override") is False
        for row in capture_resumability.values()
    )
    if (
        not safe_capture_lineage
        and not args.allow_forensic_nonresumable_captures
    ):
        raise RuntimeError(
            "SNES capture summaries do not prove authenticated resumable "
            "start states; rerun from safe checkpoints or explicitly select "
            "--allow-forensic-nonresumable-captures"
        )
    args.output.mkdir(parents=True)
    mame = read_mame_boundaries(args.mame_dir, ticks)

    comparisons = {
        "pre": {
            "mame_vs_native_off": compare_work(
                work["mame_pre"], work["native_off_pre"]
            ),
            "mame_vs_native_on": compare_work(
                work["mame_pre"], work["native_on_pre"]
            ),
            "native_off_vs_on": compare_work(
                work["native_off_pre"], work["native_on_pre"]
            ),
        },
        "post": {
            "mame_vs_native_off": compare_work(
                work["mame_post"], work["native_off_post"]
            ),
            "mame_vs_native_on": compare_work(
                work["mame_post"], work["native_on_post"]
            ),
            "native_off_vs_on": compare_work(
                work["native_off_post"], work["native_on_post"]
            ),
        },
    }

    post_mame_registers = normalize_mame_registers(mame[args.post_tick])
    post_off_registers = native_off[args.post_tick]["m68k"]["registers"]
    post_on_registers = native_on[args.post_tick]["m68k"]["registers"]
    register_comparisons = {
        "mame_vs_native_off": compare_registers(
            post_mame_registers, post_off_registers
        ),
        "mame_vs_native_on": compare_registers(
            post_mame_registers, post_on_registers
        ),
        "native_off_vs_on": compare_registers(
            post_off_registers, post_on_registers
        ),
    }
    boundary_register_diagnostics = {
        "native_on_post_gprs_except_a7_match_mame": set(
            register_comparisons["mame_vs_native_on"]["mismatches"]
        )
        <= {"A7"},
        "native_off_post_gprs_except_a7_match_mame": set(
            register_comparisons["mame_vs_native_off"]["mismatches"]
        )
        <= {"A7"},
    }

    gameplay_checks = {}
    scheduler_diagnostics = {}
    for phase in ("pre", "post"):
        for comparison_name, comparison in comparisons[phase].items():
            for region in GAMEPLAY_REGIONS:
                gameplay_checks[
                    f"{phase}_{comparison_name}_{region}_exact"
                ] = comparison["regions"][region]["equal"]
            gameplay_checks[
                f"{phase}_{comparison_name}_active_collision_records_exact"
            ] = comparison["collision_records"]["semantic_equal"]
            scheduler_diagnostics[
                f"{phase}_{comparison_name}_task_saved_sp_exact"
            ] = comparison["task_contexts"]["saved_sp_equal"]
            scheduler_diagnostics[
                f"{phase}_{comparison_name}_task_saved_status_exact"
            ] = comparison["task_contexts"]["saved_status_equal"]
            scheduler_diagnostics[
                f"{phase}_{comparison_name}_task_resume_pc_exact"
            ] = comparison["task_contexts"]["resume_pc_equal"]
    checks = {
        "native_off_capture_declares_disabled_gameplay_roots": (
            native_off_summary.get("gameplay_native") in {"off", "all-off"}
            and all(
                int(native_off[tick]["gates"]["071a"]) == 0
                and int(native_off[tick]["gates"]["073a"]) == 0
                for tick in ticks
            )
        ),
        "native_on_capture_declares_enabled_gameplay_roots": (
            native_on_summary.get("gameplay_native") == "on"
            and all(
                int(native_on[tick]["gates"]["071a"]) != 0
                and int(native_on[tick]["gates"]["073a"]) != 0
                for tick in ticks
            )
        ),
        "same_snes_prestate": comparisons["pre"]["native_off_vs_on"][
            "equal"
        ],
        "native_off_player_matches_movie": all(
            native_off[tick]["player_comparison"]["result"] == "green"
            for tick in ticks
        ),
        "native_on_player_matches_movie": all(
            native_on[tick]["player_comparison"]["result"] == "green"
            for tick in ticks
        ),
        "task_masks_match_post": (
            int(native_off[args.post_tick]["task_mask"])
            == int(native_on[args.post_tick]["task_mask"])
        ),
        "halt_zero": (
            int(native_off[args.post_tick]["halt"]) == 0
            and int(native_on[args.post_tick]["halt"]) == 0
        ),
        **gameplay_checks,
    }

    semantic_green = all(checks.values())
    result = (
        "green"
        if semantic_green and safe_capture_lineage
        else "forensic_only"
        if semantic_green
        else "red"
    )
    scheduler_phase_difference = (
        not all(scheduler_diagnostics.values())
        or not all(boundary_register_diagnostics.values())
    )
    summary = {
        "result": result,
        "classification": (
            "nonresumable_source_forensic_only_no_causal_claim"
            if not safe_capture_lineage
            else
            (
                "gameplay_state_exact_with_hardware_boundary_timing_differences"
                if scheduler_phase_difference
                else "gameplay_and_scheduler_state_exact"
            )
            if semantic_green
            else "unclassified_threeway_campaign_state_difference"
        ),
        "scope": (
            "one-tick same-checkpoint MAME 0.287/SNES gameplay-root-off/"
            "production-on "
            "campaign differential; exact game-owned object/player/RNG/"
            "collision regions plus explicit scheduler/renderer/IRQ diagnostics; "
            + (
                "authenticated checkpointed focused evidence, not fresh-boot "
                "or FPS proof"
                if safe_capture_lineage
                else "explicit nonresumable-source forensic comparison; no "
                "production or causal claim"
            )
        ),
        "ticks": {"pre": args.pre_tick, "post": args.post_tick},
        "safe_capture_lineage": safe_capture_lineage,
        "capture_resumability": capture_resumability,
        "allow_forensic_nonresumable_captures": (
            args.allow_forensic_nonresumable_captures
        ),
        "inputs": {
            name: {
                "path": str(path.resolve()),
                "sha256": sha256(path),
            }
            for name, path in paths.items()
        },
        "checks": checks,
        "snes_capture_configurations": {
            "native_off_directory": {
                "gameplay_native": native_off_summary.get("gameplay_native"),
                "pre_gates": native_off[args.pre_tick]["gates"],
                "post_gates": native_off[args.post_tick]["gates"],
            },
            "native_on_directory": {
                "gameplay_native": native_on_summary.get("gameplay_native"),
                "pre_gates": native_on[args.pre_tick]["gates"],
                "post_gates": native_on[args.post_tick]["gates"],
            },
        },
        "scheduler_diagnostics": scheduler_diagnostics,
        "boundary_register_diagnostics": boundary_register_diagnostics,
        "comparisons": comparisons,
        "register_comparisons": register_comparisons,
        "boundary_state": {
            "mame": {
                "pre": mame[args.pre_tick],
                "post": mame[args.post_tick],
            },
            "native_off": {
                "pre": native_off[args.pre_tick],
                "post": native_off[args.post_tick],
            },
            "native_on": {
                "pre": native_on[args.pre_tick],
                "post": native_on[args.post_tick],
            },
        },
        "timing": {
            "native_off_video_frames": (
                int(native_off[args.post_tick]["video_frame"])
                - int(native_off[args.pre_tick]["video_frame"])
            ),
            "native_on_video_frames": (
                int(native_on[args.post_tick]["video_frame"])
                - int(native_on[args.pre_tick]["video_frame"])
            ),
            "native_off_irq_countdown_post": int(
                native_off[args.post_tick]["virtual_irq_countdown"]
            ),
            "native_on_irq_countdown_post": int(
                native_on[args.post_tick]["virtual_irq_countdown"]
            ),
        },
        "notes": [
            (
                "MAME's boundary is a work-RAM read tap in $003A92-$003AB0; "
                "the SNES campaign stops on its synthetic game-tick hook. "
                "Live GPRs, CCR/X, and below-A7 residue are therefore reported "
                "as boundary diagnostics but are not claimed same-instruction "
                "lockstep. Function-entry differentials own those exactness "
                "claims."
            ),
            (
                "Native-off takes more video frames and virtual IRQ "
                "opportunities to complete the tick. Its active A7/stack phase "
                "may differ while the completed gameplay records remain exact."
            ),
            (
                "A capture mode of 'off' disables the gameplay xlat/choke "
                "roots ($071A/$073A) but retains native scheduler machinery; "
                "only 'all-off' disables those scheduler gates too. Exact "
                "all-escape-off claims must come from a compatible all-off or "
                "function-entry differential."
            ),
            (
                "Collision rows whose leading active word is zero are compared "
                "only for inactive status. Their trailing bytes are stale slot "
                "residue and are reported separately instead of being promoted "
                "to a gameplay mismatch."
            ),
            (
                "Coroutine saved-SP, saved-SR/CCR/X, interrupt mask, and resume "
                "PC fields are decoded from each initialized task frame. They "
                "are scheduler architecture, not enemy-object bytes. Exactness "
                "is reported under scheduler_diagnostics but does not gate the "
                "gameplay-state verdict at these asynchronous boundaries."
            ),
        ],
    }
    output_path = args.output / "summary.json"
    output_path.write_text(
        json.dumps(summary, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(
        json.dumps(
            {
                "result": result,
                "classification": summary["classification"],
                "summary": str(output_path.resolve()),
            },
            sort_keys=True,
        ),
        flush=True,
    )
    return 0 if semantic_green else 1


if __name__ == "__main__":
    raise SystemExit(main())
