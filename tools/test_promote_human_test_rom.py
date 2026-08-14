#!/usr/bin/env python3
"""Regression tests for the fail-closed human-test promotion guard."""

from __future__ import annotations

import hashlib
import json
import tempfile
from pathlib import Path

import promote_human_test_rom as gate


ROM_SHA = "a" * 64


def write_json(path: Path, value: object) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n")
    return gate.sha256(path)


def make_evidence(root: Path) -> tuple[Path, dict[str, object]]:
    reports: dict[str, object] = {}
    for scenario, required_checks in gate.REQUIRED_SCENARIOS.items():
        report_dir = root / "reports" / scenario
        artifact = report_dir / "contact-sheet.png"
        artifact.parent.mkdir(parents=True, exist_ok=True)
        artifact.write_bytes(f"visual evidence for {scenario}".encode())
        report = {
            "schema": gate.REPORT_SCHEMA,
            "scenario": scenario,
            "rom_sha256": ROM_SHA,
            "status": "pass",
            "lineage": "fresh_power_on_movie",
            "runtime_memory_writes": [],
            "coverage": {"complete": True, "frame_start": 0, "frame_end": 100},
            "failures": [],
            "checks": {name: True for name in required_checks},
            "artifacts": [
                {
                    "kind": "contact_sheet",
                    "path": artifact.name,
                    "sha256": gate.sha256(artifact),
                }
            ],
        }
        report_path = report_dir / "report.json"
        report_sha = write_json(report_path, report)
        reports[scenario] = {
            "path": str(report_path.relative_to(root)),
            "sha256": report_sha,
        }
    manifest = {"schema": gate.MANIFEST_SCHEMA, "rom_sha256": ROM_SHA, "reports": reports}
    manifest_path = root / "promotion-manifest.json"
    write_json(manifest_path, manifest)
    return manifest_path, manifest


def assert_error(errors: list[str], fragment: str) -> None:
    if not any(fragment in error for error in errors):
        raise AssertionError(f"missing {fragment!r} in {errors!r}")


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="human-test-promotion-") as raw:
        root = Path(raw)
        manifest_path, manifest = make_evidence(root)
        errors, loaded = gate.validate_manifest(manifest_path, manifest, ROM_SHA)
        assert errors == []
        assert set(loaded) == set(gate.REQUIRED_SCENARIOS)

        missing = json.loads(json.dumps(manifest))
        del missing["reports"]["cold_boot_presentation"]
        errors, _ = gate.validate_manifest(manifest_path, missing, ROM_SHA)
        assert_error(errors, "missing required scenario report: cold_boot_presentation")

        errors, _ = gate.validate_manifest(manifest_path, manifest, "b" * 64)
        assert_error(errors, "promotion manifest ROM hash mismatch")

        walk_reference = manifest["reports"]["walk_right"]
        walk_path = root / walk_reference["path"]
        original_walk = json.loads(walk_path.read_text())

        red_walk = json.loads(json.dumps(original_walk))
        red_walk["status"] = "unknown"
        walk_reference["sha256"] = write_json(walk_path, red_walk)
        errors, _ = gate.validate_manifest(manifest_path, manifest, ROM_SHA)
        assert_error(errors, "walk_right: status is 'unknown', not 'pass'")

        incomplete_walk = json.loads(json.dumps(original_walk))
        incomplete_walk["checks"]["facing_right"] = False
        walk_reference["sha256"] = write_json(walk_path, incomplete_walk)
        errors, _ = gate.validate_manifest(manifest_path, manifest, ROM_SHA)
        assert_error(errors, "walk_right: required check 'facing_right' is not true")

        no_artifact_walk = json.loads(json.dumps(original_walk))
        no_artifact_walk["artifacts"][0]["path"] = "missing.png"
        walk_reference["sha256"] = write_json(walk_path, no_artifact_walk)
        errors, _ = gate.validate_manifest(manifest_path, manifest, ROM_SHA)
        assert_error(errors, "artifact[0] is missing")

    print("human-test ROM promotion guard: green")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
