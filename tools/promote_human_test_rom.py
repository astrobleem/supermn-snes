#!/usr/bin/env python3
"""Fail-closed promotion of an exact ROM to a human-test copy.

An ordinary ``build/interp.sfc`` is never a handoff candidate.  This tool is the
only supported path to a ``Superman-Arcade-Edition-<hash>-test.sfc`` file.  It
requires a hash-bound manifest whose independent scenario reports are all green,
fresh-power, complete, mutation-free, and artifact-authenticated.

This tool does not run playback.  Long validators retain their large data on disk
and emit the compact reports consumed here.  Missing or narrow evidence fails
closed instead of being interpreted as success.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import tempfile
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
ROM_SIZE = 0x400000
MANIFEST_SCHEMA = 1
REPORT_SCHEMA = 1

REQUIRED_SCENARIOS: dict[str, tuple[str, ...]] = {
    "cold_boot_presentation": (
        "fresh_power_on",
        "logo_fully_visible",
        "logo_horizontally_centered",
        "loading_text_visible",
        "no_corrupt_pixels",
    ),
    "title_credit_start": (
        "title_visible",
        "credit_registered",
        "start_consumed_credit",
        "gameplay_entered",
        "composite_frames_clear",
    ),
    "walk_right": (
        "player_moved_right",
        "facing_right",
        "animation_progressed_forward",
        "composite_frames_clear",
    ),
    "walk_left": (
        "player_moved_left",
        "facing_left",
        "animation_progressed_forward",
        "composite_frames_clear",
    ),
    "attack_motion": (
        "stationary_attack_visible",
        "moving_attack_visible",
        "facing_matches_motion",
        "animation_progressed_forward",
        "composite_frames_clear",
    ),
    "scroll_continuity": (
        "every_video_frame_captured",
        "no_black_vertical_bands",
        "no_flashes",
        "no_gaps",
        "no_reverse_or_oversized_steps",
        "composite_frames_clear",
    ),
    "fence_break": (
        "intact_fence_visible",
        "intact_fence_blocks_player",
        "attack_hits_fence",
        "break_animation_visible",
        "broken_fence_passable",
        "no_black_background",
        "composite_frames_clear",
    ),
    "full_composite_oracle": (
        "mame_alignment_proven",
        "background_compared",
        "objects_compared",
        "hud_compared",
        "every_game_tick_compared",
        "every_intervening_snes_frame_conserved",
    ),
    "sol_visual_review": (
        "cold_boot_artifacts_opened",
        "title_credit_artifacts_opened",
        "walk_right_artifacts_opened",
        "walk_left_artifacts_opened",
        "attack_artifacts_opened",
        "scroll_artifacts_opened",
        "fence_artifacts_opened",
        "composite_oracle_artifacts_opened",
    ),
}

VISUAL_ARTIFACT_KINDS = {"screenshot", "contact_sheet", "video"}


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def load_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text())
    if not isinstance(value, dict):
        raise ValueError(f"expected JSON object: {path}")
    return value


def confined_path(parent: Path, raw: Any, label: str) -> Path:
    if not isinstance(raw, str) or not raw:
        raise ValueError(f"{label} must be a nonempty relative path")
    supplied = Path(raw)
    if supplied.is_absolute():
        raise ValueError(f"{label} must be relative: {raw}")
    resolved = (parent / supplied).resolve()
    try:
        resolved.relative_to(parent.resolve())
    except ValueError as exc:
        raise ValueError(f"{label} escapes its evidence directory: {raw}") from exc
    return resolved


def validate_artifacts(
    scenario: str, report_path: Path, artifacts: Any
) -> list[str]:
    errors: list[str] = []
    if not isinstance(artifacts, list) or not artifacts:
        return [f"{scenario}: artifacts must be a nonempty list"]
    has_visual = False
    for index, artifact in enumerate(artifacts):
        prefix = f"{scenario}: artifact[{index}]"
        if not isinstance(artifact, dict):
            errors.append(f"{prefix} must be an object")
            continue
        kind = artifact.get("kind")
        if kind in VISUAL_ARTIFACT_KINDS:
            has_visual = True
        try:
            path = confined_path(report_path.parent, artifact.get("path"), prefix)
        except ValueError as exc:
            errors.append(str(exc))
            continue
        expected = artifact.get("sha256")
        if not isinstance(expected, str) or len(expected) != 64:
            errors.append(f"{prefix} has invalid sha256")
            continue
        if not path.is_file():
            errors.append(f"{prefix} is missing: {path}")
            continue
        observed = sha256(path)
        if observed != expected:
            errors.append(
                f"{prefix} hash mismatch: expected {expected}, observed {observed}"
            )
    if not has_visual:
        errors.append(f"{scenario}: no screenshot/contact-sheet/video artifact")
    return errors


def validate_scenario_report(
    scenario: str,
    report_path: Path,
    report: dict[str, Any],
    rom_sha256: str,
) -> list[str]:
    errors: list[str] = []
    if report.get("schema") != REPORT_SCHEMA:
        errors.append(f"{scenario}: unsupported report schema")
    if report.get("scenario") != scenario:
        errors.append(f"{scenario}: report scenario identity mismatch")
    if report.get("rom_sha256") != rom_sha256:
        errors.append(f"{scenario}: report ROM hash mismatch")
    if report.get("status") != "pass":
        errors.append(
            f"{scenario}: status is {report.get('status', 'missing')!r}, not 'pass'"
        )
    if report.get("lineage") != "fresh_power_on_movie":
        errors.append(f"{scenario}: lineage is not fresh_power_on_movie")
    if report.get("runtime_memory_writes") != []:
        errors.append(f"{scenario}: runtime_memory_writes must be an empty list")

    coverage = report.get("coverage")
    if not isinstance(coverage, dict) or coverage.get("complete") is not True:
        errors.append(f"{scenario}: coverage is absent or incomplete")
    else:
        start = coverage.get("frame_start")
        end = coverage.get("frame_end")
        if (
            not isinstance(start, int)
            or isinstance(start, bool)
            or not isinstance(end, int)
            or isinstance(end, bool)
            or start < 0
            or end < start
        ):
            errors.append(f"{scenario}: invalid coverage frame range")

    failures = report.get("failures")
    if failures != []:
        errors.append(f"{scenario}: failures must be an explicit empty list")

    checks = report.get("checks")
    if not isinstance(checks, dict):
        errors.append(f"{scenario}: checks must be an object")
    else:
        for name in REQUIRED_SCENARIOS[scenario]:
            if checks.get(name) is not True:
                errors.append(f"{scenario}: required check {name!r} is not true")

    errors.extend(validate_artifacts(scenario, report_path, report.get("artifacts")))
    return errors


def validate_manifest(
    manifest_path: Path, manifest: dict[str, Any], rom_sha256: str
) -> tuple[list[str], dict[str, dict[str, Any]]]:
    errors: list[str] = []
    loaded_reports: dict[str, dict[str, Any]] = {}
    if manifest.get("schema") != MANIFEST_SCHEMA:
        errors.append("unsupported promotion manifest schema")
    if manifest.get("rom_sha256") != rom_sha256:
        errors.append("promotion manifest ROM hash mismatch")
    reports = manifest.get("reports")
    if not isinstance(reports, dict):
        return errors + ["promotion manifest reports must be an object"], loaded_reports

    extra = sorted(set(reports) - set(REQUIRED_SCENARIOS))
    if extra:
        errors.append(f"unknown promotion scenarios: {', '.join(extra)}")
    for scenario in REQUIRED_SCENARIOS:
        reference = reports.get(scenario)
        if not isinstance(reference, dict):
            errors.append(f"missing required scenario report: {scenario}")
            continue
        try:
            report_path = confined_path(
                manifest_path.parent, reference.get("path"), f"{scenario} report"
            )
        except ValueError as exc:
            errors.append(str(exc))
            continue
        expected = reference.get("sha256")
        if not isinstance(expected, str) or len(expected) != 64:
            errors.append(f"{scenario}: invalid report sha256")
            continue
        if not report_path.is_file():
            errors.append(f"{scenario}: report is missing: {report_path}")
            continue
        observed = sha256(report_path)
        if observed != expected:
            errors.append(
                f"{scenario}: report hash mismatch: expected {expected}, observed {observed}"
            )
            continue
        try:
            report = load_json(report_path)
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            errors.append(f"{scenario}: cannot load report: {exc}")
            continue
        loaded_reports[scenario] = report
        errors.extend(
            validate_scenario_report(scenario, report_path, report, rom_sha256)
        )
    return errors, loaded_reports


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--rom", type=Path, required=True)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, default=ROOT / "build")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    rom = args.rom.resolve()
    manifest_path = args.manifest.resolve()
    if not rom.is_file():
        raise SystemExit(f"ROM not found: {rom}")
    if rom.stat().st_size != ROM_SIZE:
        raise SystemExit(f"refusing ROM of size {rom.stat().st_size}; expected {ROM_SIZE}")
    rom_bytes = rom.read_bytes()
    if int.from_bytes(rom_bytes[0x77E0:0x77E2], "little") != 0:
        raise SystemExit("refusing non-production ROM: TESTFLAG is set")
    if not manifest_path.is_file():
        raise SystemExit(f"promotion manifest not found: {manifest_path}")

    rom_hash = hashlib.sha256(rom_bytes).hexdigest()
    try:
        manifest = load_json(manifest_path)
        errors, reports = validate_manifest(manifest_path, manifest, rom_hash)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        raise SystemExit(f"invalid promotion manifest: {exc}") from exc
    if errors:
        print(
            json.dumps(
                {
                    "promotion_status": "blocked",
                    "rom_sha256": rom_hash,
                    "errors": errors,
                },
                indent=2,
                sort_keys=True,
            )
        )
        return 1

    output_dir = args.output_dir.resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    candidate = output_dir / f"Superman-Arcade-Edition-{rom_hash[:8]}-test.sfc"
    if candidate.exists():
        raise SystemExit(f"refusing to overwrite existing candidate: {candidate}")

    with tempfile.NamedTemporaryFile(
        prefix=f".{candidate.name}.", dir=output_dir, delete=False
    ) as stream:
        temporary = Path(stream.name)
    try:
        shutil.copyfile(rom, temporary)
        if sha256(temporary) != rom_hash:
            raise RuntimeError("candidate copy hash mismatch")
        os.replace(temporary, candidate)
    finally:
        if temporary.exists():
            temporary.unlink()

    handoff_dir = output_dir / ".human-test-handoffs"
    handoff_dir.mkdir(parents=True, exist_ok=True)
    handoff = handoff_dir / f"{rom_hash}.json"
    record = {
        "schema": 1,
        "promotion_status": "pass",
        "candidate": str(candidate),
        "rom_sha256": rom_hash,
        "manifest": str(manifest_path),
        "manifest_sha256": sha256(manifest_path),
        "validated_scenarios": list(REQUIRED_SCENARIOS),
        "scenario_coverage": {
            name: reports[name]["coverage"] for name in REQUIRED_SCENARIOS
        },
        "permitted_claim": (
            "Exact-hash bounded human-test scenarios in validated_scenarios passed; "
            "no wider gameplay, performance, audio, hardware, or release claim."
        ),
    }
    handoff.write_text(json.dumps(record, indent=2, sort_keys=True) + "\n")
    print(json.dumps(record, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
