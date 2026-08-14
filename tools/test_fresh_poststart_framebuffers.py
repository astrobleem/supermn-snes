#!/usr/bin/env python3
"""Regression tests for the fresh post-Start visual gate's pure checks."""

from __future__ import annotations

import tempfile
import inspect
from pathlib import Path

from PIL import Image

import validate_fresh_poststart_framebuffers as gate


class FakeMemory:
    def __init__(self, reverse: bytes, vram: bytes) -> None:
        self.reverse = reverse
        self.vram = vram

    def read_memory(self, memory: str, address: int, length: int) -> bytes:
        if (memory, address, length) == ("snesWorkRam", 0xD000, 0x0180):
            return self.reverse
        if (memory, address, length) == ("snesVideoRam", 0x2000, 0x6000):
            return self.vram
        raise AssertionError((memory, address, length))


def main() -> int:
    main_source = inspect.getsource(gate.main)
    assert "advance_to(m, args.title_frame)" in main_source
    assert "m.run_frames(args.title_frame)" not in main_source
    assert '"promotion_status": "blocked"' in main_source
    assert '"cold_boot_logo_geometry"' in main_source
    assert '"player_animation_order"' in main_source
    assert gate.parse_milestone_frames("1,1250,1500", 5500) == [1, 1250, 1500]
    for invalid in ("", "1,1", "2,1", "1,nope", "1,5500"):
        try:
            gate.parse_milestone_frames(invalid, 5500)
        except ValueError:
            pass
        else:
            raise AssertionError(f"accepted invalid milestones: {invalid!r}")

    code = 2
    record = bytes((index * 13 + 7) & 0xFF for index in range(0x80))
    rom = bytearray(gate.BG_GRAPHICS_FILE_BASE + (code + 1) * 0x80)
    start = gate.BG_GRAPHICS_FILE_BASE + code * 0x80
    rom[start:start + 0x80] = record
    reverse = bytearray(0x0180)
    reverse[2:4] = code.to_bytes(2, "little")
    vram = bytearray(0x6000)
    vram[0x80:0x100] = record
    exact = gate.bg_graphics_check(FakeMemory(bytes(reverse), bytes(vram)), bytes(rom))
    assert exact["owned_slots"] == 1
    assert exact["matching_slots"] == 1
    assert exact["mismatch_count"] == 0

    vram[0x80 + 89] ^= 0xFF
    corrupt = gate.bg_graphics_check(
        FakeMemory(bytes(reverse), bytes(vram)), bytes(rom)
    )
    assert corrupt["mismatch_count"] == 1
    assert corrupt["mismatches"][0]["slot"] == 1
    assert corrupt["mismatches"][0]["first_changed_offsets"] == [89]

    transition = {
        "frame": 100,
        "relative_frame": 0,
        "halt": 0,
        "forced_blank": False,
        "main_screen_layers": 1,
        "image_metrics": {
            "playfield_black_ratio": 1.0,
            "dominant_tile_ratio": 1.0,
            "max_vertical_black_run": 256,
        },
    }
    clear = {
        "frame": 101,
        "relative_frame": 1,
        "halt": 0,
        "forced_blank": False,
        "main_screen_layers": 1,
        "image_metrics": {
            "playfield_black_ratio": 0.1,
            "dominant_tile_ratio": 0.1,
            "max_vertical_black_run": 0,
        },
    }
    assert gate.evaluate_rows([transition, clear], 1) == []
    transition_failures = gate.evaluate_rows([transition, clear], 0)
    assert [item["kind"] for item in transition_failures] == [
        "blank_playfield",
        "repeated_tile_collapse",
        "vertical_black_band",
    ]

    with tempfile.TemporaryDirectory(prefix="fresh-poststart-gate-test-") as raw:
        temp = Path(raw)
        black = temp / "black.png"
        Image.new("RGB", (256, 224), (0, 0, 0)).save(black)
        metrics = gate.image_metrics(black)
        assert metrics["playfield_black_ratio"] == 1.0
        assert metrics["dominant_tile_ratio"] == 1.0
        assert metrics["max_vertical_black_run"] == 256

        band = temp / "vertical-band.png"
        band_image = Image.new("RGB", (256, 224), (40, 80, 120))
        for x in range(96, 160):
            for y in range(24, 224):
                band_image.putpixel((x, y), (0, 0, 0))
        band_image.save(band)
        band_metrics = gate.image_metrics(band)
        assert band_metrics["max_vertical_black_run"] == 64
        band_row = dict(clear)
        band_row["image_metrics"] = band_metrics
        assert "vertical_black_band" in [
            item["kind"] for item in gate.evaluate_rows([band_row], 0)
        ]

        second = temp / "second.png"
        Image.new("RGB", (256, 224), (40, 80, 120)).save(second)
        sheet = gate.make_contact_sheet([black, second], temp / "sheet.png")
        assert Path(sheet["path"]).is_file()
        assert sheet["frames"] == ["black.png", "second.png"]
        assert sheet["size"] == [1024, 224]

    print("fresh post-Start framebuffer gate checks: green")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
