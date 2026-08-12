#!/usr/bin/env python3
"""Detect repeated-tile framebuffer collapse across a captured sequence."""

from __future__ import annotations

import argparse
import json
import statistics
from pathlib import Path
from typing import Any

from PIL import ImageChops

from compare_snes_framebuffers import (
    ACTIVE_SIZE,
    PLAYFIELD_BOX,
    changed_pixel_count,
    normalize,
    repetition_metrics,
)
from gameplay_acceptance_contract import unknown_diagnostic_gate


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--frames", type=Path, required=True)
    parser.add_argument("--glob", default="frame-*.png")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--dominant-tile-ratio", type=float, default=0.5)
    parser.add_argument("--baseline-frames", type=int, default=32)
    parser.add_argument(
        "--skip-frames",
        type=int,
        default=0,
        help="exclude this many leading serialized/pre-vblank images",
    )
    return parser.parse_args()


def ranges(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    start: dict[str, Any] | None = None
    previous: dict[str, Any] | None = None
    for row in rows:
        if row["repeated_tile_collapse"]:
            if start is None:
                start = row
            previous = row
        elif start is not None and previous is not None:
            result.append(
                {
                    "start_index": start["index"],
                    "end_index": previous["index"],
                    "start_file": start["file"],
                    "end_file": previous["file"],
                }
            )
            start = previous = None
    if start is not None and previous is not None:
        result.append(
            {
                "start_index": start["index"],
                "end_index": previous["index"],
                "start_file": start["file"],
                "end_file": previous["file"],
            }
        )
    return result


def main() -> int:
    args = parse_args()
    if not 0 < args.dominant_tile_ratio <= 1:
        raise SystemExit("--dominant-tile-ratio must be in (0, 1]")
    if args.baseline_frames <= 0:
        raise SystemExit("--baseline-frames must be positive")
    if args.skip_frames < 0:
        raise SystemExit("--skip-frames must be nonnegative")
    files = sorted(args.frames.glob(args.glob))
    if not files:
        raise SystemExit("no input framebuffers matched")
    if args.skip_frames >= len(files):
        raise SystemExit("--skip-frames excludes every input framebuffer")
    files = files[args.skip_frames:]

    rows: list[dict[str, Any]] = []
    previous = None
    for index, path in enumerate(files):
        image, meta = normalize(path)
        repetition = repetition_metrics(image)
        changed = 0
        playfield_changed = 0
        if previous is not None:
            difference = ImageChops.difference(previous, image)
            changed = changed_pixel_count(difference)
            playfield_changed = changed_pixel_count(
                difference.crop(PLAYFIELD_BOX)
            )
        rows.append(
            {
                "index": index,
                "file": path.name,
                "active_rgb_sha256": meta["active_rgb_sha256"],
                "dominant_tile_ratio": repetition["dominant_tile_ratio"],
                "dominant_tile_count": repetition["dominant_tile_count"],
                "unique_tiles": repetition["unique_tiles"],
                "changed_pixels_from_previous": changed,
                "playfield_changed_pixels_from_previous": playfield_changed,
                "repeated_tile_collapse": (
                    repetition["dominant_tile_ratio"]
                    >= args.dominant_tile_ratio
                ),
            }
        )
        previous = image

    anomaly_ranges = ranges(rows)
    first = next(
        (row for row in rows if row["repeated_tile_collapse"]), None
    )
    baseline = rows[: min(args.baseline_frames, len(rows))]
    report = {
        "schema": 1,
        "scope": (
            "temporal SNES framebuffer repeated-tile-collapse detection; "
            "visual evidence only"
        ),
        "frames_directory": str(args.frames.resolve()),
        "frame_glob": args.glob,
        "leading_frames_excluded": args.skip_frames,
        "frames_compared": len(rows),
        "diagnostic_result": "anomaly-detected" if first is not None else "clear",
        "threshold": {
            "dominant_tile_ratio": args.dominant_tile_ratio,
            "baseline_frames": len(baseline),
            "baseline_median_dominant_tile_ratio": statistics.median(
                row["dominant_tile_ratio"] for row in baseline
            ),
        },
        "first_detected_anomaly": (
            {
                "index": first["index"],
                "file": first["file"],
                "dominant_tile_ratio": first["dominant_tile_ratio"],
                "unique_tiles": first["unique_tiles"],
                "changed_pixels_from_previous": first[
                    "changed_pixels_from_previous"
                ],
                "playfield_changed_pixels_from_previous": first[
                    "playfield_changed_pixels_from_previous"
                ],
            }
            if first is not None
            else None
        ),
        "detected_anomaly_ranges": anomaly_ranges,
        "acceptance_gate": unknown_diagnostic_gate(
            "repetition_heuristic",
            (
                "A dominant-tile heuristic can detect one symptom but cannot "
                "prove alignment, correctness, motion, or renderer conservation."
            ),
        ),
        "frames": rows,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(
        json.dumps(
            {
                "diagnostic_result": report["diagnostic_result"],
                "frames_compared": report["frames_compared"],
                "first_detected_anomaly": report["first_detected_anomaly"],
                "detected_anomaly_ranges": anomaly_ranges,
                "acceptance_status": "unknown",
                "report": str(args.output.resolve()),
            },
            sort_keys=True,
        )
    )
    return 1 if first is not None else 0


if __name__ == "__main__":
    raise SystemExit(main())
