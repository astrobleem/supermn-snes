#!/usr/bin/env python3
"""Compare an explicitly aligned SNES framebuffer sequence.

The manifest is a JSON object with a ``frames`` array.  Each row supplies a
stable ``label`` plus ``reference`` and ``candidate`` PNG paths.  Relative paths
are resolved beside the manifest.  Every row is compared, while difference
masks are retained only for mismatches.  The console result stays compact; the
full metrics remain in the output JSON.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from PIL import Image, ImageChops

from compare_snes_framebuffers import (
    ACTIVE_SIZE,
    PLAYFIELD_BOX,
    changed_pixel_count,
    normalize,
    repetition_metrics,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--max-changed-pixels", type=int, default=0)
    return parser.parse_args()


def resolve_path(manifest: Path, raw: str) -> Path:
    path = Path(raw)
    return path if path.is_absolute() else manifest.parent / path


def mismatch_ranges(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    ranges: list[dict[str, Any]] = []
    start: dict[str, Any] | None = None
    previous: dict[str, Any] | None = None
    for row in rows:
        if row["result"] == "red":
            if start is None:
                start = row
            previous = row
        elif start is not None and previous is not None:
            ranges.append(
                {
                    "start_index": start["index"],
                    "end_index": previous["index"],
                    "start_label": start["label"],
                    "end_label": previous["label"],
                }
            )
            start = previous = None
    if start is not None and previous is not None:
        ranges.append(
            {
                "start_index": start["index"],
                "end_index": previous["index"],
                "start_label": start["label"],
                "end_label": previous["label"],
            }
        )
    return ranges


def main() -> int:
    args = parse_args()
    if args.max_changed_pixels < 0:
        raise SystemExit("--max-changed-pixels must be nonnegative")
    manifest_path = args.manifest.resolve()
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    frames = manifest.get("frames")
    if not isinstance(frames, list) or not frames:
        raise SystemExit("manifest must contain a nonempty frames array")

    output = args.output.resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    diff_dir = output.parent / f"{output.stem}-diffs"
    results: list[dict[str, Any]] = []

    for index, item in enumerate(frames):
        if not isinstance(item, dict):
            raise SystemExit(f"frame {index}: expected an object")
        label = item.get("label", index)
        reference_path = resolve_path(manifest_path, str(item["reference"]))
        candidate_path = resolve_path(manifest_path, str(item["candidate"]))
        reference, reference_meta = normalize(reference_path)
        candidate, candidate_meta = normalize(candidate_path)
        difference = ImageChops.difference(reference, candidate)
        changed = changed_pixel_count(difference)
        playfield_changed = changed_pixel_count(difference.crop(PLAYFIELD_BOX))
        result = "green" if changed <= args.max_changed_pixels else "red"
        reference_repetition = repetition_metrics(reference)
        candidate_repetition = repetition_metrics(candidate)
        row: dict[str, Any] = {
            "index": index,
            "label": label,
            "result": result,
            "changed_pixels": changed,
            "changed_ratio": changed / (ACTIVE_SIZE[0] * ACTIVE_SIZE[1]),
            "playfield_changed_pixels": playfield_changed,
            "difference_bbox": (
                list(difference.getbbox()) if difference.getbbox() else None
            ),
            "reference": reference_meta,
            "candidate": candidate_meta,
            "tile_repetition": {
                "reference": reference_repetition,
                "candidate": candidate_repetition,
            },
        }
        if result == "red":
            diff_dir.mkdir(parents=True, exist_ok=True)
            mask = difference.convert("L").point(lambda value: 255 if value else 0)
            diff_image = Image.new("RGB", ACTIVE_SIZE, (0, 0, 0))
            diff_image.paste((255, 0, 0), mask=mask)
            diff_path = diff_dir / f"{index:06d}.png"
            diff_image.save(diff_path)
            row["difference_mask"] = str(diff_path)
        results.append(row)

    mismatches = [row for row in results if row["result"] == "red"]
    first = mismatches[0] if mismatches else None
    report = {
        "schema": 1,
        "scope": (
            "aligned consecutive SNES framebuffer comparison; every manifest "
            "row compared, mismatch masks retained only for red rows"
        ),
        "manifest": str(manifest_path),
        "threshold": args.max_changed_pixels,
        "result": "red" if mismatches else "green",
        "frames_compared": len(results),
        "mismatch_frames": len(mismatches),
        "first_divergence": (
            {
                "index": first["index"],
                "label": first["label"],
                "changed_pixels": first["changed_pixels"],
                "playfield_changed_pixels": first["playfield_changed_pixels"],
                "difference_bbox": first["difference_bbox"],
            }
            if first is not None
            else None
        ),
        "mismatch_ranges": mismatch_ranges(results),
        "frames": results,
    }
    output.write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(
        json.dumps(
            {
                "result": report["result"],
                "frames_compared": report["frames_compared"],
                "mismatch_frames": report["mismatch_frames"],
                "first_divergence": report["first_divergence"],
                "mismatch_ranges": report["mismatch_ranges"],
                "report": str(output),
            },
            sort_keys=True,
        )
    )
    return 1 if mismatches else 0


if __name__ == "__main__":
    raise SystemExit(main())
