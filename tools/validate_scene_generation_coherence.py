#!/usr/bin/env python3
"""Fail closed on BG-camera/OAM cross-generation presentation.

Consumes the consecutive-frame JSON emitted by
``validate_fresh_poststart_framebuffers.py``. The gate proves that the displayed
camera is exactly reconciled with the last complete hardware-OAM base by its
published compensation, and that the published OAM sequence stays within a
caller-selected game-tick age.
It is a renderer component gate, not an aligned MAME or promotion result.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


def signed8(value: int) -> int:
    value &= 0xFF
    return value - 0x100 if value & 0x80 else value


def compress_ranges(values: list[int]) -> list[list[int]]:
    if not values:
        return []
    result: list[list[int]] = []
    start = previous = values[0]
    for value in values[1:]:
        if value == previous + 1:
            previous = value
            continue
        result.append([start, previous])
        start = previous = value
    result.append([start, previous])
    return result


def evaluate(source: dict[str, Any], max_obj_sequence_lag: int = 4) -> dict[str, Any]:
    captures = source.get("captures")
    if not isinstance(captures, list) or not captures:
        raise ValueError("source report has no captures")

    failures: list[str] = []
    compensation_failures: list[int] = []
    lag_failures: list[int] = []
    step_failures: list[int] = []
    incomplete_frames: list[int] = []
    rows: list[dict[str, Any]] = []
    previous: dict[str, int] | None = None

    for index, capture in enumerate(captures):
        relative = capture.get("relative_frame", index)
        required = (
            capture.get("tick"),
            capture.get("presented_scrollx"),
            capture.get("obj_published_sequence"),
            capture.get("obj_published_base_scrollx"),
            capture.get("obj_published_comp"),
            capture.get("obj_published_valid"),
        )
        if not isinstance(relative, int) or any(not isinstance(value, int) for value in required):
            incomplete_frames.append(index)
            continue
        tick, presented, sequence, base, compensation, valid = (
            int(value) for value in required
        )
        lag = (tick - sequence) & 0xFFFF
        lag_valid = lag <= max_obj_sequence_lag
        if valid == 0xA5 and not lag_valid:
            lag_failures.append(relative)

        expected_compensation = (base - presented) & 0xFF
        compensation_valid = (compensation & 0xFF) == expected_compensation
        if valid == 0xA5 and not compensation_valid:
            compensation_failures.append(relative)
        step_valid = True
        if previous is not None:
            frame_step = signed8(presented - previous["presented"])
            step_valid = abs(frame_step) <= 2
            if not step_valid:
                step_failures.append(relative)

        rows.append(
            {
                "relative_frame": relative,
                "tick": tick,
                "presented_scrollx": presented,
                "published_oam_sequence": sequence,
                "published_oam_base_scrollx": base,
                "published_oam_compensation": compensation & 0xFF,
                "expected_oam_compensation": expected_compensation,
                "published_oam_sequence_lag": lag,
                "camera_oam_compensation_exact": compensation_valid,
                "camera_step_bounded": step_valid,
            }
        )
        previous = {"presented": presented, "base": base, "valid": valid}

    relative_frames = [
        capture.get("relative_frame", index)
        for index, capture in enumerate(captures)
        if isinstance(capture.get("relative_frame", index), int)
    ]
    coverage_complete = relative_frames == list(range(relative_frames[0], relative_frames[-1] + 1))
    if not coverage_complete:
        failures.append("relative framebuffer coverage is not consecutive")
    if incomplete_frames:
        failures.append(f"required renderer fields absent at capture indexes {compress_ranges(incomplete_frames)}")
    if compensation_failures:
        failures.append(
            "published OAM compensation did not reconcile base and camera at frames "
            f"{compress_ranges(compensation_failures)}"
        )
    if lag_failures:
        failures.append(
            f"published OAM exceeded {max_obj_sequence_lag}-tick age at frames "
            f"{compress_ranges(lag_failures)}"
        )
    if step_failures:
        failures.append(f"camera exceeded two pixels per video frame at {compress_ranges(step_failures)}")

    return {
        "schema": 1,
        "kind": "scene_generation_coherence_component_gate",
        "authority": "component_only",
        "rom_sha256": source.get("rom_sha256"),
        "status": "pass" if not failures else "fail",
        "coverage": {
            "complete": coverage_complete and not incomplete_frames,
            "frame_start": relative_frames[0],
            "frame_end": relative_frames[-1],
            "frames": len(captures),
        },
        "checks": {
            "camera_oam_compensation_exact": not compensation_failures,
            "published_oam_age_bounded": not lag_failures,
            "camera_steps_bounded": not step_failures,
        },
        "limits": {"max_obj_sequence_lag": max_obj_sequence_lag, "max_camera_step": 2},
        "mismatch_ranges": {
            "camera_oam_compensation": compress_ranges(compensation_failures),
            "oam_age": compress_ranges(lag_failures),
            "camera_step": compress_ranges(step_failures),
        },
        "max_observed_oam_sequence_lag": max(row["published_oam_sequence_lag"] for row in rows),
        "failures": failures,
        "captures": rows,
        "scope_note": (
            "Internal consecutive-frame coherence only; does not prove MAME pixels, "
            "facing, animation order, fresh lineage, or promotion eligibility."
        ),
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--max-obj-sequence-lag", type=int, default=4)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    source = json.loads(args.input.read_text())
    report = evaluate(source, args.max_obj_sequence_lag)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    print(json.dumps({"status": report["status"], "failures": report["failures"]}))
    return 0 if report["status"] == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
