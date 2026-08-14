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
        obj_base_scrollx = (0x80 - tick * 3) & 0xFF
        presented_scrollx = (0x80 - displayed) & 0xFF
        obj_comp = (obj_base_scrollx - presented_scrollx) & 0xFF
        absolute_map_basis = 0xC0 if failure == "basis_drift" else 0x80
        world_x = 100 if failure == "obj_hold" else 100 + obj_comp
        fixed_x = 50 + (obj_comp if failure == "obj_hud" else 0)
        presentation_oam = bytearray(0x220)
        presentation_oam[0:8] = bytes(
            (fixed_x & 0xFF, 0x08, 0x11, 0x22,
             world_x & 0xFF, 0x40, 0x22, 0x33)
        )
        if world_x & 0x100:
            presentation_oam[0x200] |= 0x04
        presentation_sha = hashlib.sha256(presentation_oam).hexdigest()
        captures.append(
            {
                "frame": frame,
                "live_scrollx_column0": (0x80 - tick * 3) & 0xFF,
                "live_scrollx_column4": (0x80 - tick * 3) & 0xFF,
                "latest_scrollx": (0x80 - tick * 3) & 0xFF,
                "presented_scrollx": presented_scrollx,
                "bg1_hscroll": ppu_position,
                "bg_column_kind": 0,
                "bg_column_map": "000102030405060708090a0b0c0d0e0f",
                "displayed_column_map": "000102030405060708090a0b0c0d0e0f",
                "displayed_map_scrollx": absolute_map_basis,
                "displayed_map_valid": 0xA5,
                "obj_cache_scrollx": obj_base_scrollx,
                "scroll_packed": obj_base_scrollx << 8,
                "displayed_bg_map_sha256": (
                    "map-after" if failure == "coordinate_rebase" and frame >= 14
                    else "map-before"
                ),
                "screenshot": {
                    "path": str(image_path),
                    "sha256": sha256(image_path),
                },
                "hardware_oam": presentation_oam.hex(),
                "hardware_oam_sha256": presentation_sha,
                "presentation_oam": presentation_oam.hex(),
                "presentation_oam_sha256": presentation_sha,
                "obj_base_scrollx": obj_base_scrollx,
                "obj_present_valid": 0xA5,
                "obj_applied_comp": obj_comp,
                "obj_world_count": 1,
                "obj_dma_pending": 0,
                "obj_base_sequence": tick,
                "obj_dma_skips": 0,
                "obj_world_list": "04000004",
                "obj_published_sequence": tick,
                "obj_published_base_scrollx": obj_base_scrollx,
                "obj_published_comp": obj_comp,
                "obj_published_valid": 0xA5,
                "obj_world_first": 4,
                "obj_world_span": 4,
                "obj_partial_dmas": 0,
            }
        )
    results = directory / "results.json"
    results.write_text(
        json.dumps(
            {
                "provenance": {"obj_temporal_capture": True},
                "captures": captures,
            },
            indent=2,
        )
        + "\n"
    )
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

        basis_dir = temp / "basis-drift"
        basis_dir.mkdir()
        basis_output = basis_dir / "report.json"
        basis = run(make_capture(basis_dir, failure="basis_drift"), basis_output)
        assert basis.returncode == 1, basis.stderr or basis.stdout
        basis_report = json.loads(basis_output.read_text())
        assert basis_report["result"] == "red"
        assert basis_report["absolute_map_basis"]["violation_count"] == 28
        assert any(
            "absolute physical-map basis" in failure
            for failure in basis_report["failures"]
        )

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

        obj_hold_dir = temp / "obj-hold"
        obj_hold_dir.mkdir()
        obj_hold_output = obj_hold_dir / "report.json"
        obj_held = run(make_capture(obj_hold_dir, failure="obj_hold"), obj_hold_output)
        assert obj_held.returncode == 1, obj_held.stderr or obj_held.stdout
        obj_hold_report = json.loads(obj_hold_output.read_text())
        assert obj_hold_report["result"] == "red"
        assert any(
            row["kind"] == "world-x-delta"
            for row in obj_hold_report["obj_temporal"]["violations"]
        )

        obj_hud_dir = temp / "obj-hud"
        obj_hud_dir.mkdir()
        obj_hud_output = obj_hud_dir / "report.json"
        obj_hud = run(make_capture(obj_hud_dir, failure="obj_hud"), obj_hud_output)
        assert obj_hud.returncode == 1, obj_hud.stderr or obj_hud.stdout
        obj_hud_report = json.loads(obj_hud_output.read_text())
        assert obj_hud_report["result"] == "red"
        assert any(
            row["kind"] == "fixed-or-non-x-oam-changed"
            for row in obj_hud_report["obj_temporal"]["violations"]
        )

    print("temporal scroll cadence gate: green")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
