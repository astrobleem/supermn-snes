#!/usr/bin/env python3
"""Normalize an exact fresh-movie suffix capture into the framebuffer gate schema.

This is the evidence-preserving resume path when organic recording completed but
the original validator failed before retaining post-Start frames.  It never
turns a checkpoint into fresh evidence: the source must be a no-state, no-poke,
step-one replay of a StartWithoutSaveData movie from its declared frame range.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from gameplay_acceptance_contract import unknown_diagnostic_gate
from validate_fresh_poststart_framebuffers import (
    evaluate_rows,
    image_metrics,
    make_contact_sheet,
    movie_input_contract,
    sha256,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--visual-grace-frames", type=int, default=100)
    parser.add_argument("--contact-step", type=int, default=25)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.visual_grace_frames < 0 or args.contact_step <= 0:
        raise SystemExit("invalid grace/contact interval")
    source_path = args.input.resolve()
    target = args.output.resolve()
    if not source_path.is_file():
        raise FileNotFoundError(source_path)
    if target.exists():
        raise SystemExit(f"refusing existing output: {target}")

    source = json.loads(source_path.read_text())
    provenance = source.get("provenance", {})
    frame_range = provenance.get("frame_range")
    if (
        provenance.get("state") is not None
        or provenance.get("runtime_memory_pokes")
        or provenance.get("capture_step") != 1
        or not isinstance(frame_range, list)
        or len(frame_range) != 2
    ):
        raise RuntimeError("source is not an unmodified step-one fresh-movie replay")

    rom = Path(provenance["rom"]).resolve()
    movie = Path(provenance["movie"]).resolve()
    for path, expected in (
        (rom, provenance["rom_sha256"]),
        (movie, provenance["movie_sha256"]),
    ):
        if not path.is_file() or sha256(path) != expected:
            raise RuntimeError(f"source artifact hash mismatch: {path}")
    movie_contract = movie_input_contract(movie)
    if not movie_contract["green"] or movie_contract["start_rows"] <= 0:
        raise RuntimeError(f"movie input contract failed: {movie_contract}")

    originals = source.get("captures")
    if not isinstance(originals, list) or not originals:
        raise RuntimeError("source has no retained captures")
    expected_frames = list(range(int(frame_range[0]), int(frame_range[1]) + 1))
    observed_frames = [row.get("frame") for row in originals]
    if observed_frames != expected_frames:
        raise RuntimeError("source framebuffer coverage is not exact and consecutive")

    rows: list[dict[str, Any]] = []
    for relative, original in enumerate(originals):
        row = dict(original)
        screenshot = Path(row["screenshot"]["path"]).resolve()
        if not screenshot.is_file() or sha256(screenshot) != row["screenshot"]["sha256"]:
            raise RuntimeError(f"framebuffer authentication failed: {screenshot}")
        row["relative_frame"] = relative
        row["image_metrics"] = image_metrics(screenshot)
        rows.append(row)

    failures = evaluate_rows(rows, args.visual_grace_frames)
    uninitialized_queue = [
        row["relative_frame"]
        for row in rows
        if row.get("obj_tile_queue_valid") is not True
    ]
    if uninitialized_queue:
        failures.append(
            {
                "relative_frame": uninitialized_queue[0],
                "kind": "obj_queue_not_initialized",
                "count": len(uninitialized_queue),
            }
        )

    selected = [
        Path(row["screenshot"]["path"])
        for row in rows
        if row["relative_frame"] % args.contact_step == 0
        or row["relative_frame"] == rows[-1]["relative_frame"]
    ]
    contact_sheet = make_contact_sheet(
        selected, target.parent / "contact-sheet-poststart.png"
    )
    coverage = {
        "complete": True,
        "fresh_video_frame_start": 0,
        "fresh_video_frame_end": movie_contract["input_rows"],
        "poststart_relative_start": 0,
        "poststart_relative_end": rows[-1]["relative_frame"],
        "poststart_video_frame_start": rows[0]["frame"],
        "poststart_video_frame_end": rows[-1]["frame"],
    }
    acceptance_gate = unknown_diagnostic_gate(
        "fresh_poststart_framebuffers_resumed_replay",
        (
            "An authenticated exact fresh-movie suffix can prove its retained "
            "post-Start window, not aligned MAME pixels or full-game acceptance."
        ),
    )
    acceptance_gate["rom_sha256"] = provenance["rom_sha256"]
    acceptance_gate["coverage"] = coverage
    report = {
        "schema": 1,
        "scope": (
            "authenticated StartWithoutSaveData movie replay; exact step-one "
            "post-Start suffix normalized after pre-capture recorder failure"
        ),
        "source_results": str(source_path),
        "source_results_sha256": sha256(source_path),
        "rom": str(rom),
        "rom_sha256": provenance["rom_sha256"],
        "emulator": provenance.get("mesen"),
        "emulator_sha256": provenance.get("mesen_sha256"),
        "movie": str(movie),
        "movie_sha256": provenance["movie_sha256"],
        "movie_start": "StartWithoutSaveData",
        "movie_input_contract": movie_contract,
        "runtime_memory_writes": [],
        "obj_temporal_capture": True,
        "coverage": coverage,
        "visual_grace_frames": args.visual_grace_frames,
        "captures": rows,
        "contact_sheet": contact_sheet,
        "visual_regression_result": "red" if failures else "clear",
        "first_failure": failures[0] if failures else None,
        "failures": failures,
        "manual_review_required": True,
        "acceptance_gate": acceptance_gate,
        "not_checked": [
            "aligned_full_composite_mame_pixels",
            "intervening_snes_frame_conservation_against_mame",
            "fence_collision_break_and_passage",
            "later_stages",
        ],
        "promotion": {
            "eligible": False,
            "status": "blocked",
            "authority": "none",
            "reason": "bounded fresh suffix is not the complete promotion manifest",
        },
    }
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    print(
        json.dumps(
            {
                "visual_regression_result": report["visual_regression_result"],
                "frames": len(rows),
                "first_failure": report["first_failure"],
                "report": str(target),
                "contact_sheet": contact_sheet["path"],
                "acceptance_status": "unknown",
            },
            sort_keys=True,
        )
    )
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
