#!/usr/bin/env python3
"""Compare Superman's intentionally reflowed top HUD against MAME pixels.

The arcade output is 384 pixels wide.  Gameplay uses the centered x=64..319
crop, but the outer 1UP/2UP records are moved inward so neither score is
clipped on the 256-pixel SNES display.  Top-HUD OBJ wrap also preserves MAME
rows 0..15 directly rather than applying the gameplay y=1 crop.

This is deliberately a HUD-component oracle.  It never widens a green result
to the background, gameplay objects, or the full composite framebuffer.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

from PIL import Image

from gameplay_acceptance_contract import gate, valid_sha256


MAME_SIZE = (384, 240)
SNES_SIZE = (256, 224)
HUD_HEIGHT = 16
HUD_COLORS = ((247, 0, 0), (247, 247, 247))


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    return parser.parse_args()


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def transformed_x(source_x: int) -> int:
    """Apply production's left/center/right HUD record placement."""
    if source_x < 80:
        return source_x - 16
    if source_x < 288:
        return source_x - 64
    return source_x - 112


def keyed_pixels(image: Image.Image, *, transformed: bool) -> dict[tuple[int, int], tuple[int, int, int]]:
    pixels: dict[tuple[int, int], tuple[int, int, int]] = {}
    for y in range(HUD_HEIGHT):
        for x in range(image.width):
            color = image.getpixel((x, y))
            if color not in HUD_COLORS:
                continue
            output_x = transformed_x(x) if transformed else x
            if 0 <= output_x < SNES_SIZE[0]:
                pixels[(output_x, y)] = color
    return pixels


def keyed_image(pixels: dict[tuple[int, int], tuple[int, int, int]]) -> Image.Image:
    image = Image.new("RGB", (SNES_SIZE[0], HUD_HEIGHT), (0, 0, 0))
    for coordinate, color in pixels.items():
        image.putpixel(coordinate, color)
    return image


def main() -> int:
    args = parse_args()
    manifest = json.loads(args.manifest.read_text(encoding="utf-8"))
    frames = manifest.get("frames")
    if not isinstance(frames, list) or not frames:
        raise SystemExit("manifest has no frames")

    args.output.mkdir(parents=True, exist_ok=False)
    frame_reports: list[dict[str, object]] = []
    review_rows: list[Image.Image] = []
    review_indexes = {0, len(frames) // 2, len(frames) - 1}
    for index, row in enumerate(frames):
        mame_path = Path(row["mame"])
        snes_path = Path(row["snes"])
        mame = Image.open(mame_path).convert("RGB")
        snes = Image.open(snes_path).convert("RGB")
        if mame.size != MAME_SIZE:
            raise SystemExit(f"expected MAME {MAME_SIZE}, got {mame.size}: {mame_path}")
        if snes.size != SNES_SIZE:
            raise SystemExit(f"expected SNES {SNES_SIZE}, got {snes.size}: {snes_path}")

        expected = keyed_pixels(mame, transformed=True)
        observed = keyed_pixels(snes, transformed=False)
        missing = sorted(set(expected) - set(observed))
        extra = sorted(set(observed) - set(expected))
        wrong_color = sorted(
            coordinate
            for coordinate in set(expected) & set(observed)
            if expected[coordinate] != observed[coordinate]
        )
        result = "green" if not missing and not extra and not wrong_color else "red"
        frame_reports.append(
            {
                "index": index,
                "game_tick": row.get("game_tick"),
                "mame": str(mame_path.resolve()),
                "snes": str(snes_path.resolve()),
                "expected_pixels": len(expected),
                "observed_pixels": len(observed),
                "missing_pixels": len(missing),
                "extra_pixels": len(extra),
                "wrong_color_pixels": len(wrong_color),
                "first_missing": [list(value) for value in missing[:16]],
                "first_extra": [list(value) for value in extra[:16]],
                "first_wrong_color": [list(value) for value in wrong_color[:16]],
                "result": result,
            }
        )
        if index in review_indexes:
            source = mame.crop((0, 0, 384, HUD_HEIGHT)).resize((384, 32))
            expected_image = keyed_image(expected).resize((512, 32))
            observed_image = snes.crop((0, 0, 256, HUD_HEIGHT)).resize((512, 32))
            row_image = Image.new("RGB", (1408, 32), (0, 0, 0))
            row_image.paste(source, (0, 0))
            row_image.paste(expected_image, (384, 0))
            row_image.paste(observed_image, (896, 0))
            review_rows.append(row_image)

    review = Image.new("RGB", (1408, 32 * len(review_rows)), (0, 0, 0))
    for index, row_image in enumerate(review_rows):
        review.paste(row_image, (0, index * 32))
    review_path = args.output / "hud-review.png"
    review.save(review_path)

    failures = [row for row in frame_reports if row["result"] != "green"]
    coverage = manifest.get("coverage")
    rom_sha256 = manifest.get("rom_sha256")
    complete = bool(isinstance(coverage, dict) and coverage.get("complete"))
    gate_ready = valid_sha256(rom_sha256) and complete
    result = "green" if not failures and gate_ready else "red"
    report = {
        "schema": 1,
        "scope": (
            "exact red/white top-HUD glyph pixels after the production narrow-screen "
            "left/center/right placement transform; no full-composite claim"
        ),
        "oracle": manifest.get("oracle"),
        "rom_sha256": rom_sha256,
        "coverage": coverage,
        "mapping": {
            "mame_rows": [0, HUD_HEIGHT - 1],
            "snes_rows": [0, HUD_HEIGHT - 1],
            "source_x_0_79": "destination_x = source_x - 16",
            "source_x_80_287": "destination_x = source_x - 64",
            "source_x_288_383": "destination_x = source_x - 112",
            "keyed_rgb_colors": [list(color) for color in HUD_COLORS],
        },
        "summary": {
            "frames": len(frame_reports),
            "green_frames": len(frame_reports) - len(failures),
            "red_frames": len(failures),
            "first_failure_game_tick": failures[0]["game_tick"] if failures else None,
            "result": result,
        },
        "frames": frame_reports,
        "artifacts": {
            "review": str(review_path.resolve()),
            "review_sha256": file_sha256(review_path),
            "manifest": str(args.manifest.resolve()),
            "manifest_sha256": file_sha256(args.manifest),
        },
        "acceptance_gate": gate(
            "aligned_transformed_hud_oracle",
            result if gate_ready else "unknown",
            rom_sha256 if valid_sha256(rom_sha256) else None,
            coverage if gate_ready else None,
            authority="exact_mame_transformed_hud_pixels" if gate_ready else "none",
            reason=None if gate_ready else "Exact ROM hash and complete manifest coverage are required.",
        ),
    }
    report_path = args.output / "report.json"
    report_path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(report["summary"], sort_keys=True))
    return 0 if result == "green" else 1


if __name__ == "__main__":
    raise SystemExit(main())
