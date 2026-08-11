#!/usr/bin/env python3
"""Pin the one-byte interpreter-only derivative of the e00f VTIME image."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
BASE = ROOT / "build/interp-vtime-2429c-root-b758-nmi-dma-d0-v1.sfc"
CANDIDATE = ROOT / "build/interp-vtime-interpreter-only-e00f-v1.sfc"
MANIFEST = ROOT / "build/interp-vtime-interpreter-only-e00f-v1.manifest.json"
OFFSET = 0x328000
BASE_HASH = "e00fb0cbba42bb5bb92808f70f3a42f1c0080c30aa0170ab01718cadefc07051"
CANDIDATE_HASH = "0bfae7d05a152441f9df4d028677641420a6053ce4148711668a1c5c6b48456f"


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def main() -> int:
    base = BASE.read_bytes()
    candidate = CANDIDATE.read_bytes()
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    assert len(base) == len(candidate) == 0x400000
    assert digest(base) == BASE_HASH
    assert digest(candidate) == CANDIDATE_HASH
    changed = [
        index
        for index, (before, after) in enumerate(zip(base, candidate))
        if before != after
    ]
    assert changed == [OFFSET]
    assert base[OFFSET] == 0x01
    assert candidate[OFFSET] == 0x03
    assert manifest["base"]["sha256"] == BASE_HASH
    assert manifest["output"]["sha256"] == CANDIDATE_HASH
    assert manifest["changed_bytes"] == 1
    assert manifest["change"] == {
        "file_offset": "328000",
        "before": "01",
        "after": "03",
        "meaning": "VTIME enabled plus post-initialization interpreter-only gates",
    }
    print("VTIME interpreter-only e00f candidate regression: green (one byte)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
