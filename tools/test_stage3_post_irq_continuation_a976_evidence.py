#!/usr/bin/env python3
"""Guard the active-ROM post-IRQ continuation and its immutable pre-failure state."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
ROM_SHA256 = "a9765fbfbd2a0863f093ff1bb887cfd422ecde26e3c46bae0afd56bf8b1dac60"
PREFIX = ROOT / "build/continue-stage3-current-a976-safe14743-native-on-prefailure-v2"
SUFFIX = ROOT / "build/continue-stage3-current-a976-safe14743-native-on-v1"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def rows(path: Path) -> list[dict]:
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def main() -> None:
    prefix = json.loads((PREFIX / "summary.json").read_text(encoding="utf-8"))
    assert prefix["rom_sha256"] == ROM_SHA256
    assert prefix["result"] == "partial-with-oracle-divergences"
    assert prefix["failure"] is None
    first = prefix["first_oracle_divergence"]
    assert first["kind"] == "input_response_compare"
    assert first["mame_tick"] == 14841
    assert first["source_input_tick"] == 14839
    assert first["comparison"] == {
        "mame": {"action": 0, "health": 4, "x": 52, "x1_ctrl_3601": 16, "x1_ctrl_3603": 33, "y": 112},
        "snes": {"action": 9, "health": 20, "x": 68, "x1_ctrl_3601": 16, "x1_ctrl_3603": 33, "y": 96},
        "mismatches": {
            "action": {"mame": 0, "snes": 9},
            "health": {"mame": 4, "snes": 20},
            "x": {"mame": 52, "snes": 68},
            "y": {"mame": 112, "snes": 96},
        },
        "result": "red",
    }
    retained = first["pre_failure_input_state"]
    retained_path = ROOT / retained["path"]
    retained_iram = ROOT / retained["sa1_iram_sidecar"]["path"]
    assert retained["copied_at_first_observation"] is True
    assert retained["boundary_kind"] == "pre_input_apply_exact_entry_forensic"
    assert retained["input"]["effective_mame_tick"] == 14839
    assert retained_path.is_file() and retained_iram.is_file()
    assert sha256(retained_path) == retained["sha256"] == retained["source_sha256"]
    assert sha256(retained_iram) == retained["sa1_iram_sidecar"]["sha256"]
    prefix_rows = rows(PREFIX / "events.jsonl")
    green_before = [
        row for row in prefix_rows
        if row["event"] in {"input_compare", "input_response_compare"}
        and 14744 <= int(row["mame_tick"]) < 14841
    ]
    assert green_before and all(row["comparison"]["result"] == "green" for row in green_before)
    suffix = json.loads((SUFFIX / "summary.json").read_text(encoding="utf-8"))
    assert suffix["rom_sha256"] == ROM_SHA256
    assert suffix["result"] == "partial-with-oracle-divergences"
    assert suffix["failure"] is None
    assert suffix["oracle_divergence_count"] == 15
    end = next(row for row in rows(SUFFIX / "events.jsonl") if row["event"] == "campaign_end")
    snap = end["snapshot"]
    assert snap["mame_tick"] == 15050
    assert snap["halt"] == 0
    assert snap["minimum_margin"] == 138
    assert snap["render_generation"] > snap["render_complete"] > 0
    print("active a976 Stage-3 post-IRQ continuation evidence: retained")


if __name__ == "__main__":
    main()
