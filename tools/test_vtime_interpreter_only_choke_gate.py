#!/usr/bin/env python3
"""Guard the VTIME choke pre-arm test against DP-register aliasing."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PACKER = ROOT / "tools" / "build_interp_rom.py"
OLD = bytes.fromhex("c230a52ef00f")
FIXED = bytes.fromhex("c230ad2e07f00f")
CHOKE_OFFSETS = (0x7980, 0xF980)
CANDIDATE = ROOT / (
    "build/interp-vtime-interpreter-only-e00f-gate-restore-scheduler-0818-"
    "mvc-fallback-choke-gate-v1.sfc"
)
BASE = ROOT / (
    "build/interp-vtime-e00f-gate-restore-scheduler-0818-mvc-fallback-"
    "choke-gate-v1.sfc"
)
OLD_CANDIDATE = ROOT / (
    "build/interp-vtime-interpreter-only-e00f-gate-restore-scheduler-0818-"
    "mvc-fallback-v1.sfc"
)
MANIFEST = CANDIDATE.with_suffix(".manifest.json")
PRODUCTION = ROOT / "build/interp.sfc"
PRODUCTION_SHA256 = "2dadd12cba0f2a90b0bfeef9e6ef4f8722a6ba46650677c59b85eb9087e430dd"
BASE_SHA256 = "05b2dbf97b45d50242c3d69abe11899d7b13f876e46ddd832be8cd509c28f42b"
CANDIDATE_SHA256 = "d91e28e99e1c2c04e8c3d539b69195ce744697ded1cd577981e692c8401f2b28"


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def main() -> None:
    source = PACKER.read_text(encoding="utf-8")
    assert '"c230ad2e07f00f2280b4f2d005685ca580005c81e20060"' in source
    assert '"c230a52ef00f2280b4f2d005685ca580005c81e20060"' not in source
    assert "accidentally read emulated A3.H" in source
    assert "exact three-byte absolute load" in source

    production = PRODUCTION.read_bytes()
    base = BASE.read_bytes()
    old = OLD_CANDIDATE.read_bytes()
    rom = CANDIDATE.read_bytes()
    assert len(production) == len(base) == len(old) == len(rom) == 0x400000
    assert sha256(production) == PRODUCTION_SHA256
    assert sha256(base) == BASE_SHA256
    assert sha256(rom) == CANDIDATE_SHA256
    for offset in CHOKE_OFFSETS:
        assert rom[offset : offset + len(FIXED)] == FIXED
        assert rom[offset : offset + len(OLD)] != OLD
    allowed_differences = {
        *range(0x7980, 0x79AA),
        *range(0xF980, 0xF9AA),
        0xFFDC,
        0xFFDD,
        0xFFDE,
        0xFFDF,
    }
    differences = {
        index for index, (before, after) in enumerate(zip(old, rom)) if before != after
    }
    assert len(differences) == 42
    assert differences <= allowed_differences
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    assert manifest["base"]["sha256"] == BASE_SHA256
    assert manifest["output"]["sha256"] == CANDIDATE_SHA256
    assert manifest["changed_bytes"] == 1
    assert manifest["change"]["file_offset"] == "328000"
    print("VTIME interpreter-only choke gate: green absolute $072E load")


if __name__ == "__main__":
    main()
