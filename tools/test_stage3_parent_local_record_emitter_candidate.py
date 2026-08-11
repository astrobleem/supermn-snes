#!/usr/bin/env python3
"""Regression guard for the parent-local Stage-3 route candidate builder."""

from __future__ import annotations

import hashlib
import subprocess
import sys
import tempfile
from pathlib import Path

import build_stage3_parent_local_record_emitter_candidate as candidate


ROOT = Path(__file__).resolve().parents[1]
ACTIVE = ROOT / "build" / "interp.sfc"
BUILDER = ROOT / "tools" / "build_stage3_parent_local_record_emitter_candidate.py"


def main() -> None:
    original = ACTIVE.read_bytes()
    assert hashlib.sha256(original).hexdigest() == candidate.ACTIVE_SHA256
    with tempfile.TemporaryDirectory(prefix="supermn-parent-local-emitter-") as temporary:
        output = Path(temporary) / "candidate.sfc"
        subprocess.run(
            [sys.executable, str(BUILDER), "--input", str(ACTIVE), "--output", str(output)],
            cwd=ROOT,
            check=True,
            capture_output=True,
            text=True,
        )
        proposed = output.read_bytes()

    allowed = set(range(candidate.CHECKSUM_OFFSET, candidate.CHECKSUM_OFFSET + 4))
    for _label, old, new in candidate.BRIDGES:
        offset = original.index(old)
        assert proposed[offset : offset + len(new)] == new
        allowed.update(range(offset + 11, offset + 14))
    changed = {i for i, (before, after) in enumerate(zip(original, proposed)) if before != after}
    assert changed <= allowed, sorted(changed - allowed)[:8]
    checked = bytearray(proposed)
    checked[candidate.CHECKSUM_OFFSET : candidate.CHECKSUM_OFFSET + 4] = bytes(4)
    total = sum(checked) & 0xFFFF
    assert proposed[candidate.CHECKSUM_OFFSET : candidate.CHECKSUM_OFFSET + 2] == ((~total) & 0xFFFF).to_bytes(2, "little")
    assert proposed[candidate.CHECKSUM_OFFSET + 2 : candidate.CHECKSUM_OFFSET + 4] == total.to_bytes(2, "little")
    print("Stage-3 parent-local record-emitter candidate builder: green")


if __name__ == "__main__":
    main()
