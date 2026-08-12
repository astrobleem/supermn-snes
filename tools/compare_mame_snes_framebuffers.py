#!/usr/bin/env python3
"""Register and compare an exact-MAME frame with an SNES framebuffer.

Superman's 384x240 arcade output registers to the SNES viewport by cropping
MAME x=64..319 and y=1..224.  The top HUD is reported separately because the
SNES port intentionally repositions it for the narrower display.  Exact pixel
equality remains the default acceptance threshold.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from PIL import Image, ImageChops

from compare_snes_framebuffers import (
    ACTIVE_SIZE,
    PLAYFIELD_BOX,
    changed_pixel_count,
    file_sha256,
    image_sha256,
    repetition_metrics,
)


MAME_SIZE = (384, 240)
MAME_CROP = (64, 1, 320, 225)
HUD_BOX = (0, 0, 256, 24)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--mame", type=Path, required=True)
    parser.add_argument("--snes", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--max-changed-pixels", type=int, default=0)
    parser.add_argument("--max-playfield-changed-pixels", type=int, default=0)
    return parser.parse_args()


def region_changed(difference: Image.Image, box: tuple[int, int, int, int]) -> int:
    return changed_pixel_count(difference.crop(box))


def main() -> int:
    args = parse_args()
    if min(args.max_changed_pixels, args.max_playfield_changed_pixels) < 0:
        raise SystemExit("changed-pixel thresholds must be nonnegative")
    mame_source = Image.open(args.mame).convert("RGB")
    snes_source = Image.open(args.snes).convert("RGB")
    if mame_source.size != MAME_SIZE:
        raise SystemExit(f"expected a 384x240 MAME frame, got {mame_source.size}")
    if snes_source.width != 256 or snes_source.height < 224:
        raise SystemExit(
            f"expected a 256-wide SNES frame with at least 224 lines, got {snes_source.size}"
        )
    mame = mame_source.crop(MAME_CROP)
    snes = snes_source.crop((0, 0, *ACTIVE_SIZE))
    difference = ImageChops.difference(mame, snes)
    changed = changed_pixel_count(difference)
    playfield_changed = region_changed(difference, PLAYFIELD_BOX)
    hud_changed = region_changed(difference, HUD_BOX)
    green = (
        changed <= args.max_changed_pixels
        and playfield_changed <= args.max_playfield_changed_pixels
    )

    args.output.parent.mkdir(parents=True, exist_ok=True)
    diff_path = args.output.with_suffix(".diff.png")
    mask = difference.convert("L").point(lambda value: 255 if value else 0)
    diff_image = Image.new("RGB", ACTIVE_SIZE, (0, 0, 0))
    diff_image.paste((255, 0, 0), mask=mask)
    diff_image.save(diff_path)
    registered_path = args.output.with_suffix(".mame-registered.png")
    mame.save(registered_path)

    report = {
        "schema": 1,
        "scope": (
            "registered MAME 0.287 versus SNES active-display pixels; HUD is "
            "reported separately because its SNES placement is intentionally narrower"
        ),
        "registration": {
            "mame_source_size": list(MAME_SIZE),
            "mame_crop": list(MAME_CROP),
            "snes_crop": [0, 0, *ACTIVE_SIZE],
        },
        "mame": {
            "path": str(args.mame.resolve()),
            "file_sha256": file_sha256(args.mame),
            "registered_rgb_sha256": image_sha256(mame),
        },
        "snes": {
            "path": str(args.snes.resolve()),
            "file_sha256": file_sha256(args.snes),
            "active_rgb_sha256": image_sha256(snes),
            "source_size": list(snes_source.size),
        },
        "comparison": {
            "changed_pixels": changed,
            "changed_ratio": changed / (ACTIVE_SIZE[0] * ACTIVE_SIZE[1]),
            "hud_changed_pixels": hud_changed,
            "playfield_changed_pixels": playfield_changed,
            "playfield_changed_ratio": playfield_changed
            / ((PLAYFIELD_BOX[2] - PLAYFIELD_BOX[0]) * (PLAYFIELD_BOX[3] - PLAYFIELD_BOX[1])),
            "difference_bbox": (
                list(difference.getbbox()) if difference.getbbox() else None
            ),
            "max_changed_pixels": args.max_changed_pixels,
            "max_playfield_changed_pixels": args.max_playfield_changed_pixels,
            "result": "green" if green else "red",
        },
        "tile_repetition": {
            "mame": repetition_metrics(mame),
            "snes": repetition_metrics(snes),
        },
        "artifacts": {
            "registered_mame": str(registered_path),
            "difference_mask": str(diff_path),
        },
    }
    args.output.write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(json.dumps(report["comparison"], sort_keys=True))
    return 0 if green else 1


if __name__ == "__main__":
    raise SystemExit(main())
