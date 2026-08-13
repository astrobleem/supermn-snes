#!/usr/bin/env python3
"""Offline gate for *presented* horizontal motion in consecutive captures.

State/pixel correctness does not prove temporal continuity.  Every consecutive
video-frame transition is registered here, including frames on which the 30 Hz
game camera has not produced a new target.  This prevents a 60 Hz presentation
that alternates ``hold, jump`` from being mislabeled smooth and also rejects a
tilemap publication that cannot be explained by the camera translation.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from collections import Counter
from pathlib import Path
from typing import Any

from PIL import Image, ImageChops


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--results", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--warmup-frames", type=int, default=2)
    parser.add_argument("--minimum-source-steps", type=int, default=20)
    parser.add_argument("--crop-left", type=int, default=32)
    parser.add_argument("--crop-top", type=int, default=24)
    parser.add_argument("--crop-right", type=int, default=224)
    parser.add_argument("--crop-bottom", type=int, default=96)
    parser.add_argument("--max-registration-shift", type=int, default=18)
    parser.add_argument(
        "--max-presented-step",
        type=int,
        default=2,
        help="largest acceptable motion on one 60 Hz video transition",
    )
    parser.add_argument(
        "--max-background-mismatch",
        type=float,
        default=0.08,
        help="maximum residual changed-pixel ratio after translation",
    )
    return parser.parse_args()


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def signed8_delta(before: int, after: int) -> int:
    return ((after - before + 128) & 0xFF) - 128


def signed32_delta(before: int, after: int) -> int:
    return ((after - before + 16) & 0x1F) - 16


def signed1024_delta(before: int, after: int) -> int:
    return ((after - before + 512) & 0x3FF) - 512


def screenshot_path(source_path: Path, recorded: str) -> Path:
    """Resolve a capture after evidence-preserving directory archival.

    Capture manifests retain their original absolute path.  When the whole
    capture directory has been moved, its authenticated basename beside the
    moved results file is an unambiguous fallback.
    """

    path = Path(recorded).resolve()
    if path.is_file():
        return path
    sibling = source_path.parent / path.name
    return sibling.resolve()


def best_horizontal_shift(
    before: Image.Image,
    after: Image.Image,
    limit: int,
) -> tuple[int, float]:
    width, height = before.size
    candidates: list[tuple[float, int]] = []
    for shift in range(-limit, limit + 1):
        if shift < 0:
            left = before.crop((0, 0, width + shift, height))
            right = after.crop((-shift, 0, width, height))
        elif shift > 0:
            left = before.crop((shift, 0, width, height))
            right = after.crop((0, 0, width - shift, height))
        else:
            left = before
            right = after
        histogram = ImageChops.difference(left, right).convert("L").histogram()
        changed = sum(histogram[1:])
        candidates.append((changed / (left.width * left.height), shift))
    mismatch, shift = min(candidates)
    return shift, mismatch


def main() -> int:
    args = parse_args()
    source_path = args.results.resolve()
    source = json.loads(source_path.read_text())
    captures: list[dict[str, Any]] = source["captures"]
    if len(captures) < 2:
        raise SystemExit("capture has fewer than two frames")

    failures: list[str] = []
    frame_deltas = [
        int(after["frame"]) - int(before["frame"])
        for before, after in zip(captures, captures[1:])
    ]
    if any(delta != 1 for delta in frame_deltas):
        failures.append("capture is not consecutive actual video frames")

    authenticated = 0
    images: list[Path] = []
    for row in captures:
        screenshot = row["screenshot"]
        path = screenshot_path(source_path, screenshot["path"])
        if not path.is_file() or sha256(path) != screenshot["sha256"]:
            failures.append(f"framebuffer authentication failed: {path}")
            break
        images.append(path)
        authenticated += 1

    source_steps: list[tuple[int, int]] = []
    ppu_steps: list[tuple[int, int]] = []
    # Current renderer builds explicitly publish the common modulo-32 camera
    # phase in latest_scrollx.  A raw X1 source column can jump by 64 pixels
    # when it crosses the hardware layout gap; treating that column as camera
    # truth recreates the very false discontinuity this gate must distinguish.
    # Retain the raw-column fallback for authenticated historical captures.
    source_key = (
        "latest_scrollx"
        if all("latest_scrollx" in row for row in captures)
        else (
            "live_scrollx_column4"
            if all("live_scrollx_column4" in row for row in captures)
            else "live_scrollx_column0"
        )
    )
    for index in range(max(1, args.warmup_frames + 1), len(captures)):
        before = captures[index - 1]
        after = captures[index]
        if int(after[source_key]) != int(before[source_key]):
            source_steps.append(
                (
                    index,
                    signed8_delta(
                        int(before[source_key]),
                        int(after[source_key]),
                    ),
                )
            )
        if int(after["bg1_hscroll"]) != int(before["bg1_hscroll"]):
            ppu_steps.append(
                (
                    index,
                    signed32_delta(
                        int(before["bg1_hscroll"]),
                        int(after["bg1_hscroll"]),
                    ),
                )
            )

    source_histogram = Counter(delta for _, delta in source_steps)
    dominant_source_step = (
        source_histogram.most_common(1)[0][0] if source_histogram else None
    )
    expected_visual_shift = (
        -dominant_source_step if dominant_source_step is not None else None
    )

    if len(source_steps) < args.minimum_source_steps:
        failures.append(
            f"only {len(source_steps)} source-scroll steps; "
            f"need {args.minimum_source_steps}"
        )
    if source_steps and source_histogram[dominant_source_step] != len(source_steps):
        failures.append("source-scroll step is not stable in the measured window")
    registrations: list[dict[str, Any]] = []
    if authenticated == len(captures) and expected_visual_shift is not None:
        for index in range(max(1, args.warmup_frames + 1), len(captures)):
            before = Image.open(images[index - 1]).convert("RGB").crop(
                (
                    args.crop_left,
                    args.crop_top,
                    args.crop_right,
                    args.crop_bottom,
                )
            )
            after = Image.open(images[index]).convert("RGB").crop(
                (
                    args.crop_left,
                    args.crop_top,
                    args.crop_right,
                    args.crop_bottom,
                )
            )
            shift, mismatch = best_horizontal_shift(
                before, after, args.max_registration_shift
            )
            registrations.append(
                {
                    "capture_index": index,
                    "frame": captures[index]["frame"],
                    "best_shift": shift,
                    "mismatch_ratio": mismatch,
                }
            )
    first_motion = source_steps[0][0] if source_steps else len(captures)
    last_motion = source_steps[-1][0] if source_steps else -1
    direction = 1 if expected_visual_shift and expected_visual_shift > 0 else -1
    # A 64x32 tilemap can rotate its physical 32-pixel columns while preserving
    # the same world image.  HOFS must rebase at that exact PPU publication,
    # so its raw register delta is not itself visible motion.  The authenticated
    # framebuffer registration below remains authoritative for that transition.
    map_change_indices = {
        index
        for index in range(1, len(captures))
        if captures[index - 1].get("displayed_bg_map_sha256") is not None
        and captures[index].get("displayed_bg_map_sha256") is not None
        and captures[index - 1]["displayed_bg_map_sha256"]
        != captures[index]["displayed_bg_map_sha256"]
    }
    motion_ppu_steps = [
        (index, delta)
        for index, delta in ppu_steps
        if first_motion <= index <= last_motion
    ]
    motion_ppu_indices = {index for index, _delta in motion_ppu_steps}
    held_ppu_transitions = [
        index
        for index in range(first_motion, last_motion + 1)
        if index not in motion_ppu_indices and index not in map_change_indices
    ]
    wrong_ppu_steps = [
        {"capture_index": index, "delta_signed32": delta}
        for index, delta in motion_ppu_steps
        if index not in map_change_indices
        and (delta * direction <= 0 or abs(delta) > args.max_presented_step)
    ]
    if held_ppu_transitions:
        failures.append(
            f"PPU held on {len(held_ppu_transitions)} video transitions while "
            "the camera was moving"
        )
    if wrong_ppu_steps:
        failures.append(
            f"{len(wrong_ppu_steps)} PPU transitions exceeded the per-video "
            "step limit or reversed direction"
        )
    expected_motion_total = sum(-delta for _, delta in source_steps)
    observed_ppu_total = sum(delta for _, delta in motion_ppu_steps)

    motion_registrations = [
        row
        for row in registrations
        if first_motion <= row["capture_index"] <= last_motion
    ]
    registration_by_index = {
        int(row["capture_index"]): row for row in motion_registrations
    }
    coordinate_rebases = [
        {
            "capture_index": index,
            "frame": captures[index]["frame"],
            "ppu_delta_signed32": next(
                (delta for step_index, delta in motion_ppu_steps if step_index == index),
                0,
            ),
            "ppu_delta_signed1024": signed1024_delta(
                int(captures[index - 1]["bg1_hscroll"]),
                int(captures[index]["bg1_hscroll"]),
            ),
            "registration": registration_by_index.get(index),
        }
        for index in sorted(map_change_indices)
        if first_motion <= index <= last_motion
    ]
    held_presentations = [
        row for row in motion_registrations if row["best_shift"] == 0
    ]
    oversized_presentations = [
        row
        for row in motion_registrations
        if abs(row["best_shift"]) > args.max_presented_step
    ]
    reversed_presentations = [
        row
        for row in motion_registrations
        if row["best_shift"] * direction < 0
    ]
    discontinuities = [
        row
        for row in motion_registrations
        if row["mismatch_ratio"] > args.max_background_mismatch
    ]
    wrong_registrations = sorted(
        {
            row["capture_index"]: row
            for row in (
                held_presentations
                + oversized_presentations
                + reversed_presentations
                + discontinuities
            )
        }.values(),
        key=lambda row: row["capture_index"],
    )
    observed_visual_total = sum(
        int(row["best_shift"]) for row in motion_registrations
    )
    if abs(expected_motion_total - observed_visual_total) > args.max_presented_step:
        failures.append(
            f"framebuffers presented {observed_visual_total:+d} pixels for "
            f"{expected_motion_total:+d} pixels of source motion"
        )
    if held_presentations:
        failures.append(
            f"{len(held_presentations)} held video frames occurred while the "
            "camera was moving"
        )
    if oversized_presentations:
        failures.append(
            f"{len(oversized_presentations)} presented steps exceeded "
            f"{args.max_presented_step} pixels per video frame"
        )
    if reversed_presentations:
        failures.append(
            f"{len(reversed_presentations)} presented steps reversed camera direction"
        )
    if discontinuities:
        failures.append(
            f"{len(discontinuities)} background transitions exceeded the "
            f"{args.max_background_mismatch:.3f} post-registration mismatch limit"
        )

    report = {
        "schema": 1,
        "scope": (
            "offline temporal-scroll gate over authenticated consecutive actual "
            "video frames; not fresh-boot, gameplay, performance, or MAME-pixel acceptance"
        ),
        "source_results": str(source_path),
        "source_results_sha256": sha256(source_path),
        "capture_count": len(captures),
        "authenticated_framebuffers": authenticated,
        "frame_range": [captures[0]["frame"], captures[-1]["frame"]],
        "warmup_frames": args.warmup_frames,
        "source_scroll_key": source_key,
        "source_step_count": len(source_steps),
        "source_step_histogram": dict(sorted(source_histogram.items())),
        "dominant_source_step": dominant_source_step,
        "ppu_step_count": len(ppu_steps),
        "expected_ppu_direction": direction,
        "expected_motion_total": expected_motion_total,
        "observed_ppu_motion_total": observed_ppu_total,
        "observed_visual_motion_total": observed_visual_total,
        "coordinate_rebases": coordinate_rebases,
        "held_ppu_transitions": held_ppu_transitions,
        "wrong_ppu_steps": wrong_ppu_steps,
        "expected_visual_shift": expected_visual_shift,
        "registration_count": len(registrations),
        "registration_shift_histogram": dict(
            sorted(Counter(row["best_shift"] for row in registrations).items())
        ),
        "motion_transition_count": len(motion_registrations),
        "held_presentations": held_presentations,
        "oversized_presentations": oversized_presentations,
        "reversed_presentations": reversed_presentations,
        "background_discontinuities": discontinuities,
        "max_presented_step": args.max_presented_step,
        "max_background_mismatch": args.max_background_mismatch,
        "wrong_registrations": wrong_registrations,
        "failures": failures,
        "result": "green" if not failures else "red",
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    print(
        json.dumps(
            {
                "result": report["result"],
                "source_steps": len(source_steps),
                "ppu_steps": len(ppu_steps),
                "registration_shift_histogram": report[
                    "registration_shift_histogram"
                ],
                "failures": failures,
                "report": str(args.output.resolve()),
            },
            sort_keys=True,
        )
    )
    return 0 if not failures else 1


if __name__ == "__main__":
    raise SystemExit(main())
