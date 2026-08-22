#!/usr/bin/env python3
"""Compare aligned SNES screenshots and retain compact pixel evidence.

Nexen captures 256x239 while exact Mesen 2.1.1 captures the 256x224 active
display.  Their accepted one-credit fixtures are byte-for-byte pixel-identical
when Nexen is cropped to its top 224 lines.  This tool makes that normalization
explicit, measures full-frame and playfield differences, and emits a red diff
image plus JSON.  It intentionally fails on any changed pixel by default.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

from PIL import Image, ImageChops

from gameplay_acceptance_contract import unknown_diagnostic_gate


ACTIVE_SIZE = (256, 224)
PLAYFIELD_BOX = (0, 24, 256, 224)
# Gameplay picture excluding both the repositioned top HUD and the arcade/SNES
# bottom status-line difference.  This is diagnostic only; exact-composite
# acceptance still uses every pixel.
SCENE_BOX = (0, 24, 256, 208)
TILE_SIZE = 8


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--reference", type=Path, required=True)
    parser.add_argument("--candidate", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument(
        "--max-changed-pixels",
        type=int,
        default=0,
        help="acceptance threshold after normalization (default: exact equality)",
    )
    return parser.parse_args()


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def image_sha256(image: Image.Image) -> str:
    return hashlib.sha256(image.tobytes()).hexdigest()


def normalize(path: Path) -> tuple[Image.Image, dict[str, Any]]:
    image = Image.open(path).convert("RGB")
    original_size = image.size
    if image.width != ACTIVE_SIZE[0] or image.height < ACTIVE_SIZE[1]:
        raise ValueError(
            f"{path}: expected width 256 and at least 224 lines, got {image.size}"
        )
    active = image.crop((0, 0, *ACTIVE_SIZE))
    return active, {
        "path": str(path.resolve()),
        "file_sha256": file_sha256(path),
        "original_size": list(original_size),
        "normalization": "RGB; crop top-left 256x224 active display",
        "active_rgb_sha256": image_sha256(active),
    }


def changed_pixel_count(difference: Image.Image) -> int:
    return sum(pixel != (0, 0, 0) for pixel in difference.getdata())


def tile_digest_counts(image: Image.Image, box: tuple[int, int, int, int]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for y in range(box[1], box[3], TILE_SIZE):
        for x in range(box[0], box[2], TILE_SIZE):
            tile = image.crop((x, y, x + TILE_SIZE, y + TILE_SIZE))
            key = hashlib.sha256(tile.tobytes()).hexdigest()
            counts[key] = counts.get(key, 0) + 1
    return counts


def repetition_metrics(image: Image.Image) -> dict[str, Any]:
    counts = tile_digest_counts(image, PLAYFIELD_BOX)
    ordered = sorted(counts.items(), key=lambda item: (-item[1], item[0]))
    total = sum(counts.values())
    dominant_hash, dominant_count = ordered[0]
    return {
        "tiles": total,
        "unique_tiles": len(counts),
        "dominant_tile_sha256": dominant_hash,
        "dominant_tile_count": dominant_count,
        "dominant_tile_ratio": dominant_count / total,
    }


def main() -> int:
    args = parse_args()
    if args.max_changed_pixels < 0:
        raise SystemExit("--max-changed-pixels must be nonnegative")

    reference, reference_meta = normalize(args.reference)
    candidate, candidate_meta = normalize(args.candidate)
    difference = ImageChops.difference(reference, candidate)
    changed = changed_pixel_count(difference)
    playfield_changed = changed_pixel_count(difference.crop(PLAYFIELD_BOX))
    extrema = difference.getextrema()
    max_channel_delta = max(high for _low, high in extrema)

    # Preserve a reviewable red mask without copying either source framebuffer.
    mask = difference.convert("L").point(lambda value: 255 if value else 0)
    diff_image = Image.new("RGB", ACTIVE_SIZE, (0, 0, 0))
    diff_image.paste((255, 0, 0), mask=mask)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    diff_path = args.output.with_suffix(".diff.png")
    diff_image.save(diff_path)

    report = {
        "schema": 1,
        "scope": (
            "aligned emulator framebuffer comparison; visual evidence only, "
            "not gameplay, performance, audio, or hardware acceptance"
        ),
        "reference": reference_meta,
        "candidate": candidate_meta,
        "active_size": list(ACTIVE_SIZE),
        "playfield_box": list(PLAYFIELD_BOX),
        "comparison": {
            "changed_pixels": changed,
            "changed_ratio": changed / (ACTIVE_SIZE[0] * ACTIVE_SIZE[1]),
            "difference_bbox": list(difference.getbbox()) if difference.getbbox() else None,
            "playfield_changed_pixels": playfield_changed,
            "playfield_changed_ratio": playfield_changed
            / ((PLAYFIELD_BOX[2] - PLAYFIELD_BOX[0]) * (PLAYFIELD_BOX[3] - PLAYFIELD_BOX[1])),
            "max_channel_delta": max_channel_delta,
            "threshold": args.max_changed_pixels,
            "result": "green" if changed <= args.max_changed_pixels else "red",
        },
        "tile_repetition": {
            "reference": repetition_metrics(reference),
            "candidate": repetition_metrics(candidate),
        },
        "artifacts": {"difference_mask": str(diff_path.resolve())},
        "acceptance_gate": unknown_diagnostic_gate(
            "cross_emulator_pixels",
            (
                "A single SNES-to-SNES frame comparison is not an exact-MAME "
                "sequence or an every-video-frame conservation proof."
            ),
        ),
    }
    args.output.write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(json.dumps(report["comparison"], sort_keys=True))
    return 0 if report["comparison"]["result"] == "green" else 1


if __name__ == "__main__":
    raise SystemExit(main())
