#!/usr/bin/env python3
"""Inspect BG map/cache ownership in one paused legacy-Mesen checkpoint.

This is a read-only checkpoint structural diagnostic.  It uses the same
emulator that created the state; it does not advance a frame, migrate memory,
or claim exact MAME pixel authority.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
sys.path.insert(0, "/home/chad/Mesen2/python")

import capture_mesen211_transitions as capture  # noqa: E402
from validate_bg_cell_liveness import (  # noqa: E402
    arcade_code,
    inspect_hash,
    inspect_map,
    slot,
    words,
)
import mesen_mcp.session as _session  # noqa: E402

_session.validate_mesen_build = lambda *_args, **_kwargs: None
from mesen_mcp import McpSession  # noqa: E402


DEFAULT_MESEN = Path("/home/chad/Mesen2/bin/linux-x64/Release/Mesen")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--rom", type=Path, required=True)
    parser.add_argument("--state", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--emulator", type=Path, default=DEFAULT_MESEN)
    parser.add_argument("--port", type=int, default=43310)
    parser.add_argument(
        "--refresh-video-mirror",
        action="store_true",
        help=(
            "diagnostic intervention: replace serialized $7F:8000-$AFFF with "
            "the selected ROM's renderer mirror before inspecting"
        ),
    )
    return parser.parse_args()


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def expected_offsets_for_layout(kind: int, column_map: bytes) -> list[int]:
    if len(column_map) != 16:
        raise ValueError("BG column map must contain 16 bytes")
    offsets = []
    for column in range(16):
        physical = column if kind >= 0xFFFE else column_map[column]
        for row in range(32):
            raw_x = physical * 8 + (row & 1) * 4
            offsets.append(
                (row & ~1) * 64
                + (raw_x & 0x3F)
                + (0x0800 if raw_x & 0x40 else 0)
            )
    return offsets


def main() -> int:
    args = parse_args()
    for path in (args.rom, args.state, args.emulator):
        if not path.is_file():
            raise FileNotFoundError(path)
    output = args.output.resolve()
    if output.exists():
        raise SystemExit(f"refusing existing output: {output}")
    output.mkdir(parents=True)
    capture.configure_dotnet8()

    with McpSession(
        rom=args.rom.resolve(),
        mesen=args.emulator.resolve(),
        cwd=ROOT,
        port=args.port,
        boot_wait=6.0,
        socket_timeout=120.0,
        stderr_log=output / "emulator.stderr.log",
    ) as m:
        m.pause()
        m.load_state(args.state.resolve())
        m.pause()
        runtime_memory_writes: list[dict[str, object]] = []
        if args.refresh_video_mirror:
            mirror = args.rom.read_bytes()[0x298000:0x29B000]
            if len(mirror) != 0x3000:
                raise RuntimeError("selected ROM lacks the complete video mirror")
            m.write_memory("snesWorkRam", 0x18000, mirror.hex())
            observed = bytes(m.read_memory("snesWorkRam", 0x18000, 0x3000))
            if observed != mirror:
                raise RuntimeError("video mirror intervention did not verify")
            runtime_memory_writes.append(
                {
                    "region": "snesWorkRam $18000-$1AFFF",
                    "length": len(mirror),
                    "sha256": hashlib.sha256(mirror).hexdigest(),
                    "reason": "selected-ROM renderer-mirror diagnostic refresh",
                }
            )
        boundary = capture.snapshot(m)
        tilemap = bytes(m.read_memory("snesWorkRam", 0x9000, 0x1000))
        table = bytes(m.read_memory("snesWorkRam", 0x7500, 0x0400))
        raw_codes = bytes(m.read_memory("snesWorkRam", 0x2000, 0x0400))
        raw_colors = bytes(m.read_memory("snesWorkRam", 0x2400, 0x0400))
        palette_map = bytes(m.read_memory("snesWorkRam", 0x8940, 0x0020))
        hash_codes = bytes(m.read_memory("snesWorkRam", 0xA000, 0x0400))
        hash_slots = bytes(m.read_memory("snesWorkRam", 0xA400, 0x0400))
        reverse_codes = bytes(m.read_memory("snesWorkRam", 0xD000, 0x0180))
        vram_bg_tiles = bytes(m.read_memory("snesVideoRam", 0x2000, 0x6000))
        free_list = bytes(m.read_memory("snesWorkRam", 0x7C00, 0x00C0))
        free_count = int.from_bytes(
            m.read_memory("snesWorkRam", 0x89C2, 2), "little"
        )
        high_water = int.from_bytes(
            m.read_memory("snesWorkRam", 0x00DC, 2), "little"
        )
        reverse_valid = (
            int.from_bytes(m.read_memory("snesWorkRam", 0x89D0, 2), "little")
            == 0xB7C5
        )

    map_result = inspect_map(tilemap, table)
    generations = (
        boundary["snapshot_generation"],
        boundary["direct_generation"],
        boundary["rendered_generation"],
    )
    cache_matches_map = (
        boundary["renderer_busy"] == 0
        and boundary["render_queue_primary"] == 0
        and boundary["render_queue_secondary"] == 0
        and len(set(generations)) == 1
        and not (boundary["snapshot_generation"] & 1)
    )
    hash_result = inspect_hash(
        tilemap,
        table,
        raw_codes,
        hash_codes,
        hash_slots,
        reverse_codes,
        free_list,
        free_count,
        high_water,
        reverse_valid,
        cache_matches_map,
        3,
    )

    map_words = words(tilemap)
    offsets = words(table)
    column_map = bytes.fromhex(boundary["bg_column_map"])
    expected_offsets = expected_offsets_for_layout(
        boundary["bg_column_kind"], column_map
    )
    layout_table_matches = offsets == expected_offsets
    raw_words = words(raw_codes)
    raw_color_words = words(raw_colors)
    reverse = words(reverse_codes)
    rom_bytes = args.rom.read_bytes()
    occupied = 0
    ownership_ok = 0
    ownership_bad: list[dict[str, int]] = []
    stale_empty: list[dict[str, int]] = []
    occupied_codes: set[int] = set()
    occupied_slots: set[int] = set()
    final_target_claim: dict[int, int] = {}
    occupied_targets = {
        offsets[cell]
        for cell, raw_word in enumerate(raw_words)
        if arcade_code(raw_word) != 0
    }
    for cell, raw_word in enumerate(raw_words):
        code = arcade_code(raw_word)
        physical = slot(map_words[offsets[cell] // 2])
        if code == 0:
            # Dynamic X1 layouts may deliberately overlap an empty source
            # column with an occupied column.  The empty cell does not erase
            # the other source's target, so only an unclaimed nonblank target
            # is stale.
            if physical != 0 and offsets[cell] not in occupied_targets:
                stale_empty.append({"cell": cell, "slot": physical})
            continue
        occupied += 1
        final_target_claim[offsets[cell]] = cell
        occupied_codes.add(code)
    shadowed_occupied = occupied - len(final_target_claim)
    for target, cell in final_target_claim.items():
        code = arcade_code(raw_words[cell])
        physical = slot(map_words[target // 2])
        occupied_slots.add(physical)
        owner = reverse[physical] if physical < len(reverse) else -1
        if physical != 0 and owner == code:
            ownership_ok += 1
        elif len(ownership_bad) < 64:
            ownership_bad.append(
                {"cell": cell, "code": code, "slot": physical, "owner": owner}
            )

    palette_missing: list[dict[str, int]] = []
    palette_mismatches: list[dict[str, int]] = []
    palette_ok = 0
    for target, cell in final_target_claim.items():
        color = raw_color_words[cell]
        arcade_bank = (((color & 0x00FF) << 8) | (color >> 8)) >> 11 & 0x1F
        expected_slot = palette_map[arcade_bank]
        observed_slot = (map_words[target // 2] >> 10) & 0x07
        if expected_slot == 0xFF:
            if len(palette_missing) < 64:
                palette_missing.append({"cell": cell, "bank": arcade_bank})
        elif expected_slot != observed_slot:
            if len(palette_mismatches) < 64:
                palette_mismatches.append(
                    {
                        "cell": cell,
                        "bank": arcade_bank,
                        "expected_slot": expected_slot,
                        "observed_slot": observed_slot,
                    }
                )
        else:
            palette_ok += 1

    graphics_ok = 0
    graphics_mismatches: list[dict[str, object]] = []
    graphics_region_start = 0x090000
    graphics_record_count = max(
        0, (len(rom_bytes) - graphics_region_start) // 0x80
    )
    for physical, code in enumerate(reverse):
        if physical == 0 or code == 0:
            continue
        source_start = 0x090000 + code * 0x80
        expected = rom_bytes[source_start : source_start + 0x80]
        observed = vram_bg_tiles[physical * 0x80 : (physical + 1) * 0x80]
        if len(expected) == 0x80 and observed == expected:
            graphics_ok += 1
        elif len(graphics_mismatches) < 64:
            exact_matches = [
                candidate
                for candidate in range(graphics_record_count)
                if rom_bytes[
                    graphics_region_start + candidate * 0x80:
                    graphics_region_start + (candidate + 1) * 0x80
                ]
                == observed
            ]
            mismatch_offsets = [
                index
                for index, (left, right) in enumerate(zip(expected, observed))
                if left != right
            ]
            observed_segment_matches = {}
            for segment_start in range(0, 0x80, 0x20):
                segment = observed[segment_start:segment_start + 0x20]
                observed_segment_matches[f"{segment_start:02x}-{segment_start + 0x1f:02x}"] = [
                    candidate
                    for candidate in range(graphics_record_count)
                    if rom_bytes[
                        graphics_region_start + candidate * 0x80 + segment_start:
                        graphics_region_start + candidate * 0x80 + segment_start + 0x20
                    ]
                    == segment
                ][:64]
            expected_path = output / f"slot-{physical:03d}-expected.bin"
            observed_path = output / f"slot-{physical:03d}-observed.bin"
            expected_path.write_bytes(expected)
            observed_path.write_bytes(observed)
            graphics_mismatches.append(
                {
                    "slot": physical,
                    "code": code,
                    "expected_sha256": hashlib.sha256(expected).hexdigest(),
                    "observed_sha256": hashlib.sha256(observed).hexdigest(),
                    "observed_exact_rom_codes": exact_matches[:64],
                    "observed_segment_rom_codes": observed_segment_matches,
                    "changed_byte_count": len(mismatch_offsets),
                    "first_changed_offsets": mismatch_offsets[:64],
                    "expected_artifact": str(expected_path),
                    "observed_artifact": str(observed_path),
                    "source_cells": [
                        cell
                        for cell, raw_word in enumerate(raw_words)
                        if arcade_code(raw_word) == code
                    ],
                }
            )

    result = {
        "schema": 1,
        "scope": (
            "read-only legacy-Mesen checkpoint BG cache/map/reverse-owner "
            "inspection; not gameplay, exact MAME pixels, or temporal conservation"
        ),
        "rom": str(args.rom.resolve()),
        "rom_sha256": sha256(args.rom),
        "state": str(args.state.resolve()),
        "state_sha256": sha256(args.state),
        "emulator": str(args.emulator.resolve()),
        "runtime_memory_writes": runtime_memory_writes,
        "boundary": boundary,
        "source_cells": len(raw_words),
        "occupied_cells": occupied,
        "shadowed_occupied_cells": shadowed_occupied,
        "final_occupied_targets": len(final_target_claim),
        "unique_codes": len(occupied_codes),
        "unique_slots": len(occupied_slots),
        "ownership_ok": ownership_ok,
        "ownership_bad_count": len(final_target_claim) - ownership_ok,
        "ownership_bad": ownership_bad,
        "palette_map": palette_map.hex(),
        "palette_target_ok": palette_ok,
        "palette_missing_count": len(palette_missing),
        "palette_missing": palette_missing,
        "palette_mismatch_count": len(palette_mismatches),
        "palette_mismatches": palette_mismatches,
        "graphics_owner_count": sum(1 for code in reverse[1:] if code),
        "graphics_ok": graphics_ok,
        "graphics_mismatch_count": len(graphics_mismatches),
        "graphics_mismatches": graphics_mismatches,
        "stale_empty_count": len(stale_empty),
        "stale_empty": stale_empty[:64],
        "high_water": high_water,
        "layout_table_matches": layout_table_matches,
        "expected_layout_offsets_sha256": hashlib.sha256(
            b"".join(value.to_bytes(2, "little") for value in expected_offsets)
        ).hexdigest(),
        "map": map_result,
        "hash": hash_result,
        "green": (
            cache_matches_map
            and layout_table_matches
            and len(final_target_claim) == ownership_ok
            and not stale_empty
            and not palette_missing
            and not palette_mismatches
            and not graphics_mismatches
            and map_result["quadrants_share_slot"]
            and map_result["live_sets_match"]
            and hash_result["green"]
        ),
        "acceptance_authority": "checkpoint structure only",
    }
    target = output / "results.json"
    target.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
    print(
        json.dumps(
            {
                "green": result["green"],
                "occupied_cells": occupied,
                "shadowed_occupied_cells": shadowed_occupied,
                "final_occupied_targets": len(final_target_claim),
                "ownership_ok": ownership_ok,
                "ownership_bad_count": len(final_target_claim) - ownership_ok,
                "stale_empty_count": len(stale_empty),
                "palette_missing_count": len(palette_missing),
                "palette_mismatch_count": len(palette_mismatches),
                "graphics_mismatch_count": len(graphics_mismatches),
                "unique_codes": len(occupied_codes),
                "unique_slots": len(occupied_slots),
                "high_water": high_water,
                "result": str(target),
            },
            sort_keys=True,
        )
    )
    return 0 if result["green"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
