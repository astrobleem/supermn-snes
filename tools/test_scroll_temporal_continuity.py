#!/usr/bin/env python3
"""Regression test for the focused temporal-scroll gate."""

from __future__ import annotations

import hashlib
import json
import subprocess
import tempfile
from pathlib import Path

from PIL import Image


ROOT = Path(__file__).resolve().parents[1]
TOOL = ROOT / "tools/validate_scroll_temporal_continuity.py"


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def make_capture(directory: Path, *, failure: str | None) -> Path:
    base = Image.new("RGB", (320, 224))
    for y in range(224):
        for x in range(320):
            base.putpixel(
                (x, y),
                ((x * 13 + y) & 0xFF, (x + y * 7) & 0xFF, (x * 3) & 0xFF),
            )

    captures = []
    for frame in range(28):
        tick = frame // 2
        # The 30 Hz source advances three pixels per tick.  A correct 60 Hz
        # presenter splits that target displacement 1/2 pixels across both
        # video frames.  The historical bug either held then jumped three, or
        # accumulated several targets into a larger jump.
        if failure == "accumulated":
            displayed = (tick // 3) * 9
        elif failure == "hold_jump":
            displayed = tick * 3
        else:
            displayed = (frame * 3) // 2
        ppu_position = 32 + displayed
        if failure == "coordinate_rebase" and frame >= 14:
            ppu_position -= 32
        image_path = directory / f"frame-{frame:06d}.png"
        base.crop((displayed, 0, displayed + 256, 224)).save(image_path)
        captures.append(
            {
                "frame": frame,
                "live_scrollx_column0": (0x80 - tick * 3) & 0xFF,
                "live_scrollx_column4": (0x80 - tick * 3) & 0xFF,
                "latest_scrollx": (0x80 - tick * 3) & 0xFF,
                "bg1_hscroll": ppu_position,
                "displayed_bg_map_sha256": (
                    "map-after" if failure == "coordinate_rebase" and frame >= 14
                    else "map-before"
                ),
                "screenshot": {
                    "path": str(image_path),
                    "sha256": sha256(image_path),
                },
            }
        )
    results = directory / "results.json"
    results.write_text(json.dumps({"captures": captures}, indent=2) + "\n")
    return results


def run(results: Path, output: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [
            "python3",
            str(TOOL),
            "--results",
            str(results),
            "--output",
            str(output),
            "--minimum-source-steps",
            "10",
        ],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="scroll-temporal-test-") as raw:
        temp = Path(raw)
        smooth_dir = temp / "smooth"
        smooth_dir.mkdir()
        smooth_output = smooth_dir / "report.json"
        smooth = run(make_capture(smooth_dir, failure=None), smooth_output)
        assert smooth.returncode == 0, smooth.stderr or smooth.stdout
        smooth_report = json.loads(smooth_output.read_text())
        assert smooth_report["result"] == "green"
        assert smooth_report["source_scroll_key"] == "latest_scrollx"
        assert smooth_report["source_step_count"] == 12
        assert smooth_report["ppu_step_count"] == 25
        assert smooth_report["registration_shift_histogram"] == {"1": 13, "2": 12}

        rebase_dir = temp / "coordinate-rebase"
        rebase_dir.mkdir()
        rebase_output = rebase_dir / "report.json"
        rebased = run(
            make_capture(rebase_dir, failure="coordinate_rebase"),
            rebase_output,
        )
        assert rebased.returncode == 0, rebased.stderr or rebased.stdout
        rebase_report = json.loads(rebase_output.read_text())
        assert rebase_report["result"] == "green"
        assert len(rebase_report["coordinate_rebases"]) == 1
        assert rebase_report["coordinate_rebases"][0]["ppu_delta_signed1024"] == -30

        hold_dir = temp / "hold-jump"
        hold_dir.mkdir()
        hold_output = hold_dir / "report.json"
        held = run(make_capture(hold_dir, failure="hold_jump"), hold_output)
        assert held.returncode == 1, held.stderr or held.stdout
        hold_report = json.loads(hold_output.read_text())
        assert hold_report["result"] == "red"
        assert hold_report["held_presentations"]
        assert hold_report["oversized_presentations"]

        skip_dir = temp / "accumulated"
        skip_dir.mkdir()
        skip_output = skip_dir / "report.json"
        skipped = run(make_capture(skip_dir, failure="accumulated"), skip_output)
        assert skipped.returncode == 1, skipped.stderr or skipped.stdout
        skip_report = json.loads(skip_output.read_text())
        assert skip_report["result"] == "red"
        assert skip_report["ppu_step_count"] < skip_report["source_step_count"]
        assert skip_report["wrong_ppu_steps"]

    print("temporal scroll cadence gate: green")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
