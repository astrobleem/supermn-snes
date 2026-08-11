#!/usr/bin/env python3
"""Regression for MAME-movie to SNES controller/tick synchronization.

The fresh-playthrough driver originally labeled its gameplay-origin boundary
as arcade tick 222 even though its active object/collision state matches tick
221.  It then installed each physical controller transition at T-1 and used
the exporter's later frame-done `input` row as the state oracle.  Those errors
made gameplay consume input early and produced false collision/state failures.

This validator ties the corrected scheduling source to retained exact-emulator
evidence around the first movie transition.  It also guards the fresh-campaign
coin boundary and mandatory gameplay-origin RNG check: matching player
coordinates alone are insufficient because an RNG phase error can remain latent
for thousands of ticks.  With Left installed at tick 1054, the player, active
enemy, and collision table must match uninterrupted MAME at every boundary from
1053 through 1059.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
EVIDENCE = ROOT / "build" / "playtest-investigation-20260725"
DEFAULT_ROM = ROOT / "build" / "interp.sfc"
DEFAULT_SNES = EVIDENCE / "controller-alignment-snes-700f46f-nexen-green-v1"
DEFAULT_MAME = EVIDENCE / "organic-extra-player-hit-mame-1040-1060-dense-v1"
DEFAULT_ORIGIN_SNES = (
    EVIDENCE / "gameplay-origin-work-700f46f-nexen-v1"
    / "snes-tick-00222.work.bin"
)
DEFAULT_ORIGIN_MAME = (
    EVIDENCE / "gameplay-origin-mame-220-223-v1"
    / "mame-tick-00221.work.bin"
)
CAMPAIGN_SOURCE = ROOT / "tools" / "replay_mame_controller_campaign.py"
CAPTURE_SOURCE = ROOT / "tools" / "capture_snes_movie_ticks.py"
TICKS = tuple(range(1053, 1060))
REGIONS = {
    "player_record": (0x12A2, 0x70),
    "active_enemy_record": (0x02DA, 0x70),
    "collision_table": (0x3734, 0x02C0),
}


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def compare(left: bytes, right: bytes, base: int) -> dict[str, Any]:
    offsets = [
        index
        for index, (lhs, rhs) in enumerate(zip(left, right))
        if lhs != rhs
    ]
    return {
        "equal": not offsets,
        "different_bytes": len(offsets),
        "first": [f"F0{base + index:04X}" for index in offsets[:32]],
    }


def source_regression() -> dict[str, Any]:
    campaign = CAMPAIGN_SOURCE.read_text(encoding="utf-8")
    capture = CAPTURE_SOURCE.read_text(encoding="utf-8")
    input_start = campaign.index(
        "                for event in inputs:\n"
    )
    input_stop = campaign.index(
        "                for event in boss_events:\n",
        input_start,
    )
    block = campaign[input_start:input_stop]
    required = {
        "origin_maps_to_declared_tick": (
            "mapped_origin_tick = segment_origin_tick\n" in campaign
            and "else args.mame_origin_tick\n" in campaign
            and "mapped_origin_tick = args.mame_origin_tick + 1" not in campaign
        ),
        "compare_at_input_tick": (
            'events_by_tick[event.tick].append(\n'
            '                            ("input_compare", event)\n'
            in block
        ),
        "apply_at_input_tick": (
            'events_by_tick[event.tick].append(\n'
            '                            ("input_apply", event)\n'
            in block
            and "events_by_tick[event.tick - 1]" not in block
        ),
        "response_checked_at_t_plus_2": (
            "events_by_tick[event.tick + 2].append(" in block
            and '("input_response_compare", event)' in block
        ),
        "checkpoint_replay_default_offset_zero": (
            'default=0,\n'
            '        help=(\n'
            '            "apply a movie transition at T (default);' in capture
            and "event.tick + args.input_apply_offset" in capture
        ),
        "campaign_events_come_from_tick_rows": (
            'previous_buttons = int(tick_rows[origin_tick]["snes_buttons"])'
            in campaign
            and "inputs.append(InputEvent(tick, buttons, row))" in campaign
            and 'elif row.get("event") == "input"' not in campaign
        ),
        "fresh_campaign_default_rng_aligned": (
            '"--cold-boot-frame",\n'
            "        type=int,\n"
            "        default=5248," in campaign
            and '"--expected-origin-rng",\n' in campaign
            and "default=0x00C8," in campaign
            and '"--start-frames",\n'
            "        type=int,\n"
            "        default=61," in campaign
        ),
        "fresh_campaign_rejects_rng_mismatch": (
            'int(origin["rng_state"]) != args.expected_origin_rng'
            in campaign
            and '"reason": "gameplay_origin_rng_mismatch"' in campaign
        ),
        "boot_input_uses_exact_frame_stepping": (
            "input_response = set_held_input(m, buttons)" in campaign
            and "response = m.run_frames(requested)" in campaign
            and "if advanced != requested:" in campaign
            and "m.set_input(buttons, requested)" not in campaign
        ),
        "checkpoint_events_come_from_tick_rows": (
            "tick_rows[args.state_mame_tick][\"snes_buttons\"]" in capture
            and (
                "inputs.append(campaign.InputEvent(tick, buttons, row))"
                in capture
            )
            and 'elif raw.get("event") == "input"' not in capture
        ),
    }
    return {
        "checks": required,
        "result": "green" if all(required.values()) else "red",
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--rom", type=Path, default=DEFAULT_ROM)
    parser.add_argument("--snes-dir", type=Path, default=DEFAULT_SNES)
    parser.add_argument("--mame-dir", type=Path, default=DEFAULT_MAME)
    parser.add_argument("--origin-snes", type=Path, default=DEFAULT_ORIGIN_SNES)
    parser.add_argument("--origin-mame", type=Path, default=DEFAULT_ORIGIN_MAME)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument(
        "--allow-forensic-nonresumable-captures",
        action="store_true",
        help=(
            "diagnostic only: permit a legacy/nonresumable SNES capture; "
            "the result is labeled forensic_only, never green evidence"
        ),
    )
    args = parser.parse_args()
    for label, path in (
        ("ROM", args.rom),
        ("SNES capture directory", args.snes_dir),
        ("MAME capture directory", args.mame_dir),
        ("SNES origin work", args.origin_snes),
        ("MAME origin work", args.origin_mame),
        ("campaign source", CAMPAIGN_SOURCE),
        ("checkpoint capture source", CAPTURE_SOURCE),
    ):
        if not path.exists():
            parser.error(f"missing {label}: {path}")
    if args.output.exists():
        parser.error(f"output already exists: {args.output}")

    summary_path = args.snes_dir / "summary.json"
    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    rom_hash = sha256(args.rom)
    capture_resumability = summary.get("state_resumability", {})
    safe_capture_lineage = (
        isinstance(capture_resumability, dict)
        and capture_resumability.get("resumable_checkpoint") is True
        and capture_resumability.get("explicit_override") is False
    )
    if (
        not safe_capture_lineage
        and not args.allow_forensic_nonresumable_captures
    ):
        raise RuntimeError(
            "SNES summary does not prove an authenticated resumable start "
            "state; rerun from a safe checkpoint or explicitly select "
            "--allow-forensic-nonresumable-captures"
        )
    provenance_semantic = (
        summary["rom_sha256"] == rom_hash
        and summary["emulator"].endswith("/Nexen")
        and summary["input_apply_offset"] == 0
        and summary["all_player_references_green"] is True
    )
    provenance_green = provenance_semantic and safe_capture_lineage

    origin_snes = args.origin_snes.read_bytes()
    origin_mame = args.origin_mame.read_bytes()
    origin = {
        name: compare(
            origin_mame[offset : offset + size],
            origin_snes[offset : offset + size],
            offset,
        )
        for name, (offset, size) in (
            ("player_record", REGIONS["player_record"]),
            ("collision_table", REGIONS["collision_table"]),
        )
    }
    origin_green = all(row["equal"] for row in origin.values())

    boundaries: dict[str, Any] = {}
    boundaries_green = True
    for tick in TICKS:
        mame_path = args.mame_dir / f"mame-tick-{tick:05d}.work.bin"
        snes_path = args.snes_dir / f"snes-tick-{tick:05d}.work.bin"
        if not mame_path.is_file() or not snes_path.is_file():
            raise RuntimeError(f"missing tick-{tick} oracle pair")
        mame = mame_path.read_bytes()
        snes = snes_path.read_bytes()
        regions = {
            name: compare(
                mame[offset : offset + size],
                snes[offset : offset + size],
                offset,
            )
            for name, (offset, size) in REGIONS.items()
        }
        green = all(row["equal"] for row in regions.values())
        boundaries_green &= green
        boundaries[str(tick)] = {
            "mame": str(mame_path.resolve()),
            "mame_sha256": sha256(mame_path),
            "snes": str(snes_path.resolve()),
            "snes_sha256": sha256(snes_path),
            "regions": regions,
            "result": "green" if green else "red",
        }

    source = source_regression()
    semantic_green = (
        provenance_semantic
        and origin_green
        and boundaries_green
        and source["result"] == "green"
    )
    result_label = (
        "green"
        if semantic_green and safe_capture_lineage
        else "forensic_only"
        if semantic_green
        else "red"
    )
    result = {
        "scope": (
            "retained exact MAME/Nexen controller-boundary alignment "
            "regression; checkpointed, not fresh-boot proof"
        ),
        "rom": str(args.rom.resolve()),
        "rom_sha256": rom_hash,
        "nexen_summary": str(summary_path.resolve()),
        "nexen_summary_sha256": sha256(summary_path),
        "provenance_result": "green" if provenance_green else "red",
        "provenance_semantic_result": (
            "green" if provenance_semantic else "red"
        ),
        "safe_capture_lineage": safe_capture_lineage,
        "capture_resumability": capture_resumability,
        "allow_forensic_nonresumable_captures": (
            args.allow_forensic_nonresumable_captures
        ),
        "origin_tick": 221,
        "origin_regions": origin,
        "origin_result": "green" if origin_green else "red",
        "first_input_tick": 1054,
        "boundaries": boundaries,
        "boundaries_result": "green" if boundaries_green else "red",
        "source": source,
        "classification_of_prior_extra_hit": (
            "replay_harness_timing"
            if safe_capture_lineage
            else "nonresumable_source_forensic_only_no_causal_claim"
        ),
        "result": result_label,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(result, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(
        json.dumps(
            {
                "boundaries": result["boundaries_result"],
                "origin": result["origin_result"],
                "provenance": result["provenance_result"],
                "source": source["result"],
                "result": result["result"],
                "result_path": str(args.output.resolve()),
            },
            sort_keys=True,
        )
    )
    return 0 if semantic_green else 1


if __name__ == "__main__":
    raise SystemExit(main())
