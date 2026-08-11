#!/usr/bin/env python3
"""Join controlled `$02429C` semantic and original-MAME cycle coverage.

The organic MAME movie is the timing oracle for its observed path.  This
read-only reducer records the complementary, deliberately controlled arms:
each one first passed the active-ROM MAME/native-off/native-on function
differential, then produced a bounded IRQ-masked original-MAME instruction
trace.  The report may therefore close the *root/direct-child dynamic timing
inventory*, but never the global virtual clock, a native handoff, IRQ cadence,
organic gameplay, rate, or playthrough.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

import validate_mame_2429c_branch_timing as branch
import validate_mame_2429c_native_child_timing as child


ROOT = Path(__file__).resolve().parents[1]
SEMANTIC = ROOT / "build" / "validate-2429c-distinct-arm-isolated-a976-pinned-v2.jsonl"
MANIFEST = ROOT / "build" / "mame-2429c-fixture-cycles-original-v2" / "manifest.json"
ACTIVE_ROM_SHA256 = "a9765fbfbd2a0863f093ff1bb887cfd422ecde26e3c46bae0afd56bf8b1dac60"
MAME = {
    "gnome_content_revision": "263",
    "path": "/tmp/mame-4339-recovery/root/mame",
    "sha256": "297843036f728695878300f3bd9949122907cd83bfd6d501875e9a49cd950c6f",
    "snap_revision": "4339",
    "version": "0.287 (mame0287)",
}


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def read_json(path: Path) -> dict[str, Any]:
    if not path.is_file():
        raise RuntimeError(f"missing retained artifact: {path}")
    return json.loads(path.read_text(encoding="utf-8"))


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.is_file():
        raise RuntimeError(f"missing retained artifact: {path}")
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


def report_path(kind: str, case: str) -> Path:
    if kind == "branch":
        stem = "validate-mame-2429c-branch-fixture"
    elif kind == "child":
        stem = "validate-mame-2429c-native-child-fixture"
    else:
        raise ValueError(kind)
    return ROOT / "build" / f"{stem}-{case}-v2.json"


def collect() -> dict[str, Any]:
    semantic_rows = read_jsonl(SEMANTIC)
    if not semantic_rows or semantic_rows[0].get("event") != "provenance":
        raise RuntimeError("missing semantic-differential provenance")
    semantic = semantic_rows[0]
    cases = [row for row in semantic_rows if row.get("event") == "case"]
    summary = semantic_rows[-1]
    semantic_ok = (
        semantic.get("rom_sha256") == ACTIVE_ROM_SHA256
        and semantic.get("capture_rom_sha256") == ACTIVE_ROM_SHA256
        and semantic.get("mame") == MAME
        and semantic.get("fixtures") == 4
        and semantic.get("variants_per_fixture") == 3
        and len(cases) == 12
        and all(row.get("result") == "green" for row in cases)
        and summary.get("result") == "green"
        and summary.get("green") == 12
        and summary.get("red") == 0
        and summary.get("total") == 12
    )

    manifest = read_json(MANIFEST)
    manifest_cases = list(manifest.get("cases", []))
    if manifest.get("mame") != MAME or len(manifest_cases) != 4:
        raise RuntimeError("fixture trace manifest identity/case count changed")
    root_expected = {f"{pc:06X}" for pc in branch.ROOT_DYNAMIC_PCS}
    child_expected = {f"{pc:06X}" for pc in child.child_dynamic_pcs()}
    root_seen: set[str] = set()
    child_seen: set[str] = set()
    per_case: list[dict[str, object]] = []
    artifacts: dict[str, dict[str, object]] = {
        "semantic": {"path": str(SEMANTIC.resolve()), "sha256": sha256(SEMANTIC)},
        "manifest": {"path": str(MANIFEST.resolve()), "sha256": sha256(MANIFEST)},
    }
    for row in manifest_cases:
        name = str(row.get("case", ""))
        summary_path = Path(str(row.get("summary", "")))
        fixture_summary = read_json(summary_path)
        if fixture_summary.get("mame") != MAME:
            raise RuntimeError(f"{name}: fixture trace is not exact MAME 0.287")
        if fixture_summary.get("capture", {}).get("terminal_hits") != 1:
            raise RuntimeError(f"{name}: no finite terminal boundary")
        if fixture_summary.get("entry_pc") != "02429C" or fixture_summary.get("terminal_pc") != "02429A":
            raise RuntimeError(f"{name}: wrong root fixture boundary")
        branch_path = report_path("branch", name)
        child_path = report_path("child", name)
        branch_report = read_json(branch_path)
        child_report = read_json(child_path)
        if branch_report.get("result") != "green" or branch_report.get("failures"):
            raise RuntimeError(f"{name}: root cycle prediction failure")
        if child_report.get("result") != "green" or child_report.get("failures"):
            raise RuntimeError(f"{name}: child cycle prediction failure")
        observed_root = set(branch_report.get("observed_counts", {}))
        observed_child = set(child_report.get("observed_counts", {}))
        root_seen.update(observed_root)
        child_seen.update(observed_child)
        per_case.append(
            {
                "case": name,
                "trace_records": fixture_summary["capture"]["register_trace_records"],
                "root_dynamic_pcs": sorted(observed_root),
                "child_dynamic_pcs": sorted(observed_child),
            }
        )
        artifacts[name] = {
            "summary": {"path": str(summary_path.resolve()), "sha256": sha256(summary_path)},
            "branch": {"path": str(branch_path.resolve()), "sha256": sha256(branch_path)},
            "child": {"path": str(child_path.resolve()), "sha256": sha256(child_path)},
        }

    alternate = next(
        row for row in per_case
        if row["case"] == "synthetic-active-child-and-root-alternate-branches"
    )
    targeted_outcomes_ok = (
        "024388" in alternate["root_dynamic_pcs"]
        and "023618" in alternate["child_dynamic_pcs"]
    )
    result = "green" if (
        semantic_ok
        and root_seen == root_expected
        and child_seen == child_expected
        and targeted_outcomes_ok
    ) else "red"
    return {
        "scope": (
            "bounded controlled `$02429C` semantic triple differential plus "
            "original-MAME dynamic timing inventory; not common-clock, IRQ, "
            "organic-gameplay, rate, or playthrough acceptance"
        ),
        "active_rom_sha256": ACTIVE_ROM_SHA256,
        "mame": MAME,
        "semantic_triple_differential": {
            "fixtures": 4,
            "configurations_per_fixture": 3,
            "green": sum(row.get("result") == "green" for row in cases),
            "total": len(cases),
            "all_register_ccr_stack_work_checks_green": semantic_ok,
        },
        "original_mame_fixture_traces": per_case,
        "root_dynamic": {
            "expected": sorted(root_expected),
            "observed": sorted(root_seen),
            "complete": root_seen == root_expected,
        },
        "direct_native_child_dynamic": {
            "expected": sorted(child_expected),
            "observed": sorted(child_seen),
            "complete": child_seen == child_expected,
        },
        "targeted_new_outcomes": {
            "fixture": alternate["case"],
            "root_024388_observed": "024388" in alternate["root_dynamic_pcs"],
            "child_023618_observed": "023618" in alternate["child_dynamic_pcs"],
        },
        "artifacts": artifacts,
        "promotion_blocked": True,
        "not_proven": [
            "native parent/child ownership handoff",
            "common virtual MC68000 clock",
            "unmasked IRQ ordering/cadence",
            "interpreter-child timing ownership",
            "other accelerated boundaries and legacy $AC migration",
            "organic Stage-3 completion, rate, or full playthrough",
        ],
        "result": result,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        parser.error(f"refusing to overwrite output: {args.output}")
    report = collect()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({"result": report["result"], "output": str(args.output.resolve())}, sort_keys=True))
    return 0 if report["result"] == "green" else 1


if __name__ == "__main__":
    raise SystemExit(main())
