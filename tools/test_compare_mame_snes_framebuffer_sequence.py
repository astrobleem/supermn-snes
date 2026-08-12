#!/usr/bin/env python3
"""Regression tests for exact-MAME every-game-tick pixel coverage."""

from __future__ import annotations

import json
import subprocess
import tempfile
from pathlib import Path

from PIL import Image


ROOT = Path(__file__).resolve().parents[1]
TOOL = ROOT / "tools/compare_mame_snes_framebuffer_sequence.py"
ROM_SHA = "2" * 64
IDENTITY = "3" * 64


def run(manifest: Path, output: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["python3", str(TOOL), "--manifest", str(manifest), "--output", str(output)],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="mame-frame-sequence-test-") as raw:
        temp = Path(raw)
        snes = Image.new("RGB", (256, 224), (10, 20, 30))
        snes_path = temp / "snes.png"
        snes.save(snes_path)
        altered = snes.copy()
        altered.putpixel((80, 100), (255, 0, 255))
        altered_path = temp / "altered.png"
        altered.save(altered_path)
        mame = Image.new("RGB", (384, 240), (0, 0, 0))
        mame.paste(snes, (64, 1))
        mame_path = temp / "mame.png"
        mame.save(mame_path)
        manifest = temp / "manifest.json"
        base = {
            "oracle": "MAME 0.287",
            "rom_sha256": ROM_SHA,
            "coverage": {
                "game_tick_start": 20,
                "game_tick_end": 21,
                "complete": True,
            },
            "provenance": {
                "mame_executable_sha256": IDENTITY,
                "mame_timeline_sha256": IDENTITY,
                "snes_emulator_sha256": IDENTITY,
            },
            "frames": [
                {"game_tick": 20, "mame": str(mame_path), "snes": str(snes_path)},
                {"game_tick": 21, "mame": str(mame_path), "snes": str(altered_path)},
            ],
        }
        manifest.write_text(json.dumps(base), encoding="utf-8")
        red_output = temp / "red.json"
        red = run(manifest, red_output)
        assert red.returncode == 1, red.stderr or red.stdout
        report = json.loads(red_output.read_text(encoding="utf-8"))
        assert report["acceptance_gate"]["status"] == "red"
        assert report["first_divergence"]["game_tick"] == 21
        assert report["mismatch_ranges"][0]["start_label"] == 21

        base["frames"][1]["snes"] = str(snes_path)
        manifest.write_text(json.dumps(base), encoding="utf-8")
        green_output = temp / "green.json"
        green = run(manifest, green_output)
        assert green.returncode == 0, green.stderr or green.stdout
        green_report = json.loads(green_output.read_text(encoding="utf-8"))
        assert green_report["acceptance_gate"]["status"] == "green"
        assert green_report["frames_compared"] == 2

        base["frames"] = base["frames"][:1]
        manifest.write_text(json.dumps(base), encoding="utf-8")
        unknown_output = temp / "unknown.json"
        unknown = run(manifest, unknown_output)
        assert unknown.returncode == 2, unknown.stderr or unknown.stdout
        unknown_report = json.loads(unknown_output.read_text(encoding="utf-8"))
        assert unknown_report["acceptance_gate"]["status"] == "unknown"
        assert "not_every_game_tick_is_covered_exactly_once" in unknown_report[
            "coverage_errors"
        ]

    print("exact-MAME every-game-tick framebuffer sequence: green")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
