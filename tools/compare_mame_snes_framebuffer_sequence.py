#!/usr/bin/env python3
"""Compare every game tick against its exact aligned MAME framebuffer."""

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
    SCENE_BOX,
    changed_pixel_count,
    file_sha256,
    image_sha256,
    normalize,
)
from gameplay_acceptance_contract import gate, load_json, valid_sha256


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    return parser.parse_args()


def resolve(base: Path, raw: Any) -> Path:
    path = Path(str(raw))
    return path if path.is_absolute() else base / path


def main() -> int:
    args = parse_args()
    manifest_path = args.manifest.resolve()
    manifest = load_json(manifest_path)
    rom_sha256 = manifest.get("rom_sha256")
    coverage = manifest.get("coverage")
    reasons: list[str] = []
    if manifest.get("oracle") != "MAME 0.287":
        reasons.append("oracle_must_be_MAME_0.287")
    if not valid_sha256(rom_sha256):
        reasons.append("rom_sha256_invalid")
    if not isinstance(coverage, dict):
        coverage = {}
        reasons.append("coverage_missing")
    start = coverage.get("game_tick_start")
    end = coverage.get("game_tick_end")
    if not isinstance(start, int) or not isinstance(end, int) or start > end:
        reasons.append("coverage_tick_range_invalid")
    if coverage.get("complete") is not True:
        reasons.append("coverage_not_complete")
    provenance = manifest.get("provenance")
    if not isinstance(provenance, dict):
        reasons.append("provenance_missing")
    else:
        for field in (
            "mame_executable_sha256",
            "mame_timeline_sha256",
            "snes_emulator_sha256",
        ):
            if not valid_sha256(provenance.get(field)):
                reasons.append(f"{field}_invalid")
    frames = manifest.get("frames")
    if not isinstance(frames, list) or not frames:
        frames = []
        reasons.append("frames_missing")
    for index, row in enumerate(frames):
        if not isinstance(row, dict):
            reasons.append(f"frame_{index}_not_an_object")
            continue
        if not isinstance(row.get("game_tick"), int):
            reasons.append(f"frame_{index}_game_tick_invalid")
        for field in ("mame", "snes"):
            if field not in row:
                reasons.append(f"frame_{index}_{field}_missing")
            elif not resolve(manifest_path.parent, row[field]).is_file():
                reasons.append(f"frame_{index}_{field}_file_missing")
    ticks = [row.get("game_tick") for row in frames if isinstance(row, dict)]
    if isinstance(start, int) and isinstance(end, int):
        expected_ticks = list(range(start, end + 1))
        if ticks != expected_ticks:
            reasons.append("not_every_game_tick_is_covered_exactly_once")

    output = args.output.resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    diff_dir = output.parent / f"{output.stem}-diffs"
    rows: list[dict[str, Any]] = []
    if not reasons:
        for index, item in enumerate(frames):
            mame_path = resolve(manifest_path.parent, item["mame"])
            snes_path = resolve(manifest_path.parent, item["snes"])
            mame_source = Image.open(mame_path).convert("RGB")
            if mame_source.size != MAME_SIZE:
                raise SystemExit(
                    f"tick {item['game_tick']}: expected MAME {MAME_SIZE}, got {mame_source.size}"
                )
            mame = mame_source.crop(MAME_CROP)
            snes, snes_meta = normalize(snes_path)
            difference = ImageChops.difference(mame, snes)
            changed = changed_pixel_count(difference)
            playfield = changed_pixel_count(difference.crop(PLAYFIELD_BOX))
            scene = changed_pixel_count(difference.crop(SCENE_BOX))
            result = "green" if changed == 0 else "red"
            row: dict[str, Any] = {
                "index": index,
                "label": int(item["game_tick"]),
                "game_tick": int(item["game_tick"]),
                "result": result,
                "changed_pixels": changed,
                "playfield_changed_pixels": playfield,
                "scene_changed_pixels": scene,
                "difference_bbox": (
                    list(difference.getbbox()) if difference.getbbox() else None
                ),
                "mame": {
                    "path": str(mame_path.resolve()),
                    "file_sha256": file_sha256(mame_path),
                    "registered_rgb_sha256": image_sha256(mame),
                },
                "snes": snes_meta,
            }
            if result == "red":
                diff_dir.mkdir(parents=True, exist_ok=True)
                mask = difference.convert("L").point(
                    lambda value: 255 if value else 0
                )
                diff = Image.new("RGB", ACTIVE_SIZE, (0, 0, 0))
                diff.paste((255, 0, 0), mask=mask)
                diff_path = diff_dir / f"tick-{item['game_tick']:06d}.png"
                diff.save(diff_path)
                row["difference_mask"] = str(diff_path)
            rows.append(row)

    mismatches = [row for row in rows if row["result"] == "red"]
    status = "unknown" if reasons else ("red" if mismatches else "green")
    first = mismatches[0] if mismatches else None
    acceptance_gate = gate(
        "aligned_pixel_oracle",
        status,
        rom_sha256 if valid_sha256(rom_sha256) else None,
        coverage or None,
        authority="exact_mame_pixels" if status != "unknown" else "none",
        reason=";".join(sorted(set(reasons))) if reasons else None,
    )
    report = {
        "schema": 1,
        "scope": (
            "exact MAME 0.287 versus SNES active-display pixels at every game tick"
        ),
        "manifest": str(manifest_path),
        "rom_sha256": rom_sha256,
        "coverage": coverage,
        "registration": {"mame_crop": list(MAME_CROP), "snes_size": list(ACTIVE_SIZE)},
        "frames_compared": len(rows),
        "mismatch_frames": len(mismatches),
        "first_divergence": (
            {
                "game_tick": first["game_tick"],
                "changed_pixels": first["changed_pixels"],
                "playfield_changed_pixels": first["playfield_changed_pixels"],
                "difference_bbox": first["difference_bbox"],
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
