#!/usr/bin/env python3
"""Focused checks for the durable campaign-evidence reuse decision."""

from __future__ import annotations

import json
import subprocess
import tempfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
TOOL = ROOT / "tools/validate_campaign_evidence_ledger.py"
ROM = ROOT / "build/interp-vtime-interpreter-only-e00f-gate-restore-v1.sfc"
LINEAGE = "vtime_interpreter_only_gate_restore_v1"


def run(*extra: str) -> dict:
    output = subprocess.check_output(
        ["python3", str(TOOL), "--lineage", LINEAGE, *extra],
        cwd=ROOT,
        text=True,
    )
    return json.loads(output)


def main() -> None:
    audit = run()
    assert audit["valid"] is True
    assert audit["lineages"][0]["accepted_through_tick"] == 14743

    covered = run(
        "--candidate-rom", str(ROM), "--target-tick", "3000"
    )
    assert covered["query"]["decision"] == "already_covered"

    resume = run(
        "--candidate-rom", str(ROM), "--target-tick", "15000"
    )
    assert resume["query"]["decision"] == "resume_from_newest_checkpoint"
    assert resume["query"]["checkpoint"]["resume_tick"] == 14744

    with tempfile.NamedTemporaryFile() as different:
        different.write(b"different ROM identity")
        different.flush()
        incompatible = run(
            "--candidate-rom", different.name, "--target-tick", "6000"
        )
    assert incompatible["query"]["decision"] == "incompatible_candidate"
    print("campaign evidence ledger regression: green")


if __name__ == "__main__":
    main()
