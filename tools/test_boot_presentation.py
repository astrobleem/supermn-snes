#!/usr/bin/env python3
"""Pure regression checks for the fail-closed boot visual component gate."""

from __future__ import annotations

import tempfile
from pathlib import Path

from PIL import Image, ImageDraw

from validate_boot_presentation import evaluate


def frame(path: Path, logo_left: int, *, text: bool = True, corruption: bool = False) -> None:
    image = Image.new("RGB", (256, 224))
    draw = ImageDraw.Draw(image)
    if text:
        draw.rectangle((41, 32, 214, 54), fill=(220, 220, 220))
        draw.rectangle((37, 192, 218, 198), fill=(220, 220, 220))
    draw.rectangle((logo_left, 74, logo_left + 131, 148), fill=(20, 90, 210))
    draw.rectangle((228, 192, 235, 198), fill=(220, 140, 20))
    if corruption:
        draw.point((4, 170), fill=(255, 0, 0))
    image.save(path)


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="boot-presentation-") as raw:
        root = Path(raw)
        reference = root / "reference.png"
        good = root / "good.png"
        shifted = root / "shifted.png"
        corrupt = root / "corrupt.png"
        frame(reference, 58)
        frame(good, 58)
        frame(shifted, 0)
        frame(corrupt, 58, corruption=True)

        assert evaluate([reference], [good])["status"] == "pass"
        shifted_report = evaluate([reference], [shifted])
        assert shifted_report["status"] == "fail"
        assert any("logo_fully_visible" in value for value in shifted_report["failures"])
        corrupt_report = evaluate([reference], [corrupt])
        assert corrupt_report["status"] == "fail"
        assert any("no_unexpected_nonblack_pixels" in value for value in corrupt_report["failures"])

    print("boot presentation component gate: green")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
