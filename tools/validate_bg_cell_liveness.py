#!/usr/bin/env python3
"""Validate BG cell liveness and persistent hash/free-list invariants.

The production reclaimer needs only the set of physical BG tile slots still
referenced by the retained 64x32 SNES tilemap.  Each 16x16 arcade cell owns four
quadrants.  This harness proves on idle renderer states that scanning the
precomputed top-left offset for all 512 cells produces exactly the same slot set
as scanning all 2,048 words, and that all four quadrants resolve to one slot.

This is checkpointed renderer-structure evidence, not FPS evidence.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, "/home/chad/Mesen2/python")

import mesen_mcp.session as _session

_session.validate_mesen_build = lambda *_args, **_kwargs: None
from mesen_mcp import McpSession


DEFAULT_NEXEN = Path(
    "/mnt/sdc1/Nexen-r5-20260712/"
    "bin/linux-x64/Release/linux-x64/publish/Nexen"
)
VIDEO_FILE_BASE = 0x298000
VIDEO_WRAM_OFFSET = 0x18000
VIDEO_WRAM_LENGTH = 0x3000
QUEUE_PROMOTER_WRAM_OFFSET = 0x0ED00
QUEUE_PROMOTER_LENGTH = 0x0300
QUEUE_CODE_MARK_OFFSET = 0x089D8


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--rom", type=Path, required=True)
    parser.add_argument("--state", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--nexen", type=Path, default=DEFAULT_NEXEN)
    parser.add_argument("--port", type=int, default=7973)
    parser.add_argument("--frames", type=int, default=1800)
    parser.add_argument("--step-frames", type=int, default=20)
    parser.add_argument(
        "--input-buttons",
        type=lambda value: int(value, 0),
        default=McpSession.BTN_RIGHT | McpSession.BTN_B,
    )
    parser.add_argument("--refresh-video-mirror", action="store_true")
    parser.add_argument(
        "--bg-hash-multiplier",
        type=lambda value: int(value, 0),
        default=1,
        help=(
            "Odd 9-bit BG hash multiplier used by --rom (default: legacy 1). "
            "With --refresh-video-mirror, rebuild the checkpoint hash in place."
        ),
    )
    return parser.parse_args()


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def expected_offsets() -> list[int]:
    offsets = []
    for column in range(16):
        for row in range(32):
            raw_x = column * 8 + (row & 1) * 4
            offsets.append(
                (row & ~1) * 64
                + (raw_x & 0x3F)
                + (0x0800 if raw_x & 0x40 else 0)
            )
    return offsets


def words(data: bytes) -> list[int]:
    return [
        int.from_bytes(data[index : index + 2], "little")
        for index in range(0, len(data), 2)
    ]


def slot(word: int) -> int:
    return (word & 0x03FF) >> 2


def arcade_code(word: int) -> int:
    return (((word & 0x00FF) << 8) | (word >> 8)) & 0x3FFF


def rebuild_bg_hash(m: McpSession, multiplier: int) -> dict[str, Any]:
    raw_codes = m.read_memory("snesWorkRam", 0xA000, 0x0400)
    raw_slots = m.read_memory("snesWorkRam", 0xA400, 0x0400)
    codes = words(raw_codes)
    slots = words(raw_slots)
    active = [
        (code, slots[index])
        for index, code in enumerate(codes)
        if code not in (0x0000, 0xFFFF)
    ]
    if len({code for code, _slot in active}) != len(active):
        raise RuntimeError("checkpoint BG hash contains duplicate live codes")

    rebuilt_codes = bytearray(0x0400)
    rebuilt_slots = bytearray(0x0400)
    maximum_probe = 0
    for code, mapped_slot in active:
        probe = (code * multiplier) & 0x01FF
        probe_count = 1
        while int.from_bytes(
            rebuilt_codes[probe * 2 : probe * 2 + 2], "little"
        ):
            probe = (probe + 1) & 0x01FF
            probe_count += 1
            if probe_count > 0x0200:
                raise RuntimeError("checkpoint BG hash rebuild overflowed")
        maximum_probe = max(maximum_probe, probe_count)
        rebuilt_codes[probe * 2 : probe * 2 + 2] = code.to_bytes(2, "little")
        rebuilt_slots[probe * 2 : probe * 2 + 2] = mapped_slot.to_bytes(
            2, "little"
        )

    m.write_memory("snesWorkRam", 0xA000, rebuilt_codes.hex())
    m.write_memory("snesWorkRam", 0xA400, rebuilt_slots.hex())
    if m.read_memory("snesWorkRam", 0xA000, 0x0400) != rebuilt_codes:
        raise RuntimeError("candidate BG code hash did not verify")
    if m.read_memory("snesWorkRam", 0xA400, 0x0400) != rebuilt_slots:
        raise RuntimeError("candidate BG slot hash did not verify")
    return {
        "multiplier": multiplier,
        "entry_count": len(active),
        "removed_tombstones": sum(code == 0xFFFF for code in codes),
        "maximum_probe": maximum_probe,
        "scope": "cross-ROM checkpoint initialization only",
    }


def inspect_hash(
    tilemap: bytes,
    table: bytes,
    raw_codes: bytes,
    hash_codes: bytes,
    hash_slots: bytes,
    reverse_codes: bytes,
    free_list: bytes,
    free_count: int,
    high_water: int,
    reverse_valid: bool,
    cache_matches_map: bool,
    hash_multiplier: int,
) -> dict[str, Any]:
    map_words = words(tilemap)
    offsets = words(table)
    raw_words = words(raw_codes)
    codes = words(hash_codes)
    slots = words(hash_slots)
    reverse = words(reverse_codes)
    entries = [(index, code, slots[index]) for index, code in enumerate(codes) if code]
    tombstones = [index for index, code, _slot in entries if code == 0xFFFF]
    live_entries = [entry for entry in entries if entry[1] != 0xFFFF]
    duplicate_codes = sorted(
        {code for _index, code, _slot in live_entries if codes.count(code) > 1}
    )
    mapped_slots = [mapped for _index, _code, mapped in live_entries]
    duplicate_slots = sorted(
        {mapped for mapped in mapped_slots if mapped_slots.count(mapped) > 1}
    )
    bad_slots = sorted({mapped for mapped in mapped_slots if mapped >= 0x00C0})
    unreachable = []
    for index, code, _mapped in live_entries:
        probe = (code * hash_multiplier) & 0x01FF
        for _ in range(0x0200):
            if probe == index:
                break
            if codes[probe] == 0:
                unreachable.append({"index": index, "code": code, "empty": probe})
                break
            probe = (probe + 1) & 0x01FF
        else:
            unreachable.append({"index": index, "code": code, "empty": None})

    bounded_free_count = min(free_count, len(free_list))
    free_slots = list(free_list[:bounded_free_count])
    free_duplicates = sorted(
        {mapped for mapped in free_slots if free_slots.count(mapped) > 1}
    )
    free_bad = sorted({mapped for mapped in free_slots if mapped >= 0x00C0})
    free_mapped_overlap = sorted(set(free_slots) & set(mapped_slots))
    tilemap_slots = {
        slot(map_words[offset // 2]) for offset in offsets
    }
    unmapped_tilemap_slots = sorted(tilemap_slots - set(mapped_slots) - {0})
    hash_by_slot = {mapped: code for _index, code, mapped in live_entries}
    reverse_mismatches = [
        {"slot": physical, "hash_code": hash_by_slot.get(physical, 0), "reverse_code": code}
        for physical, code in enumerate(reverse)
        if hash_by_slot.get(physical, 0) != code
    ]
    free_reverse_nonzero = [
        {"slot": physical, "reverse_code": reverse[physical]}
        for physical in free_slots
        if reverse[physical]
    ]

    cell_mismatches = []
    missing_codes = []
    if cache_matches_map:
        code_to_slot = {code: mapped for _index, code, mapped in live_entries}
        for cell, raw_word in enumerate(raw_words):
            code = arcade_code(raw_word)
            if not code:
                continue
            mapped = code_to_slot.get(code)
            if mapped is None:
                if len(missing_codes) < 32:
                    missing_codes.append({"cell": cell, "code": code})
                continue
            observed = slot(map_words[offsets[cell] // 2])
            if observed != mapped and len(cell_mismatches) < 32:
                cell_mismatches.append(
                    {
                        "cell": cell,
                        "code": code,
                        "hash_slot": mapped,
                        "tilemap_slot": observed,
                    }
                )

    green = (
        not tombstones
        and not duplicate_codes
        and not duplicate_slots
        and not bad_slots
        and not unreachable
        and free_count <= len(free_list)
        and not free_duplicates
        and not free_bad
        and not free_mapped_overlap
        and not unmapped_tilemap_slots
        and (not reverse_valid or (not reverse_mismatches and not free_reverse_nonzero))
        and high_water <= 0x00C0
    )
    return {
        "cache_matches_map": cache_matches_map,
        "hash_multiplier": hash_multiplier,
        "entry_count": len(live_entries),
        "tombstones": tombstones,
        "duplicate_codes": duplicate_codes,
        "duplicate_slots": duplicate_slots,
        "bad_slots": bad_slots,
        "unreachable_entries": unreachable[:32],
        "free_count": free_count,
        "free_duplicates": free_duplicates,
        "free_bad_slots": free_bad,
        "free_mapped_overlap": free_mapped_overlap,
        "unmapped_tilemap_slots": unmapped_tilemap_slots,
        "reverse_mismatches": reverse_mismatches[:32],
        "free_reverse_nonzero": free_reverse_nonzero[:32],
        "reverse_valid": reverse_valid,
        "high_water": high_water,
        "raw_semantic_observation_only": True,
        "missing_visible_codes": missing_codes,
        "visible_cell_mismatches": cell_mismatches,
        "green": green,
    }


def inspect_map(tilemap: bytes, table: bytes) -> dict[str, Any]:
    map_words = words(tilemap)
    observed_offsets = words(table)
    expected = expected_offsets()
    coverage = []
    quadrant_mismatches = []
    top_left_slots = []
    for cell, offset in enumerate(observed_offsets):
        indices = (offset, offset + 2, offset + 0x40, offset + 0x42)
        coverage.extend(indices)
        cell_slots = [slot(map_words[index // 2]) for index in indices]
        top_left_slots.append(cell_slots[0])
        if len(set(cell_slots)) != 1 and len(quadrant_mismatches) < 32:
            quadrant_mismatches.append(
                {"cell": cell, "offsets": indices, "slots": cell_slots}
            )
    full_live = sorted({slot(word) for word in map_words})
    cell_live = sorted(set(top_left_slots))
    expected_coverage = list(range(0, 0x1000, 2))
    return {
        "table_matches_expected": observed_offsets == expected,
        "coverage_exact": sorted(coverage) == expected_coverage,
        "quadrants_share_slot": not quadrant_mismatches,
        "quadrant_mismatches": quadrant_mismatches,
        "full_live_slots": full_live,
        "cell_live_slots": cell_live,
        "live_sets_match": full_live == cell_live,
        "green": (
            observed_offsets == expected
            and sorted(coverage) == expected_coverage
            and not quadrant_mismatches
            and full_live == cell_live
        ),
    }


def main() -> int:
    args = parse_args()
    for path in (args.rom, args.state, args.nexen):
        if not path.is_file():
            raise SystemExit(f"missing input: {path}")
    if args.output.exists():
        raise SystemExit(f"refusing existing output: {args.output}")
    if not 1 <= args.bg_hash_multiplier <= 0x01FF or not (
        args.bg_hash_multiplier & 1
    ):
        raise SystemExit("--bg-hash-multiplier must be odd and in 1..511")
    args.output.mkdir(parents=True)

    samples = []
    busy_samples = 0
    bg_hash_intervention: dict[str, Any] | None = None
    with McpSession(
        rom=args.rom.resolve(),
        mesen=args.nexen.resolve(),
        cwd=ROOT,
        port=args.port,
        boot_wait=6.0,
        socket_timeout=300.0,
        stderr_log=args.output / "nexen.stderr.log",
    ) as m:
        m.pause()
        m.load_state(args.state.resolve())
        m.pause()
        if args.refresh_video_mirror:
            mirror = args.rom.read_bytes()[
                VIDEO_FILE_BASE : VIDEO_FILE_BASE + VIDEO_WRAM_LENGTH
            ]
            m.write_memory("snesWorkRam", VIDEO_WRAM_OFFSET, mirror.hex())
            if m.read_memory(
                "snesWorkRam", VIDEO_WRAM_OFFSET, VIDEO_WRAM_LENGTH
            ) != mirror:
                raise RuntimeError("candidate video WRAM mirror did not verify")
            # Force the candidate's production lazy installer to prove itself.
            # Pre-installing the code here would mask an invalid queue path.
            m.write_memory("snesWorkRam", QUEUE_CODE_MARK_OFFSET, "0000")
            m.write_memory(
                "snesWorkRam",
                QUEUE_PROMOTER_WRAM_OFFSET,
                bytes(QUEUE_PROMOTER_LENGTH).hex(),
            )
            if args.bg_hash_multiplier != 1:
                bg_hash_intervention = rebuild_bg_hash(
                    m, args.bg_hash_multiplier
                )
        m.tool(
            "set_input",
            {"port": 0, "buttons": args.input_buttons, "hold": True},
        )
        advanced = 0
        while advanced < args.frames:
            count = min(args.step_frames, args.frames - advanced)
            run = m.run_frames(count)
            delta = int(run.get("framesAdvanced", 0))
            if delta <= 0:
                raise RuntimeError(f"no frame progress: {run!r}")
            advanced += delta
            busy = int.from_bytes(
                m.read_memory("snesWorkRam", 0x899C, 2), "little"
            )
            if busy:
                busy_samples += 1
                continue
            tilemap = bytes(m.read_memory("snesWorkRam", 0x9000, 0x1000))
            table = bytes(m.read_memory("snesWorkRam", 0x7500, 0x0400))
            result = inspect_map(tilemap, table)
            cache_generation = int.from_bytes(
                m.read_memory("snesWorkRam", 0x899A, 2), "little"
            )
            rendered_generation = int.from_bytes(
                m.read_memory("snesWorkRam", 0x89A4, 2), "little"
            )
            hash_result = inspect_hash(
                tilemap,
                table,
                bytes(m.read_memory("snesWorkRam", 0x2000, 0x0400)),
                bytes(m.read_memory("snesWorkRam", 0xA000, 0x0400)),
                bytes(m.read_memory("snesWorkRam", 0xA400, 0x0400)),
                bytes(m.read_memory("snesWorkRam", 0xD000, 0x0180)),
                bytes(m.read_memory("snesWorkRam", 0x7C00, 0x00C0)),
                int.from_bytes(
                    m.read_memory("snesWorkRam", 0x89C2, 2), "little"
                ),
                int.from_bytes(m.read_memory("snesWorkRam", 0x00DC, 2), "little"),
                int.from_bytes(
                    m.read_memory("snesWorkRam", 0x89D0, 2), "little"
                )
                == 0xB7C4,
                cache_generation == rendered_generation and not (cache_generation & 1),
                args.bg_hash_multiplier,
            )
            result["hash"] = hash_result
            result["green"] = result["green"] and hash_result["green"]
            result.update(
                {
                    "frame": int(m.get_state()["frameCount"]),
                    "tick": int.from_bytes(
                        m.read_memory("Sa1Memory", 0x0760, 2), "little"
                    ),
                }
            )
            samples.append(result)

    result = {
        "scope": "checkpointed BG liveness/hash/free-list invariants; not FPS",
        "rom": str(args.rom),
        "rom_sha256": sha256(args.rom),
        "state": str(args.state),
        "state_sha256": sha256(args.state),
        "nexen_sha256": sha256(args.nexen),
        "frames": args.frames,
        "step_frames": args.step_frames,
        "input_buttons": args.input_buttons,
        "video_mirror_intervention": args.refresh_video_mirror,
        "bg_hash_multiplier": args.bg_hash_multiplier,
        "bg_hash_intervention": bg_hash_intervention,
        "idle_sample_count": len(samples),
        "busy_sample_count": busy_samples,
        "green_count": sum(sample["green"] for sample in samples),
        "result": "green" if samples and all(sample["green"] for sample in samples) else "red",
        "samples": samples,
    }
    target = args.output / "results.json"
    target.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
    print(
        json.dumps(
            {
                "result": result["result"],
                "idle_sample_count": result["idle_sample_count"],
                "busy_sample_count": result["busy_sample_count"],
                "green_count": result["green_count"],
                "results": str(target),
            },
            sort_keys=True,
        ),
        flush=True,
    )
    return 0 if result["result"] == "green" else 1


if __name__ == "__main__":
    raise SystemExit(main())
