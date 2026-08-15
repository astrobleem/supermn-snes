#!/usr/bin/env python3
"""Fail-closed cadence gate for one uninterrupted renderer hook trace.

The pause/step framebuffer recorder can stop before the current PPU frame's NMI
finishes, so its adjacent memory samples are not valid presenter-call evidence.
This gate accepts only the hook stream recorded during one uninterrupted input
request and excludes the serialized starting partial frame.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any


REQUIRED_FRAME_LABELS = (
    "bg_scroll_present_step",
    "obj_present_nmi",
)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def contiguous_ranges(values: list[int]) -> list[list[int]]:
    ranges: list[list[int]] = []
    for value in sorted(values):
        if not ranges or value != ranges[-1][1] + 1:
            ranges.append([value, value])
        else:
            ranges[-1][1] = value
    return ranges


def signed8_delta(before: int, after: int) -> int:
    return ((after - before + 0x80) & 0xFF) - 0x80


def analyze_trace(
    source: dict[str, Any], events: list[dict[str, Any]], min_video_frames: int
) -> dict[str, Any]:
    initial = int(source["initial"]["ppu_frame"])
    final = int(source["final"]["ppu_frame"])
    advanced = int(source["advanced_video_frames"])
    coverage_start = initial + 1
    expected_frames = list(range(coverage_start, final + 1))
    exact_span = final - initial == advanced == len(expected_frames)

    by_label: dict[str, dict[int, list[dict[str, Any]]]] = {}
    for event in events:
        label = str(event["label"])
        frame = int(event["frame"])
        by_label.setdefault(label, {}).setdefault(frame, []).append(event)

    missing: dict[str, list[int]] = {}
    duplicates: dict[str, list[int]] = {}
    for label in REQUIRED_FRAME_LABELS:
        rows = by_label.get(label, {})
        missing[label] = [frame for frame in expected_frames if len(rows.get(frame, [])) == 0]
        duplicates[label] = [frame for frame in expected_frames if len(rows.get(frame, [])) > 1]

    cursor_rows = by_label.get("presented_scrollx_write", {})
    duplicate_cursor_frames = [
        frame for frame in expected_frames if len(cursor_rows.get(frame, [])) > 1
    ]
    cursor_writes = [
        event
        for frame in expected_frames
        for event in cursor_rows.get(frame, [])
    ]
    oversized_cursor_steps: list[dict[str, int]] = []
    for before, after in zip(cursor_writes, cursor_writes[1:]):
        delta = signed8_delta(int(before["value"]), int(after["value"]))
        if abs(delta) > 2:
            oversized_cursor_steps.append(
                {
                    "before_frame": int(before["frame"]),
                    "frame": int(after["frame"]),
                    "before": int(before["value"]),
                    "after": int(after["value"]),
                    "delta": delta,
                }
            )

    failures: list[str] = []
    if exact_span and advanced >= min_video_frames:
        for label in REQUIRED_FRAME_LABELS:
            if missing[label]:
                failures.append(f"{label} missing on {len(missing[label])} PPU frames")
            if duplicates[label]:
                failures.append(f"{label} duplicated on {len(duplicates[label])} PPU frames")
        if duplicate_cursor_frames:
            failures.append(
                f"presented cursor written more than once on {len(duplicate_cursor_frames)} PPU frames"
            )
        if oversized_cursor_steps:
            failures.append(
                f"{len(oversized_cursor_steps)} successive cursor writes exceeded two pixels"
            )

    if not exact_span or advanced < min_video_frames:
        status = "unknown"
    elif failures:
        status = "red"
    else:
        status = "green"

    divergence_candidates: list[tuple[int, str]] = []
    for label in REQUIRED_FRAME_LABELS:
        divergence_candidates.extend((frame, f"missing {label}") for frame in missing[label])
        divergence_candidates.extend((frame, f"duplicate {label}") for frame in duplicates[label])
    divergence_candidates.extend(
        (frame, "duplicate presented_scrollx_write") for frame in duplicate_cursor_frames
    )
    divergence_candidates.extend(
        (row["frame"], "cursor step exceeds two pixels") for row in oversized_cursor_steps
    )
    first_divergence = None
    if status == "red" and divergence_candidates:
        frame, kind = min(divergence_candidates)
        first_divergence = {"frame": frame, "kind": kind}

    return {
        "schema": 1,
        "result": status,
        "scope": (
            "uninterrupted same-emulator presenter-hook cadence component; "
            "not fresh boot, aligned pixels, gameplay acceptance, or performance"
        ),
        "coverage": {
            "initial_serialized_partial_frame_excluded": initial,
            "ppu_frames": [coverage_start, final],
            "video_frames": advanced,
            "minimum_required": min_video_frames,
            "exact": exact_span,
        },
        "first_divergence": first_divergence,
        "mismatch_ranges": {
            label: {
                "missing": contiguous_ranges(missing[label]),
                "duplicate": contiguous_ranges(duplicates[label]),
            }
            for label in REQUIRED_FRAME_LABELS
        },
        "cursor": {
            "writes": len(cursor_writes),
            "duplicate_frame_ranges": contiguous_ranges(duplicate_cursor_frames),
            "oversized_steps": oversized_cursor_steps,
            "maximum_successive_delta": max(
                (
                    abs(signed8_delta(int(before["value"]), int(after["value"])))
                    for before, after in zip(cursor_writes, cursor_writes[1:])
                ),
                default=0,
            ),
        },
        "failures": failures,
        "acceptance_gate": {
            "schema": 1,
            "status": "unknown",
            "authority": "diagnostic_only",
            "reason": "Presenter cadence alone cannot establish full-composite or gameplay acceptance.",
        },
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--results", type=Path, required=True)
    parser.add_argument("--hooks", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--min-video-frames", type=int, default=60)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.min_video_frames <= 0:
        raise SystemExit("--min-video-frames must be positive")
    source = json.loads(args.results.read_text(encoding="utf-8"))
    hooks = args.hooks or args.results.with_name("hooks.jsonl")
    expected_hash = source.get("hooks", {}).get("sha256")
    observed_hash = sha256(hooks)
    if expected_hash != observed_hash:
        raise SystemExit(
            f"hook stream authentication failed: expected {expected_hash}, observed {observed_hash}"
        )
    events = [
        json.loads(line)
        for line in hooks.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    report = analyze_trace(source, events, args.min_video_frames)
    report.update(
        {
            "source_results": str(args.results.resolve()),
            "source_results_sha256": sha256(args.results),
            "hooks": str(hooks.resolve()),
            "hooks_sha256": observed_hash,
            "rom_sha256": source.get("rom_sha256"),
        }
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({"result": report["result"], "report": str(args.output)}, sort_keys=True))
    return 0 if report["result"] == "green" else 1


if __name__ == "__main__":
    raise SystemExit(main())
