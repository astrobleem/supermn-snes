#!/usr/bin/env python3
"""Offline gate for *presented* horizontal motion in consecutive captures.

State/pixel correctness does not prove temporal continuity.  Every consecutive
video-frame transition is registered here, including frames on which the 30 Hz
game camera has not produced a new target.  This prevents a 60 Hz presentation
that alternates ``hold, jump`` from being mislabeled smooth and also rejects a
tilemap publication that cannot be explained by the camera translation.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from collections import Counter
from pathlib import Path
from typing import Any

from PIL import Image, ImageChops


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--results", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--warmup-frames", type=int, default=2)
    parser.add_argument("--minimum-source-steps", type=int, default=20)
    parser.add_argument("--crop-left", type=int, default=32)
    parser.add_argument("--crop-top", type=int, default=24)
    parser.add_argument("--crop-right", type=int, default=224)
    parser.add_argument("--crop-bottom", type=int, default=96)
    parser.add_argument("--max-registration-shift", type=int, default=18)
    parser.add_argument(
        "--max-presented-step",
        type=int,
        default=2,
        help="largest acceptable motion on one 60 Hz video transition",
    )
    parser.add_argument(
        "--max-background-mismatch",
        type=float,
        default=0.08,
        help="maximum residual changed-pixel ratio after translation",
    )
    return parser.parse_args()


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def signed8_delta(before: int, after: int) -> int:
    return ((after - before + 128) & 0xFF) - 128


def signed32_delta(before: int, after: int) -> int:
    return ((after - before + 16) & 0x1F) - 16


def signed1024_delta(before: int, after: int) -> int:
    return ((after - before + 512) & 0x3FF) - 512


def signed512_delta(before: int, after: int) -> int:
    return ((after - before + 256) & 0x1FF) - 256


def oam_x9(oam: bytes, entry: int) -> int:
    low_offset = entry * 4
    high_offset = 0x200 + entry // 4
    high_mask = 1 << ((entry & 3) * 2)
    return oam[low_offset] | (0x100 if oam[high_offset] & high_mask else 0)


def hardware_world_descriptors(oam: bytes) -> list[tuple[int, int, int, int]]:
    """Rebuild the production Y-based world list from hardware OAM."""
    result = []
    for entry in range(128):
        low_offset = entry * 4
        y = oam[low_offset + 1]
        if 0x18 <= y < 0xC8:
            result.append(
                (
                    entry,
                    low_offset,
                    entry // 4,
                    1 << ((entry & 3) * 2),
                )
            )
    return result


def screenshot_path(source_path: Path, recorded: str) -> Path:
    """Resolve a capture after evidence-preserving directory archival.

    Capture manifests retain their original absolute path.  When the whole
    capture directory has been moved, its authenticated basename beside the
    moved results file is an unambiguous fallback.
    """

    path = Path(recorded).resolve()
    if path.is_file():
        return path
    sibling = source_path.parent / path.name
    return sibling.resolve()


def best_horizontal_shift(
    before: Image.Image,
    after: Image.Image,
    limit: int,
) -> tuple[int, float]:
    width, height = before.size
    candidates: list[tuple[float, int]] = []
    for shift in range(-limit, limit + 1):
        if shift < 0:
            left = before.crop((0, 0, width + shift, height))
            right = after.crop((-shift, 0, width, height))
        elif shift > 0:
            left = before.crop((shift, 0, width, height))
            right = after.crop((0, 0, width - shift, height))
        else:
            left = before
            right = after
        histogram = ImageChops.difference(left, right).convert("L").histogram()
        changed = sum(histogram[1:])
        candidates.append((changed / (left.width * left.height), shift))
    mismatch, shift = min(candidates)
    return shift, mismatch


def main() -> int:
    args = parse_args()
    source_path = args.results.resolve()
    source = json.loads(source_path.read_text())
    captures: list[dict[str, Any]] = source["captures"]
    if len(captures) < 2:
        raise SystemExit("capture has fewer than two frames")

    failures: list[str] = []
    frame_deltas = [
        int(after["frame"]) - int(before["frame"])
        for before, after in zip(captures, captures[1:])
    ]
    if any(delta != 1 for delta in frame_deltas):
        failures.append("capture is not consecutive actual video frames")

    authenticated = 0
    images: list[Path] = []
    for row in captures:
        screenshot = row["screenshot"]
        path = screenshot_path(source_path, screenshot["path"])
        if not path.is_file() or sha256(path) != screenshot["sha256"]:
            failures.append(f"framebuffer authentication failed: {path}")
            break
        images.append(path)
        authenticated += 1

    source_steps: list[tuple[int, int]] = []
    ppu_steps: list[tuple[int, int]] = []
    # Current renderer builds explicitly publish the common modulo-32 camera
    # phase in latest_scrollx.  A raw X1 source column can jump by 64 pixels
    # when it crosses the hardware layout gap; treating that column as camera
    # truth recreates the very false discontinuity this gate must distinguish.
    # Retain the raw-column fallback for authenticated historical captures.
    source_key = (
        "latest_scrollx"
        if all("latest_scrollx" in row for row in captures)
        else (
            "live_scrollx_column4"
            if all("live_scrollx_column4" in row for row in captures)
            else "live_scrollx_column0"
        )
    )
    for index in range(max(1, args.warmup_frames + 1), len(captures)):
        before = captures[index - 1]
        after = captures[index]
        if int(after[source_key]) != int(before[source_key]):
            source_steps.append(
                (
                    index,
                    signed8_delta(
                        int(before[source_key]),
                        int(after[source_key]),
                    ),
                )
            )
        if int(after["bg1_hscroll"]) != int(before["bg1_hscroll"]):
            ppu_steps.append(
                (
                    index,
                    signed32_delta(
                        int(before["bg1_hscroll"]),
                        int(after["bg1_hscroll"]),
                    ),
                )
            )

    source_histogram = Counter(delta for _, delta in source_steps)
    dominant_source_step = (
        source_histogram.most_common(1)[0][0] if source_histogram else None
    )
    expected_visual_shift = (
        -dominant_source_step if dominant_source_step is not None else None
    )

    if len(source_steps) < args.minimum_source_steps:
        failures.append(
            f"only {len(source_steps)} source-scroll steps; "
            f"need {args.minimum_source_steps}"
        )
    if source_steps and source_histogram[dominant_source_step] != len(source_steps):
        failures.append("source-scroll step is not stable in the measured window")
    registrations: list[dict[str, Any]] = []
    if authenticated == len(captures) and expected_visual_shift is not None:
        for index in range(max(1, args.warmup_frames + 1), len(captures)):
            before = Image.open(images[index - 1]).convert("RGB").crop(
                (
                    args.crop_left,
                    args.crop_top,
                    args.crop_right,
                    args.crop_bottom,
                )
            )
            after = Image.open(images[index]).convert("RGB").crop(
                (
                    args.crop_left,
                    args.crop_top,
                    args.crop_right,
                    args.crop_bottom,
                )
            )
            shift, mismatch = best_horizontal_shift(
                before, after, args.max_registration_shift
            )
            registrations.append(
                {
                    "capture_index": index,
                    "frame": captures[index]["frame"],
                    "best_shift": shift,
                    "mismatch_ratio": mismatch,
                }
            )
    first_motion = source_steps[0][0] if source_steps else len(captures)
    last_motion = source_steps[-1][0] if source_steps else -1
    direction = 1 if expected_visual_shift and expected_visual_shift > 0 else -1
    # A 64x32 tilemap can rotate its physical 32-pixel columns while preserving
    # the same world image.  HOFS must rebase at that exact PPU publication,
    # so its raw register delta is not itself visible motion.  The authenticated
    # framebuffer registration below remains authoritative for that transition.
    map_change_indices = {
        index
        for index in range(1, len(captures))
        if captures[index - 1].get("displayed_bg_map_sha256") is not None
        and captures[index].get("displayed_bg_map_sha256") is not None
        and captures[index - 1]["displayed_bg_map_sha256"]
        != captures[index]["displayed_bg_map_sha256"]
    }
    motion_ppu_steps = [
        (index, delta)
        for index, delta in ppu_steps
        if first_motion <= index <= last_motion
    ]
    motion_ppu_indices = {index for index, _delta in motion_ppu_steps}
    held_ppu_transitions = [
        index
        for index in range(first_motion, last_motion + 1)
        if index not in motion_ppu_indices and index not in map_change_indices
    ]
    wrong_ppu_steps = [
        {"capture_index": index, "delta_signed32": delta}
        for index, delta in motion_ppu_steps
        if index not in map_change_indices
        and (delta * direction <= 0 or abs(delta) > args.max_presented_step)
    ]
    if held_ppu_transitions:
        failures.append(
            f"PPU held on {len(held_ppu_transitions)} video transitions while "
            "the camera was moving"
        )
    if wrong_ppu_steps:
        failures.append(
            f"{len(wrong_ppu_steps)} PPU transitions exceeded the per-video "
            "step limit or reversed direction"
        )
    expected_motion_total = sum(-delta for _, delta in source_steps)
    observed_ppu_total = sum(delta for _, delta in motion_ppu_steps)

    motion_registrations = [
        row
        for row in registrations
        if first_motion <= row["capture_index"] <= last_motion
    ]
    registration_by_index = {
        int(row["capture_index"]): row for row in motion_registrations
    }
    coordinate_rebases = [
        {
            "capture_index": index,
            "frame": captures[index]["frame"],
            "ppu_delta_signed32": next(
                (delta for step_index, delta in motion_ppu_steps if step_index == index),
                0,
            ),
            "ppu_delta_signed1024": signed1024_delta(
                int(captures[index - 1]["bg1_hscroll"]),
                int(captures[index]["bg1_hscroll"]),
            ),
            "registration": registration_by_index.get(index),
        }
        for index in sorted(map_change_indices)
        if first_motion <= index <= last_motion
    ]
    held_presentations = [
        row for row in motion_registrations if row["best_shift"] == 0
    ]
    oversized_presentations = [
        row
        for row in motion_registrations
        if abs(row["best_shift"]) > args.max_presented_step
    ]
    reversed_presentations = [
        row
        for row in motion_registrations
        if row["best_shift"] * direction < 0
    ]
    discontinuities = [
        row
        for row in motion_registrations
        if row["mismatch_ratio"] > args.max_background_mismatch
    ]
    wrong_registrations = sorted(
        {
            row["capture_index"]: row
            for row in (
                held_presentations
                + oversized_presentations
                + reversed_presentations
                + discontinuities
            )
        }.values(),
        key=lambda row: row["capture_index"],
    )
    observed_visual_total = sum(
        int(row["best_shift"]) for row in motion_registrations
    )
    if abs(expected_motion_total - observed_visual_total) > args.max_presented_step:
        failures.append(
            f"framebuffers presented {observed_visual_total:+d} pixels for "
            f"{expected_motion_total:+d} pixels of source motion"
        )
    if held_presentations:
        failures.append(
            f"{len(held_presentations)} held video frames occurred while the "
            "camera was moving"
        )
    if oversized_presentations:
        failures.append(
            f"{len(oversized_presentations)} presented steps exceeded "
            f"{args.max_presented_step} pixels per video frame"
        )
    if reversed_presentations:
        failures.append(
            f"{len(reversed_presentations)} presented steps reversed camera direction"
        )
    if discontinuities:
        failures.append(
            f"{len(discontinuities)} background transitions exceeded the "
            f"{args.max_background_mismatch:.3f} post-registration mismatch limit"
        )

    # When the accepted immutable image is also the map currently displayed by
    # the PPU, its physical origin is independently reconstructible.  Source
    # column 4 contributes its physical 32-pixel slot, while the camera phase
    # and raw column-4 X were captured with that same image.  Checking the
    # absolute expression on every eligible frame prevents a cumulative/modal
    # rebase from looking smooth locally while retaining a hidden +64 offset.
    basis_required_keys = {
        "bg_column_kind",
        "bg_column_map",
        "displayed_column_map",
        "displayed_map_scrollx",
        "displayed_map_valid",
        "obj_cache_scrollx",
        "scroll_packed",
    }
    basis_checks: list[dict[str, Any]] = []
    basis_violations: list[dict[str, Any]] = []
    coordinate_checks: list[dict[str, Any]] = []
    coordinate_violations: list[dict[str, Any]] = []
    basis_schema_present = all(
        basis_required_keys <= row.keys() for row in captures
    )
    basis16_schema_present = all(
        "displayed_map_basis16" in row for row in captures
    )
    phase16_schema_present = all(
        {"obj_cache_scrollx16", "presented_scrollx16"} <= row.keys()
        for row in captures
    )

    def unwrap_sequence(key: str) -> list[int]:
        values: list[int] = []
        for row in captures:
            low = int(row[key]) & 0xFF
            if not values:
                values.append(low)
                continue
            delta = ((low - (values[-1] & 0xFF) + 0x80) & 0xFF) - 0x80
            values.append((values[-1] + delta) & 0x1FF)
        return values

    reconstructed_packet_phase = unwrap_sequence("obj_cache_scrollx")
    reconstructed_presented_phase = unwrap_sequence("presented_scrollx")
    if basis_schema_present:
        for index, row in enumerate(captures):
            if int(row["displayed_map_valid"]) != 0xA5:
                continue
            if int(row["bg_column_kind"]) >= 0xFFFE:
                continue
            if row["bg_column_map"] != row["displayed_column_map"]:
                continue
            try:
                column_map = bytes.fromhex(row["bg_column_map"])
            except (TypeError, ValueError):
                basis_violations.append(
                    {
                        "capture_index": index,
                        "frame": row["frame"],
                        "kind": "column-map-decode",
                    }
                )
                continue
            if len(column_map) != 16:
                basis_violations.append(
                    {
                        "capture_index": index,
                        "frame": row["frame"],
                        "kind": "column-map-length",
                        "bytes": len(column_map),
                    }
                )
                continue
            slot4 = column_map[4]
            phase = (
                int(row["obj_cache_scrollx16"]) & 0x1FF
                if phase16_schema_present
                else reconstructed_packet_phase[index]
            )
            raw_column4 = (int(row["scroll_packed"]) >> 8) & 0xFF
            if basis16_schema_present:
                raw_column4 |= ((int(row["bg_column_kind"]) >> 4) & 1) << 8
            basis_mask = 0x1FF if basis16_schema_present else 0xFF
            expected_basis = (
                slot4 * 32 + phase - raw_column4
            ) & basis_mask
            observed_basis = int(
                row[
                    "displayed_map_basis16"
                    if basis16_schema_present
                    else "displayed_map_scrollx"
                ]
            ) & basis_mask
            check = {
                "capture_index": index,
                "frame": row["frame"],
                "slot4": slot4,
                "paired_phase": phase,
                "paired_raw_column4": raw_column4,
                "expected_basis": expected_basis,
                "observed_basis": observed_basis,
                "basis_bits": 9 if basis16_schema_present else 8,
            }
            basis_checks.append(check)
            if observed_basis != expected_basis:
                basis_violations.append({**check, "kind": "absolute-basis"})
    if basis16_schema_present:
        for index, row in enumerate(captures):
            if int(row.get("displayed_map_valid", 0)) != 0xA5:
                continue
            presented_phase = (
                int(row["presented_scrollx16"]) & 0x1FF
                if phase16_schema_present
                else reconstructed_presented_phase[index]
            )
            basis = int(row["displayed_map_basis16"]) & 0x1FF
            expected_hscroll = (0x40 + basis - presented_phase) & 0x1FF
            observed_hscroll = int(row["bg1_hscroll"]) & 0x1FF
            check = {
                "capture_index": index,
                "frame": row["frame"],
                "displayed_basis": basis,
                "presented_phase": presented_phase,
                "expected_hscroll": expected_hscroll,
                "observed_hscroll": observed_hscroll,
                "phase_source": "captured9" if phase16_schema_present else "sequence-unwrapped8",
            }
            coordinate_checks.append(check)
            if observed_hscroll != expected_hscroll:
                coordinate_violations.append(
                    {**check, "kind": "displayed-coordinate"}
                )
    if basis_schema_present and not basis_checks:
        failures.append(
            "absolute map-basis schema was present but no displayed/accepted exact-map frame was eligible"
        )
    if basis_violations:
        failures.append(
            f"{len(basis_violations)} absolute physical-map basis violations"
        )
    if coordinate_violations:
        failures.append(
            f"{len(coordinate_violations)} nine-bit displayed-coordinate violations"
        )

    # New captures explicitly retain the immutable presentation OAM, hardware
    # OAM, and compact world-object list.  Enforce the cross-layer temporal
    # contract when that capture schema is advertised while leaving historical
    # evidence readable.  A BG-only crop can no longer certify player/crate
    # cadence: on every unchanged base sequence, each world X must move by the
    # inverse presented-camera delta and every non-world/HUD OAM field must hold.
    obj_required_keys = {
        "hardware_oam",
        "hardware_oam_sha256",
        "presentation_oam",
        "presentation_oam_sha256",
        "obj_base_scrollx",
        "obj_present_valid",
        "obj_applied_comp",
        "obj_world_count",
        "obj_dma_pending",
        "obj_base_sequence",
        "obj_dma_skips",
        "obj_world_list",
        "obj_published_sequence",
        "obj_published_base_scrollx",
        "obj_published_comp",
        "obj_published_valid",
        "obj_world_first",
        "obj_world_span",
        "obj_partial_dmas",
        "presented_scrollx",
    }
    # Fail closed whenever the capture actually contains the complete OBJ
    # schema, including historical captures made before the explicit feature
    # advertisement was added.  Otherwise an omitted top-level flag can
    # silently turn a full-composite temporal capture back into a BG-only gate.
    obj_required = bool(
        source.get("obj_temporal_capture", False)
        or source.get("provenance", {}).get("obj_temporal_capture", False)
        or all(obj_required_keys <= row.keys() for row in captures)
    )
    obj_violations: list[dict[str, Any]] = []
    obj_rows: list[dict[str, Any] | None] = []
    obj_valid_frames = 0
    for index, row in enumerate(captures):
        if not obj_required:
            obj_rows.append(None)
            continue
        missing = sorted(obj_required_keys - row.keys())
        if missing:
            obj_violations.append(
                {"capture_index": index, "frame": row["frame"], "kind": "missing", "fields": missing}
            )
            obj_rows.append(None)
            continue
        try:
            hardware = bytes.fromhex(row["hardware_oam"])
            presentation = bytes.fromhex(row["presentation_oam"])
            world_list = bytes.fromhex(row["obj_world_list"])
        except (TypeError, ValueError) as exc:
            obj_violations.append(
                {"capture_index": index, "frame": row["frame"], "kind": "decode", "error": str(exc)}
            )
            obj_rows.append(None)
            continue
        count = int(row["obj_world_count"])
        descriptors: list[tuple[int, int, int, int]] = []
        structure_ok = (
            len(hardware) == 0x220
            and len(presentation) == 0x220
            and 0 <= count <= 128
            and len(world_list) == count * 4
        )
        if len(hardware) != 0x220 or len(presentation) != 0x220:
            obj_violations.append(
                {"capture_index": index, "frame": row["frame"], "kind": "oam-length", "hardware": len(hardware), "presentation": len(presentation)}
            )
        if hashlib.sha256(hardware).hexdigest() != row["hardware_oam_sha256"]:
            obj_violations.append(
                {"capture_index": index, "frame": row["frame"], "kind": "hardware-hash"}
            )
        if hashlib.sha256(presentation).hexdigest() != row["presentation_oam_sha256"]:
            obj_violations.append(
                {"capture_index": index, "frame": row["frame"], "kind": "presentation-hash"}
            )
        pending = int(row["obj_dma_pending"])
        active_span = int(row.get("obj_active_low_span", 0x200))
        if not 0 <= active_span <= 0x200 or active_span & 3:
            obj_violations.append(
                {"capture_index": index, "frame": row["frame"], "kind": "invalid-active-span", "value": active_span}
            )
            active_span = 0x200
        if pending == 0 and int(row["obj_published_valid"]) == 0xA5:
            active_matches = hardware[:active_span] == presentation[:active_span]
            high_matches = hardware[0x200:0x220] == presentation[0x200:0x220]
            inactive_hidden = all(
                hardware[offset + 1] == 0xF0
                for offset in range(active_span, 0x200, 4)
            )
            if not active_matches or not high_matches:
                obj_violations.append(
                    {
                        "capture_index": index,
                        "frame": row["frame"],
                        "kind": "hardware-not-active-presentation",
                        "active_span": active_span,
                        "active_matches": active_matches,
                        "high_matches": high_matches,
                    }
                )
            if not inactive_hidden:
                obj_violations.append(
                    {"capture_index": index, "frame": row["frame"], "kind": "inactive-hardware-visible", "active_span": active_span}
                )
        if len(world_list) != count * 4 or count > 128:
            obj_violations.append(
                {"capture_index": index, "frame": row["frame"], "kind": "world-list-length", "count": count, "bytes": len(world_list)}
            )
        else:
            for cursor in range(0, len(world_list), 4):
                low_offset = int.from_bytes(world_list[cursor : cursor + 2], "little")
                high_index = world_list[cursor + 2]
                high_mask = world_list[cursor + 3]
                entry = low_offset // 4
                expected_mask = 1 << ((entry & 3) * 2) if entry < 128 else 0
                if (
                    low_offset & 3
                    or low_offset >= 0x200
                    or high_index != entry // 4
                    or high_mask != expected_mask
                ):
                    obj_violations.append(
                        {"capture_index": index, "frame": row["frame"], "kind": "world-descriptor", "cursor": cursor, "descriptor": world_list[cursor : cursor + 4].hex()}
                    )
                    break
                descriptors.append((entry, low_offset, high_index, high_mask))
            if len(descriptors) == count:
                expected_first = descriptors[0][1] if descriptors else 0
                expected_span = (
                    descriptors[-1][1] - expected_first + 4
                    if descriptors
                    else 0
                )
                if (
                    int(row["obj_world_first"]) != expected_first
                    or int(row["obj_world_span"]) != expected_span
                ):
                    obj_violations.append(
                        {
                            "capture_index": index,
                            "frame": row["frame"],
                            "kind": "world-span",
                            "expected_first": expected_first,
                            "observed_first": row["obj_world_first"],
                            "expected_span": expected_span,
                            "observed_span": row["obj_world_span"],
                        }
                    )
        desired = (
            int(row["obj_base_scrollx"]) - int(row["presented_scrollx"])
        ) & 0xFF
        obj_gate_active = index >= args.warmup_frames
        if obj_gate_active and int(row["obj_present_valid"]) != 0xA5:
            obj_violations.append(
                {"capture_index": index, "frame": row["frame"], "kind": "not-valid", "value": row["obj_present_valid"]}
            )
        elif obj_gate_active:
            obj_valid_frames += 1
        if obj_gate_active and int(row["obj_applied_comp"]) != desired:
            obj_violations.append(
                {"capture_index": index, "frame": row["frame"], "kind": "wrong-compensation", "expected": desired, "observed": row["obj_applied_comp"]}
            )
        if pending not in (0, 1, 2, 3):
            obj_violations.append(
                {"capture_index": index, "frame": row["frame"], "kind": "invalid-dma-state", "value": pending}
            )
        published_desired = (
            int(row["obj_published_base_scrollx"])
            - int(row["presented_scrollx"])
        ) & 0xFF
        if obj_gate_active and int(row["obj_published_valid"]) != 0xA5:
            obj_violations.append(
                {"capture_index": index, "frame": row["frame"], "kind": "hardware-not-valid", "value": row["obj_published_valid"]}
            )
        if obj_gate_active and int(row["obj_published_comp"]) != published_desired:
            obj_violations.append(
                {"capture_index": index, "frame": row["frame"], "kind": "wrong-hardware-compensation", "expected": published_desired, "observed": row["obj_published_comp"]}
            )
        obj_rows.append(
            {
                "hardware": hardware,
                "presentation": presentation,
                "descriptors": hardware_world_descriptors(hardware),
                "world_list": world_list,
                "active_span": active_span,
            }
            if structure_ok
            else None
        )

    obj_checked_transitions = 0
    if obj_required:
        for index in range(1, len(captures)):
            if index < args.warmup_frames:
                continue
            before_row = obj_rows[index - 1]
            after_row = obj_rows[index]
            before = captures[index - 1]
            after = captures[index]
            if before_row is None or after_row is None:
                continue
            if int(after["obj_dma_skips"]) > int(before["obj_dma_skips"]):
                obj_violations.append(
                    {"capture_index": index, "frame": after["frame"], "kind": "dma-skip-increased", "before": before["obj_dma_skips"], "after": after["obj_dma_skips"]}
                )
            if int(after["obj_partial_dmas"]) < int(before["obj_partial_dmas"]):
                obj_violations.append(
                    {"capture_index": index, "frame": after["frame"], "kind": "partial-dma-counter-reversed", "before": before["obj_partial_dmas"], "after": after["obj_partial_dmas"]}
                )
            if (
                int(after["obj_dma_pending"]) == 3
                or int(after["obj_published_sequence"])
                != int(before["obj_published_sequence"])
                or int(after["obj_published_valid"]) != 0xA5
                or int(before["obj_published_valid"]) != 0xA5
            ):
                continue
            obj_checked_transitions += 1
            camera_delta = signed8_delta(
                int(before["presented_scrollx"]),
                int(after["presented_scrollx"]),
            )
            expected_x_delta = -camera_delta
            before_entries = [item[0] for item in before_row["descriptors"]]
            after_entries = [item[0] for item in after_row["descriptors"]]
            if before_entries != after_entries:
                obj_violations.append(
                    {"capture_index": index, "frame": after["frame"], "kind": "hardware-world-list-changed", "before": before_entries, "after": after_entries}
                )
                continue
            for entry, low_offset, high_index, high_mask in after_row["descriptors"]:
                observed_x_delta = signed512_delta(
                    oam_x9(before_row["hardware"], entry),
                    oam_x9(after_row["hardware"], entry),
                )
                if observed_x_delta != expected_x_delta:
                    obj_violations.append(
                        {"capture_index": index, "frame": after["frame"], "kind": "world-x-delta", "entry": entry, "expected": expected_x_delta, "observed": observed_x_delta}
                    )
                    break
            normalized_before = bytearray(before_row["hardware"])
            normalized_after = bytearray(after_row["hardware"])
            for low_offset in range(before_row["active_span"], 0x200, 4):
                normalized_before[low_offset : low_offset + 4] = b"\x00" * 4
            for low_offset in range(after_row["active_span"], 0x200, 4):
                normalized_after[low_offset : low_offset + 4] = b"\x00" * 4
            for entry, low_offset, high_index, high_mask in after_row["descriptors"]:
                normalized_before[low_offset] = 0
                normalized_after[low_offset] = 0
                packed_offset = 0x200 + high_index
                normalized_before[packed_offset] &= ~high_mask
                normalized_after[packed_offset] &= ~high_mask
            if normalized_before != normalized_after:
                obj_violations.append(
                    {"capture_index": index, "frame": after["frame"], "kind": "fixed-or-non-x-oam-changed"}
                )
        obj_gated_frames = max(0, len(captures) - args.warmup_frames)
        if obj_valid_frames != obj_gated_frames:
            failures.append(
                f"OBJ presentation valid on {obj_valid_frames}/{obj_gated_frames} "
                "post-warmup captured frames"
            )
        if obj_violations:
            failures.append(
                f"{len(obj_violations)} OBJ presentation/cadence contract violations"
            )

    report = {
        "schema": 1,
        "scope": (
            "offline temporal-scroll gate over authenticated consecutive actual "
            "video frames; not fresh-boot, gameplay, performance, or MAME-pixel acceptance"
        ),
        "source_results": str(source_path),
        "source_results_sha256": sha256(source_path),
        "capture_count": len(captures),
        "authenticated_framebuffers": authenticated,
        "frame_range": [captures[0]["frame"], captures[-1]["frame"]],
        "warmup_frames": args.warmup_frames,
        "source_scroll_key": source_key,
        "source_step_count": len(source_steps),
        "source_step_histogram": dict(sorted(source_histogram.items())),
        "dominant_source_step": dominant_source_step,
        "ppu_step_count": len(ppu_steps),
        "expected_ppu_direction": direction,
        "expected_motion_total": expected_motion_total,
        "observed_ppu_motion_total": observed_ppu_total,
        "observed_visual_motion_total": observed_visual_total,
        "coordinate_rebases": coordinate_rebases,
        "held_ppu_transitions": held_ppu_transitions,
        "wrong_ppu_steps": wrong_ppu_steps,
        "expected_visual_shift": expected_visual_shift,
        "registration_count": len(registrations),
        "registration_shift_histogram": dict(
            sorted(Counter(row["best_shift"] for row in registrations).items())
        ),
        "motion_transition_count": len(motion_registrations),
        "held_presentations": held_presentations,
        "oversized_presentations": oversized_presentations,
        "reversed_presentations": reversed_presentations,
        "background_discontinuities": discontinuities,
        "max_presented_step": args.max_presented_step,
        "max_background_mismatch": args.max_background_mismatch,
        "wrong_registrations": wrong_registrations,
        "absolute_map_basis": {
            "schema_present": basis_schema_present,
            "basis_bits": 9 if basis16_schema_present else 8,
            "formula": (
                "slot4*32 + paired_phase9 - paired_raw_column4_9 (mod 512)"
                if basis16_schema_present
                else "slot4*32 + paired_phase - paired_raw_column4 (mod 256)"
            ),
            "phase_source": (
                "captured9" if phase16_schema_present else "sequence-unwrapped8"
            ),
            "checked_frames": len(basis_checks),
            "violation_count": len(basis_violations),
            "violations": basis_violations[:64],
        },
        "displayed_coordinate": {
            "schema_present": basis16_schema_present,
            "formula": "64 + displayed_basis9 - presented_phase9 (mod 512)",
            "phase_source": (
                "captured9" if phase16_schema_present else "sequence-unwrapped8"
            ),
            "checked_frames": len(coordinate_checks),
            "violation_count": len(coordinate_violations),
            "violations": coordinate_violations[:64],
        },
        "obj_temporal": {
            "required": obj_required,
            "valid_frames": obj_valid_frames,
            "checked_same-base_transitions": obj_checked_transitions,
            "partial_dma_range": (
                [
                    min(int(row["obj_partial_dmas"]) for row in captures),
                    max(int(row["obj_partial_dmas"]) for row in captures),
                ]
                if obj_required
                and all("obj_partial_dmas" in row for row in captures)
                else None
            ),
            "violation_count": len(obj_violations),
            "violations": obj_violations[:64],
        },
        "failures": failures,
        "result": "green" if not failures else "red",
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    print(
        json.dumps(
            {
                "result": report["result"],
                "source_steps": len(source_steps),
                "ppu_steps": len(ppu_steps),
                "registration_shift_histogram": report[
                    "registration_shift_histogram"
                ],
                "failures": failures,
                "report": str(args.output.resolve()),
            },
            sort_keys=True,
        )
    )
    return 0 if not failures else 1


if __name__ == "__main__":
    raise SystemExit(main())
