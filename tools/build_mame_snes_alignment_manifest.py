#!/usr/bin/env python3
"""Build a fail-closed exact-frame manifest from retained MAME/SNES captures."""

from __future__ import annotations

import argparse
import json
from pathlib import Path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--mame-summary", type=Path, required=True)
    parser.add_argument("--snes-results", type=Path, required=True)
    parser.add_argument("--rom-sha256", required=True)
    parser.add_argument("--tick-offset", type=int, required=True)
    parser.add_argument("--mame-tick-min", type=int)
    parser.add_argument("--mame-tick-max", type=int)
    parser.add_argument(
        "--snes-alignment-field",
        choices=("tick", "obj_published_sequence"),
        default="tick",
        help=(
            "SNES capture field paired to MAME tick-offset. Use the published "
            "OAM sequence for presentation pixels; logical-state comparisons use tick."
        ),
    )
    parser.add_argument(
        "--snes-frame-selector",
        choices=("first", "last"),
        default="first",
        help="select the first or last retained video frame carrying each SNES tick",
    )
    parser.add_argument("--output", type=Path, required=True)
    return parser.parse_args()


def load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def main() -> int:
    args = parse_args()
    mame = load(args.mame_summary.resolve())
    snes = load(args.snes_results.resolve())
    reasons: list[str] = []
    if mame.get("result") != "green":
        reasons.append("mame_capture_not_green")
    snes_provenance = snes.get("provenance", {})
    snes_rom_sha256 = snes_provenance.get("rom_sha256") or snes.get(
        "rom_sha256"
    )
    if snes_rom_sha256 != args.rom_sha256:
        reasons.append("snes_rom_hash_mismatch")

    snes_by_tick: dict[int, dict] = {}
    for row in snes.get("captures", []):
        tick = row.get(args.snes_alignment_field)
        if not isinstance(tick, int):
            continue
        if args.snes_frame_selector == "first" and tick in snes_by_tick:
            continue
        screenshot = row.get("screenshot", {}).get("path")
        if screenshot and Path(screenshot).is_file():
            snes_by_tick[tick] = row

    frames: list[dict] = []
    for capture in mame.get("captures", []):
        mame_tick = capture.get("tick")
        if (
            isinstance(mame_tick, int)
            and args.mame_tick_min is not None
            and mame_tick < args.mame_tick_min
        ):
            continue
        if (
            isinstance(mame_tick, int)
            and args.mame_tick_max is not None
            and mame_tick > args.mame_tick_max
        ):
            continue
        snes_tick = mame_tick - args.tick_offset if isinstance(mame_tick, int) else None
        row = snes_by_tick.get(snes_tick)
        snapshot = capture.get("snapshot", {}).get("path")
        if row is None or not snapshot or not Path(snapshot).is_file():
            reasons.append(f"missing_pair_for_mame_tick_{mame_tick}")
            continue
        frames.append(
            {
                "game_tick": mame_tick,
                "mame": str(Path(snapshot).resolve()),
                "snes": str(Path(row["screenshot"]["path"]).resolve()),
                "alignment": {
                    "snes_alignment_field": args.snes_alignment_field,
                    "snes_alignment_value": snes_tick,
                    "snes_tick": row.get("tick"),
                    "tick_offset": args.tick_offset,
                    "snes_video_frame": row.get("frame"),
                    "obj_base_sequence": row.get("obj_base_sequence"),
                },
            }
        )

    ticks = [row["game_tick"] for row in frames]
    if not ticks or ticks != list(range(ticks[0], ticks[-1] + 1)):
        reasons.append("paired_ticks_not_contiguous")
    coverage = {
        "game_tick_start": ticks[0] if ticks else None,
        "game_tick_end": ticks[-1] if ticks else None,
        "complete": not reasons,
    }
    manifest = {
        "schema": 1,
        "oracle": "MAME 0.287",
        "rom_sha256": args.rom_sha256,
        "coverage": coverage,
        "alignment": {
            "rule": (
                "MAME tick = SNES tick + Start-edge tick offset; "
                f"{args.snes_frame_selector} retained SNES video frame carrying "
                f"that {args.snes_alignment_field} value"
            ),
            "tick_offset": args.tick_offset,
            "snes_alignment_field": args.snes_alignment_field,
            "snes_frame_selector": args.snes_frame_selector,
            "authority": "bounded entrance presentation diagnostic",
        },
        "provenance": {
            "mame_executable_sha256": mame.get("mame_sha256"),
            "mame_timeline_sha256": mame.get("timeline_sha256"),
            "snes_emulator_sha256": snes_provenance.get(
                "mesen_2_1_1_binary_sha256"
            ) or snes.get("emulator_sha256"),
        },
        "coverage_errors": sorted(set(reasons)),
        "frames": frames,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"frames": len(frames), "coverage": coverage, "errors": manifest["coverage_errors"]}))
    return 0 if not reasons else 2


if __name__ == "__main__":
    raise SystemExit(main())
