#!/usr/bin/env python3
"""Render and compare the complete narrow-screen X1 scene sequence.

The raw B0/D0/E0 shadows are first rendered back to the 384x240 arcade image.
Only an exact MAME reconstruction is permitted to act as the source oracle.
The same logical layers are then rendered with the SNES crop, gameplay-Y, and
top-HUD placement transforms and compared over all 256x224 pixels.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

from PIL import Image, ImageChops

from gameplay_acceptance_contract import gate, valid_sha256
from validate_paced_obj_sources import packed_x_word


MAME_SIZE = (384, 240)
SNES_SIZE = (256, 224)
XOFF = [x if x < 8 else 256 + x - 8 for x in range(16)]
YOFF = [y * 32 if y < 8 else 512 + (y - 8) * 32 for y in range(16)]
PLANE = [0, 8, 16, 24]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--mame-summary", type=Path, required=True)
    parser.add_argument("--gfx", type=Path, default=Path("tools/mame-trace/gfx1.bin"))
    parser.add_argument("--output", type=Path, required=True)
    return parser.parse_args()


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def be16(data: bytes, offset: int) -> int:
    return int.from_bytes(data[offset : offset + 2], "big")


class X1Renderer:
    def __init__(self, gfx: bytes):
        self.gfx = gfx
        self.tiles: dict[int, list[list[int]]] = {}

    def tile(self, code: int) -> list[list[int]]:
        if code in self.tiles:
            return self.tiles[code]
        output = [[0 for _x in range(16)] for _y in range(16)]
        base = code * 1024
        for y in range(16):
            for x in range(16):
                bit_base = base + YOFF[y] + XOFF[x]
                value = 0
                for plane, plane_offset in enumerate(PLANE):
                    bit = bit_base + plane_offset
                    value |= ((self.gfx[bit >> 3] >> (7 - (bit & 7))) & 1) << (3 - plane)
                output[y][x] = value
        self.tiles[code] = output
        return output

    def blit(
        self,
        frame: Image.Image,
        palette: list[tuple[int, int, int]],
        code: int,
        color_bank: int,
        flip_x: bool,
        flip_y: bool,
        x: int,
        y: int,
        *,
        wrap_x: bool = False,
        wrap_y: bool = False,
    ) -> None:
        tile = self.tile(code)
        origins = [(x, y)]
        if wrap_x:
            origins.append((x - 512, y))
        if wrap_y:
            origins.append((x, y - 256))
            if wrap_x:
                origins.append((x - 512, y - 256))
        for origin_x, origin_y in origins:
            for tile_y in range(16):
                output_y = origin_y + tile_y
                if not 0 <= output_y < frame.height:
                    continue
                source_y = 15 - tile_y if flip_y else tile_y
                for tile_x in range(16):
                    output_x = origin_x + tile_x
                    if not 0 <= output_x < frame.width:
                        continue
                    source_x = 15 - tile_x if flip_x else tile_x
                    index = tile[source_y][source_x]
                    if index:
                        frame.putpixel(
                            (output_x, output_y),
                            palette[color_bank * 16 + index],
                        )

    def layers(
        self, b0: bytes, d0: bytes, e0: bytes
    ) -> tuple[Image.Image, list[tuple[int, int, int]], list[tuple[int, int, int]]]:
        palette: list[tuple[int, int, int]] = []
        for offset in range(0, len(b0), 2):
            value = be16(b0, offset)
            red, green, blue = (value >> 10) & 31, (value >> 5) & 31, value & 31
            palette.append((
                (red << 3) | (red >> 2),
                (green << 3) | (green >> 2),
                (blue << 3) | (blue >> 2),
            ))

        background = Image.new("RGB", MAME_SIZE, palette[0x1F0])
        control = [be16(d0, 0x600 + 2 * index) for index in range(4)]
        control0, control2, control3 = control[0], control[1], control[3]
        column_count = control2 & 15
        if column_count == 1:
            column_count = 16
        bank = 0x1000 if ((control2 ^ ((~control2) << 1)) & 0x40) else 0
        start_column = (4 if control0 & 1 else 0) + (8 if control0 & 2 else 0)
        upper = control[2] + control[3] * 256
        for column in range(column_count):
            scroll_x = d0[2 * (0x200 + column * 0x10 + 4) + 1]
            scroll_y = d0[2 * (0x200 + column * 0x10) + 1]
            for offset in range(0x20):
                source = ((column + start_column) & 15) * 32 + offset
                code_word = be16(e0, 2 * (source + 0x400 + bank))
                color_word = be16(e0, 2 * (source + 0x600 + bank))
                x = scroll_x + (offset & 1) * 16
                y = 1 - scroll_y + (offset // 2) * 16
                if upper & (1 << column):
                    x -= 256
                self.blit(
                    background,
                    palette,
                    code_word & 0x3FFF,
                    (color_word >> 11) & 31,
                    bool(code_word & 0x8000),
                    bool(code_word & 0x4000),
                    x & 0x1FF,
                    y & 0xFF,
                    wrap_x=True,
                    wrap_y=True,
                )

        records: list[tuple[int, int, int]] = []
        for offset in range(0, 0x400, 2):
            code_word = be16(e0, offset)
            if code_word == 0xFFFF or code_word & 0x3FFF == 0:
                continue
            sy = d0[offset + 1]
            x_color = be16(e0, 0x400 + offset)
            records.append((offset, sy, code_word | (x_color << 16)))
        return background, records, palette

    def render_raw(self, b0: bytes, d0: bytes, e0: bytes) -> Image.Image:
        background, records, palette = self.layers(b0, d0, e0)
        frame = background.copy()
        for _offset, sy, combined in reversed(records):
            code_word, x_color = combined & 0xFFFF, combined >> 16
            if not 0 < sy < 0xF3:
                continue
            x = (x_color & 0xFF) - (x_color & 0x100)
            if not -16 < x < 384:
                continue
            y = 240 - ((sy + 14) & 0xFF)
            self.blit(frame, palette, code_word & 0x3FFF, (x_color >> 11) & 31,
                      bool(code_word & 0x8000), bool(code_word & 0x4000), x & 0x1FF, y,
                      wrap_x=True, wrap_y=True)
        return frame

    def render_snes(self, b0: bytes, d0: bytes, e0: bytes) -> Image.Image:
        background, records, palette = self.layers(b0, d0, e0)
        frame = background.crop((64, 1, 320, 225))
        accepted: list[tuple[int, int, int, int]] = []
        for offset, sy, combined in records:
            code_word, x_color = combined & 0xFFFF, combined >> 16
            if not 0 < sy < 0xF3:
                continue
            packed_x = packed_x_word(sy, x_color, code_word, source_offset=offset)
            if packed_x is None:
                continue
            accepted.append((sy, code_word, x_color, packed_x))
            if len(accepted) == 128:
                break
        for sy, code_word, x_color, packed_x in reversed(accepted):
            x = (packed_x & 0x1FF) - 64
            y = ((0x1EA if sy == 0xE2 or sy >= 0xF0 else 0xE9) - sy) & 0xFF
            self.blit(frame, palette, code_word & 0x3FFF, (x_color >> 11) & 31,
                      bool(code_word & 0x8000), bool(code_word & 0x4000), x, y)
        return frame


def changed(left: Image.Image, right: Image.Image) -> int:
    return sum(pixel != (0, 0, 0) for pixel in ImageChops.difference(left, right).getdata())


def main() -> int:
    args = parse_args()
    manifest = json.loads(args.manifest.read_text(encoding="utf-8"))
    summary = json.loads(args.mame_summary.read_text(encoding="utf-8"))
    captures = {int(row["tick"]): row for row in summary["captures"]}
    renderer = X1Renderer(args.gfx.read_bytes())
    args.output.mkdir(parents=True, exist_ok=False)
    reports = []
    for row in manifest["frames"]:
        tick = int(row["game_tick"])
        capture = captures[tick]
        shadows = capture["video_shadows"]
        loaded = {}
        for label in ("b0", "d0", "e0"):
            path = Path(shadows[label]["path"])
            if sha256(path) != shadows[label]["sha256"]:
                raise SystemExit(f"shadow hash mismatch: {path}")
            loaded[label] = path.read_bytes()
        raw = renderer.render_raw(loaded["b0"], loaded["d0"], loaded["e0"])
        transformed = renderer.render_snes(loaded["b0"], loaded["d0"], loaded["e0"])
        mame = Image.open(Path(capture["snapshot"]["path"])).convert("RGB")
        snes = Image.open(Path(row["snes"])).convert("RGB")
        raw_changed = changed(raw, mame)
        transformed_changed = changed(transformed, snes)
        reports.append({"game_tick": tick, "raw_mame_changed_pixels": raw_changed,
                        "transformed_snes_changed_pixels": transformed_changed,
                        "result": "green" if raw_changed == 0 and transformed_changed == 0 else "red"})
        if raw_changed or transformed_changed:
            raw.save(args.output / f"tick-{tick:06d}.raw-render.png")
            transformed.save(args.output / f"tick-{tick:06d}.transformed-render.png")
    failures = [row for row in reports if row["result"] == "red"]
    coverage = manifest.get("coverage")
    rom_sha256 = manifest.get("rom_sha256")
    ready = valid_sha256(rom_sha256) and bool(coverage and coverage.get("complete"))
    result = "green" if ready and not failures else "red"
    report = {"schema": 1,
              "scope": "complete software-rendered X1 composite after SNES crop and HUD/OBJ transforms",
              "rom_sha256": rom_sha256, "coverage": coverage,
              "summary": {"frames": len(reports), "red_frames": len(failures),
                          "first_failure": failures[0] if failures else None, "result": result},
              "frames": reports,
              "provenance": {"manifest": str(args.manifest.resolve()),
                             "manifest_sha256": sha256(args.manifest),
                             "mame_summary": str(args.mame_summary.resolve()),
                             "mame_summary_sha256": sha256(args.mame_summary),
                             "gfx": str(args.gfx.resolve()), "gfx_sha256": sha256(args.gfx)},
              "acceptance_gate": gate("aligned_transformed_composite_oracle",
                                      result if ready else "unknown",
                                      rom_sha256 if valid_sha256(rom_sha256) else None,
                                      coverage if ready else None,
                                      authority="software_x1_exact_mame_then_transformed_composite" if ready else "none")}
    (args.output / "report.json").write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(report["summary"], sort_keys=True))
    return 0 if result == "green" else 1


if __name__ == "__main__":
    raise SystemExit(main())
