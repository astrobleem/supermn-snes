#!/usr/bin/env python3
"""Pure checks for the scene-generation coherence component gate."""

from validate_scene_generation_coherence import evaluate


def capture(
    frame: int,
    tick: int,
    sequence: int,
    base: int,
    presented: int,
    compensation: int | None = None,
) -> dict[str, int]:
    if compensation is None:
        compensation = (base - presented) & 0xFF
    return {
        "relative_frame": frame,
        "tick": tick,
        "presented_scrollx": presented,
        "obj_published_sequence": sequence,
        "obj_published_base_scrollx": base,
        "obj_published_comp": compensation,
        "obj_published_valid": 0xA5,
    }


def main() -> int:
    green = {
        "rom_sha256": "a" * 64,
        "captures": [
            capture(0, 100, 98, 200, 205),
            capture(1, 100, 98, 200, 203),
            capture(2, 101, 99, 200, 201),
            capture(3, 101, 99, 200, 200),
        ],
    }
    assert evaluate(green)["status"] == "pass"

    cross_generation = {
        "rom_sha256": "b" * 64,
        "captures": [
            capture(0, 120, 110, 160, 150),
            capture(1, 120, 110, 160, 148, compensation=10),
            capture(2, 121, 110, 160, 146, compensation=10),
        ],
    }
    report = evaluate(cross_generation)
    assert report["status"] == "fail"
    assert report["mismatch_ranges"]["camera_oam_compensation"] == [[1, 2]]
    assert report["mismatch_ranges"]["oam_age"] == [[0, 2]]

    print("scene-generation coherence component gate: green")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
