#!/usr/bin/env python3
"""Regression tests for every-video-frame renderer conservation."""

from __future__ import annotations

import hashlib
import json
import subprocess
import tempfile
from pathlib import Path

from PIL import Image

from gameplay_acceptance_contract import gate, tick_coverage


ROOT = Path(__file__).resolve().parents[1]
TOOL = ROOT / "tools/validate_snes_framebuffer_conservation.py"
ROM_SHA = "4" * 64


def run(manifest: Path, output: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["python3", str(TOOL), "--manifest", str(manifest), "--output", str(output)],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="frame-conservation-test-") as raw:
        temp = Path(raw)
        paths = {}
        for name, color in {
            "previous": (120, 10, 10),
            "next": (10, 10, 120),
            "corrupt": (10, 120, 10),
        }.items():
            path = temp / f"{name}.png"
            Image.new("RGB", (256, 224), color).save(path)
            paths[name] = path
        mame_paths = {}
        for name in ("previous", "next"):
            mame = Image.new("RGB", (384, 240), (0, 0, 0))
            mame.paste(Image.open(paths[name]).convert("RGB"), (64, 1))
            path = temp / f"mame-{name}.png"
            mame.save(path)
            mame_paths[name] = path
        aligned_report = temp / "aligned.json"
        aligned_report.write_text(
            json.dumps(
                {
                    "acceptance_gate": gate(
                        "aligned_pixel_oracle",
                        "green",
                        ROM_SHA,
                        tick_coverage(30, 31, complete=True),
                        authority="exact_mame_pixels",
                    ),
                    "frames": [
                        {
                            "game_tick": 30,
                            "mame": {
                                "path": str(mame_paths["previous"]),
                                "registered_rgb_sha256": hashlib.sha256(
                                    Image.open(paths["previous"]).convert("RGB").tobytes()
                                ).hexdigest(),
                            },
                        },
                        {
                            "game_tick": 31,
                            "mame": {
                                "path": str(mame_paths["next"]),
                                "registered_rgb_sha256": hashlib.sha256(
                                    Image.open(paths["next"]).convert("RGB").tobytes()
                                ).hexdigest(),
                            },
                        },
                    ],
                }
            ),
            encoding="utf-8",
        )
        manifest = temp / "manifest.json"
        frames = [
            (100, paths["previous"]),
            (101, paths["corrupt"]),
            (102, paths["next"]),
        ]
        data = {
            "rom_sha256": ROM_SHA,
            "aligned_pixel_report": str(aligned_report),
            "coverage": {
                "game_tick_start": 30,
                "game_tick_end": 31,
                "snes_video_frame_start": 100,
                "snes_video_frame_end": 102,
                "complete": True,
            },
            "frames": [
                {
                    "snes_video_frame": frame,
                    "candidate": str(candidate),
                    "previous_accepted_tick": 30,
                    "next_accepted_tick": 31,
                }
                for frame, candidate in frames
            ],
        }
        manifest.write_text(json.dumps(data), encoding="utf-8")
        red_output = temp / "red.json"
        red = run(manifest, red_output)
        assert red.returncode == 1, red.stderr or red.stdout
        report = json.loads(red_output.read_text(encoding="utf-8"))
        assert report["acceptance_gate"]["status"] == "red"
        assert report["first_divergence"]["snes_video_frame"] == 101

        data["frames"][1]["candidate"] = str(paths["previous"])
        manifest.write_text(json.dumps(data), encoding="utf-8")
        green_output = temp / "green.json"
        green = run(manifest, green_output)
        assert green.returncode == 0, green.stderr or green.stdout
        green_report = json.loads(green_output.read_text(encoding="utf-8"))
        assert green_report["acceptance_gate"]["status"] == "green"
        assert green_report["frames_compared"] == 3

        data["frames"] = data["frames"][::2]
        manifest.write_text(json.dumps(data), encoding="utf-8")
        unknown_output = temp / "unknown.json"
        unknown = run(manifest, unknown_output)
        assert unknown.returncode == 2, unknown.stderr or unknown.stdout
        unknown_report = json.loads(unknown_output.read_text(encoding="utf-8"))
        assert unknown_report["acceptance_gate"]["status"] == "unknown"
        assert "not_every_snes_video_frame_is_covered_exactly_once" in unknown_report[
            "coverage_errors"
        ]

    print("every-video-frame renderer conservation: green")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
