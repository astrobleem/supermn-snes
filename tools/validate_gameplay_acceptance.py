#!/usr/bin/env python3
"""Aggregate the three mandatory gameplay-validation oracles.

The manifest names one ROM, one exact inclusive game-tick range, and reports
for state equivalence, aligned exact-MAME pixels, and every-frame temporal
conservation.  Missing, malformed, mismatched, or incomplete evidence is
UNKNOWN.  This is the only framebuffer tooling allowed to emit an overall
gameplay-acceptance green result.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from gameplay_acceptance_contract import (
    REQUIRED_GATES,
    STATUSES,
    load_json,
    sha256_file,
    valid_sha256,
    validate_gate,
    validate_requested_coverage,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    return parser.parse_args()


def resolve(base: Path, raw: Any) -> Path:
    path = Path(str(raw))
    return path if path.is_absolute() else base / path


def main() -> int:
    args = parse_args()
    manifest_path = args.manifest.resolve()
    manifest = load_json(manifest_path)
    rom_sha256 = manifest.get("rom_sha256")
    coverage = manifest.get("coverage")
    global_reasons: list[str] = []
    if not valid_sha256(rom_sha256):
        global_reasons.append("manifest_rom_sha256_invalid")
        rom_sha256 = ""
    global_reasons.extend(validate_requested_coverage(coverage))
    if not isinstance(coverage, dict):
        coverage = {}
    declared = manifest.get("gates")
    if not isinstance(declared, dict):
        declared = {}
        global_reasons.append("manifest_gates_missing")

    gate_results: dict[str, dict[str, Any]] = {}
    for kind in REQUIRED_GATES:
        raw_path = declared.get(kind)
        row: dict[str, Any] = {
            "kind": kind,
            "status": "unknown",
            "report": None,
            "report_sha256": None,
            "reasons": [],
        }
        if raw_path is None:
            row["reasons"].append("report_not_declared")
        else:
            path = resolve(manifest_path.parent, raw_path).resolve()
            row["report"] = str(path)
            if not path.is_file():
                row["reasons"].append("report_missing")
            else:
                row["report_sha256"] = sha256_file(path)
                try:
                    report = load_json(path)
                    gate_value = report.get("acceptance_gate")
                    row["reasons"].extend(
                        validate_gate(gate_value, kind, rom_sha256, coverage)
                    )
                    if not row["reasons"]:
                        row["status"] = gate_value["status"]
                except (OSError, ValueError, json.JSONDecodeError) as error:
                    row["reasons"].append(
                        f"report_unreadable:{type(error).__name__}"
                    )
        gate_results[kind] = row

    statuses = [row["status"] for row in gate_results.values()]
    if global_reasons:
        overall = "unknown"
    elif "red" in statuses:
        overall = "red"
    elif all(status == "green" for status in statuses):
        overall = "green"
    else:
        overall = "unknown"

    output = args.output.resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    report = {
        "schema": 1,
        "scope": (
            "aggregate gameplay acceptance; requires state, aligned exact-MAME "
            "pixels, and every-frame temporal conservation over one exact ROM/range"
        ),
        "manifest": str(manifest_path),
        "manifest_sha256": sha256_file(manifest_path),
        "rom_sha256": rom_sha256 or None,
        "coverage": coverage,
        "required_gates": list(REQUIRED_GATES),
        "gates": gate_results,
        "global_reasons": sorted(set(global_reasons)),
        "acceptance_status": overall,
        "claim_authority": (
            "bounded_gameplay_acceptance" if overall == "green" else "none"
        ),
        "claim_rule": (
            "Never report unqualified no-divergence, fixed, playable, or visual "
            "green outside this exact ROM and inclusive tick range."
        ),
    }
    output.write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(
        json.dumps(
            {
                "acceptance_status": overall,
                "coverage": coverage,
                "gates": {kind: row["status"] for kind, row in gate_results.items()},
                "report": str(output),
            },
            sort_keys=True,
        )
    )
    return {"green": 0, "red": 1, "unknown": 2}[overall]


if __name__ == "__main__":
    raise SystemExit(main())
