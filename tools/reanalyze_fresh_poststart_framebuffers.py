#!/usr/bin/env python3
"""Reapply the visual gate to authenticated retained fresh-run artifacts.

This avoids replaying the multi-thousand-frame boot when only a machine
threshold changes.  It recomputes every PNG metric, verifies every PNG hash,
and preserves the original emulator report as immutable input evidence.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

from gameplay_acceptance_contract import unknown_diagnostic_gate  # noqa: E402
from validate_fresh_poststart_framebuffers import (  # noqa: E402
    evaluate_rows,
    image_metrics,
    sha256,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--results", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--visual-grace-frames", type=int, default=100)
    return parser.parse_args()


def visual_transition_observations(
    rows: list[dict[str, Any]], visual_grace_frames: int
) -> list[dict[str, Any]]:
    kinds = {"blank_playfield", "repeated_tile_collapse", "bg1_not_visible"}
    return [
        failure
        for failure in evaluate_rows(rows, 0)
        if failure["kind"] in kinds
        and failure["relative_frame"] < visual_grace_frames
    ]


def main() -> int:
    args = parse_args()
    source = args.results.resolve()
    target = args.output.resolve()
    if not source.is_file():
        raise FileNotFoundError(source)
    if target.exists():
        raise SystemExit(f"refusing existing output: {target}")
    if args.visual_grace_frames < 0:
        raise SystemExit("--visual-grace-frames must be nonnegative")

    report = json.loads(source.read_text())
    if report.get("schema") != 1:
        raise RuntimeError("unsupported fresh-run report schema")
    if report.get("movie_start") != "StartWithoutSaveData":
        raise RuntimeError("retained run did not start without save data")
    if report.get("runtime_memory_writes"):
        raise RuntimeError("retained run contains runtime memory interventions")
    if not report.get("coverage", {}).get("complete"):
        raise RuntimeError("retained run does not have complete coverage")

    rom = Path(report["rom"])
    movie = Path(report["movie"])
    contact_sheet = Path(report["contact_sheet"]["path"])
    for path, expected in (
        (rom, report["rom_sha256"]),
        (movie, report["movie_sha256"]),
        (contact_sheet, report["contact_sheet"]["sha256"]),
    ):
        if not path.is_file() or sha256(path) != expected:
            raise RuntimeError(f"retained artifact hash mismatch: {path}")

    rows: list[dict[str, Any]] = []
    for original in report["captures"]:
        row = dict(original)
        screenshot = Path(row["screenshot"]["path"])
        if not screenshot.is_file():
            raise RuntimeError(f"missing retained framebuffer: {screenshot}")
        if sha256(screenshot) != row["screenshot"]["sha256"]:
            raise RuntimeError(f"retained framebuffer hash mismatch: {screenshot}")
        recomputed = image_metrics(screenshot)
        if recomputed != row["image_metrics"]:
            raise RuntimeError(f"stored framebuffer metrics changed: {screenshot}")
        row["image_metrics"] = recomputed
        rows.append(row)

    failures = evaluate_rows(rows, args.visual_grace_frames)
    transition = visual_transition_observations(rows, args.visual_grace_frames)
    acceptance_gate = unknown_diagnostic_gate(
        "fresh_poststart_framebuffers_offline_reanalysis",
        (
            "Authenticated offline visual reanalysis cannot replace exact-MAME "
            "pixels, every-frame MAME conservation, or human visual review."
        ),
    )
    acceptance_gate["rom_sha256"] = report["rom_sha256"]
    acceptance_gate["coverage"] = report["coverage"]
    result = {
        "schema": 1,
        "scope": (
            "offline reanalysis of every authenticated retained framebuffer; "
            "no emulator replay and no runtime writes"
        ),
        "source_results": str(source),
        "source_results_sha256": sha256(source),
        "rom": str(rom),
        "rom_sha256": report["rom_sha256"],
        "movie": str(movie),
        "movie_sha256": report["movie_sha256"],
        "runtime_memory_writes": [],
        "coverage": report["coverage"],
        "verified_framebuffer_count": len(rows),
        "visual_grace_frames": args.visual_grace_frames,
        "pre_grace_transition_observations": transition,
        "visual_regression_result": "red" if failures else "clear",
        "first_failure": failures[0] if failures else None,
        "failures": failures,
        "manual_review_required": True,
        "contact_sheet": report["contact_sheet"],
        "acceptance_gate": acceptance_gate,
    }
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
    print(
        json.dumps(
            {
                "visual_regression_result": result["visual_regression_result"],
                "verified_framebuffers": len(rows),
                "first_failure": result["first_failure"],
                "pre_grace_transition_observations": len(transition),
                "report": str(target),
                "acceptance_status": "unknown",
            },
            sort_keys=True,
        )
    )
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
