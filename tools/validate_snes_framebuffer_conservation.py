#!/usr/bin/env python3
"""Require every SNES video frame to be a complete accepted image.

Each candidate must exactly equal either the preceding or succeeding aligned,
accepted MAME image.  Any third image is a temporal renderer-conservation
failure: partial DMA, stale-map publication, tearing, flashing, or breakup.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from PIL import Image, ImageChops

from compare_mame_snes_framebuffers import MAME_CROP, MAME_SIZE
from compare_snes_framebuffer_sequence import mismatch_ranges
from compare_snes_framebuffers import (
    ACTIVE_SIZE,
    PLAYFIELD_BOX,
    changed_pixel_count,
    file_sha256,
    image_sha256,
    normalize,
)
from gameplay_acceptance_contract import (
    gate,
    load_json,
    valid_sha256,
    validate_gate,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    return parser.parse_args()


def resolve(base: Path, raw: Any) -> Path:
    path = Path(str(raw))
    return path if path.is_absolute() else base / path


def changed(first: Image.Image, second: Image.Image) -> tuple[int, int]:
    difference = ImageChops.difference(first, second)
    return (
        changed_pixel_count(difference),
        changed_pixel_count(difference.crop(PLAYFIELD_BOX)),
    )


def main() -> int:
    args = parse_args()
    manifest_path = args.manifest.resolve()
    manifest = load_json(manifest_path)
    rom_sha256 = manifest.get("rom_sha256")
    coverage = manifest.get("coverage")
    reasons: list[str] = []
    if not valid_sha256(rom_sha256):
        reasons.append("rom_sha256_invalid")
    if not isinstance(coverage, dict):
        coverage = {}
        reasons.append("coverage_missing")
    for field in (
        "game_tick_start",
        "game_tick_end",
        "snes_video_frame_start",
        "snes_video_frame_end",
    ):
        if not isinstance(coverage.get(field), int):
            reasons.append(f"{field}_invalid")
    if coverage.get("complete") is not True:
        reasons.append("coverage_not_complete")
    frames = manifest.get("frames")
    if not isinstance(frames, list) or not frames:
        frames = []
        reasons.append("frames_missing")
    for index, row in enumerate(frames):
        if not isinstance(row, dict):
            reasons.append(f"frame_{index}_not_an_object")
            continue
        for field in (
            "snes_video_frame",
            "previous_accepted_tick",
            "next_accepted_tick",
        ):
            if not isinstance(row.get(field), int):
                reasons.append(f"frame_{index}_{field}_invalid")
        previous_tick = row.get("previous_accepted_tick")
        next_tick = row.get("next_accepted_tick")
        if (
            isinstance(previous_tick, int)
            and isinstance(next_tick, int)
            and previous_tick > next_tick
        ):
            reasons.append(f"frame_{index}_accepted_tick_order_invalid")
        for field in ("candidate",):
            if field not in row:
                reasons.append(f"frame_{index}_{field}_missing")
            elif not resolve(manifest_path.parent, row[field]).is_file():
                reasons.append(f"frame_{index}_{field}_file_missing")
    aligned_report_path: Path | None = None
    aligned_frames: dict[int, dict[str, Any]] = {}
    raw_aligned_report = manifest.get("aligned_pixel_report")
    if raw_aligned_report is None:
        reasons.append("aligned_pixel_report_missing")
    else:
        aligned_report_path = resolve(
            manifest_path.parent, raw_aligned_report
        ).resolve()
        if not aligned_report_path.is_file():
            reasons.append("aligned_pixel_report_file_missing")
        else:
            try:
                aligned_report = load_json(aligned_report_path)
                reasons.extend(
                    f"aligned_pixel_report:{reason}"
                    for reason in validate_gate(
                        aligned_report.get("acceptance_gate"),
                        "aligned_pixel_oracle",
                        rom_sha256,
                        coverage,
                    )
                )
                if aligned_report.get("acceptance_gate", {}).get("status") != "green":
                    reasons.append("aligned_pixel_report_not_green")
                for row in aligned_report.get("frames", []):
                    if isinstance(row, dict) and isinstance(row.get("game_tick"), int):
                        aligned_frames[int(row["game_tick"])] = row
            except (OSError, ValueError, json.JSONDecodeError) as error:
                reasons.append(
                    f"aligned_pixel_report_unreadable:{type(error).__name__}"
                )
    for index, row in enumerate(frames):
        if not isinstance(row, dict):
            continue
        for field in ("previous_accepted_tick", "next_accepted_tick"):
            tick = row.get(field)
            if isinstance(tick, int) and tick not in aligned_frames:
                reasons.append(f"frame_{index}_{field}_not_in_aligned_report")
    video_frames = [
        row.get("snes_video_frame") for row in frames if isinstance(row, dict)
    ]
    start = coverage.get("snes_video_frame_start")
    end = coverage.get("snes_video_frame_end")
    if isinstance(start, int) and isinstance(end, int):
        if start > end:
            reasons.append("video_frame_range_invalid")
        elif video_frames != list(range(start, end + 1)):
            reasons.append("not_every_snes_video_frame_is_covered_exactly_once")

    output = args.output.resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    diff_dir = output.parent / f"{output.stem}-diffs"
    rows: list[dict[str, Any]] = []
    if not reasons:
        for index, item in enumerate(frames):
            candidate, candidate_meta = normalize(
                resolve(manifest_path.parent, item["candidate"])
            )
            accepted_images: list[tuple[Image.Image, dict[str, Any]]] = []
            for accepted_tick in (
                int(item["previous_accepted_tick"]),
                int(item["next_accepted_tick"]),
            ):
                accepted_row = aligned_frames[accepted_tick]
                mame_path = Path(accepted_row["mame"]["path"])
                mame_source = Image.open(mame_path).convert("RGB")
                if mame_source.size != MAME_SIZE:
                    raise SystemExit(
                        f"accepted tick {accepted_tick}: expected MAME {MAME_SIZE}, got {mame_source.size}"
                    )
                accepted = mame_source.crop(MAME_CROP)
                if image_sha256(accepted) != accepted_row["mame"][
                    "registered_rgb_sha256"
                ]:
                    raise SystemExit(
                        f"accepted tick {accepted_tick}: registered MAME hash changed"
                    )
                accepted_images.append(
                    (
                        accepted,
                        {
                            "game_tick": accepted_tick,
                            "path": str(mame_path.resolve()),
                            "file_sha256": file_sha256(mame_path),
                            "registered_rgb_sha256": image_sha256(accepted),
                        },
                    )
                )
            (previous, previous_meta), (following, following_meta) = accepted_images
            previous_changed, previous_playfield = changed(candidate, previous)
            next_changed, next_playfield = changed(candidate, following)
            accepted_as = (
                "previous"
                if previous_changed == 0
                else ("next" if next_changed == 0 else None)
            )
            result = "green" if accepted_as is not None else "red"
            best_reference = previous if previous_changed <= next_changed else following
            best_difference = ImageChops.difference(candidate, best_reference)
            row: dict[str, Any] = {
                "index": index,
                "label": int(item["snes_video_frame"]),
                "snes_video_frame": int(item["snes_video_frame"]),
                "result": result,
                "accepted_as": accepted_as,
                "previous_accepted_tick": int(item["previous_accepted_tick"]),
                "next_accepted_tick": int(item["next_accepted_tick"]),
                "changed_from_previous": previous_changed,
                "playfield_changed_from_previous": previous_playfield,
                "changed_from_next": next_changed,
                "playfield_changed_from_next": next_playfield,
                "difference_bbox_from_closest": (
                    list(best_difference.getbbox())
                    if best_difference.getbbox()
                    else None
                ),
                "candidate": candidate_meta,
                "previous_accepted": previous_meta,
                "next_accepted": following_meta,
            }
            if result == "red":
                diff_dir.mkdir(parents=True, exist_ok=True)
                mask = best_difference.convert("L").point(
                    lambda value: 255 if value else 0
                )
                diff = Image.new("RGB", ACTIVE_SIZE, (0, 0, 0))
                diff.paste((255, 0, 0), mask=mask)
                diff_path = diff_dir / f"frame-{item['snes_video_frame']:06d}.png"
                diff.save(diff_path)
                row["difference_mask"] = str(diff_path)
            rows.append(row)

    mismatches = [row for row in rows if row["result"] == "red"]
    status = "unknown" if reasons else ("red" if mismatches else "green")
    first = mismatches[0] if mismatches else None
    acceptance_gate = gate(
        "temporal_conservation",
        status,
        rom_sha256 if valid_sha256(rom_sha256) else None,
        coverage or None,
        authority="every_snes_video_frame" if status != "unknown" else "none",
        reason=";".join(sorted(set(reasons))) if reasons else None,
    )
    report = {
        "schema": 1,
        "scope": (
            "every intervening SNES video frame must exactly equal the preceding "
            "or succeeding aligned accepted MAME image"
        ),
        "manifest": str(manifest_path),
        "aligned_pixel_report": (
            str(aligned_report_path) if aligned_report_path is not None else None
        ),
        "rom_sha256": rom_sha256,
        "coverage": coverage,
        "frames_compared": len(rows),
        "mismatch_frames": len(mismatches),
        "first_divergence": (
            {
                "snes_video_frame": first["snes_video_frame"],
                "changed_from_previous": first["changed_from_previous"],
                "changed_from_next": first["changed_from_next"],
                "difference_bbox_from_closest": first[
                    "difference_bbox_from_closest"
                ],
            }
            if first is not None
            else None
        ),
        "mismatch_ranges": mismatch_ranges(rows),
        "coverage_errors": sorted(set(reasons)),
        "frames": rows,
        "acceptance_gate": acceptance_gate,
    }
    output.write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(
        json.dumps(
            {
                "status": status,
                "frames_compared": len(rows),
                "first_divergence": report["first_divergence"],
                "mismatch_ranges": report["mismatch_ranges"],
                "coverage_errors": report["coverage_errors"],
                "report": str(output),
            },
            sort_keys=True,
        )
    )
    return {"green": 0, "red": 1, "unknown": 2}[status]


if __name__ == "__main__":
    raise SystemExit(main())
