#!/usr/bin/env python3
"""Pure pixel-predicate checks for the one-credit prompt gate."""

from __future__ import annotations

import tempfile
from pathlib import Path

from PIL import Image

import validate_fresh_one_credit_prompt as gate


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="one-credit-prompt-pixels-") as raw:
        path = Path(raw) / "prompt.png"
        image = Image.new("RGB", (256, 239), (0, 0, 0))
        gray = (148, 148, 148)
        for y in range(190, 221):
            for x in range(150, y - 30):
                image.putpixel((x, y), gray)
                image.putpixel((255 - x, y), gray)
        image.save(path)

        symmetric = gate.inspect_pixels(path)
        assert symmetric["left_wedge_black_count"] == 0
        assert symmetric["right_wedge_black_count"] == 0

        image.putpixel((100, 200), (0, 0, 0))
        image.save(path)
        broken_left = gate.inspect_pixels(path)
        assert broken_left["left_wedge_black_count"] == 1
        assert broken_left["left_wedge_black_first"] == [[100, 200]]
        assert broken_left["right_wedge_black_count"] == 0

    print("fresh one-credit prompt pixel checks: green")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
