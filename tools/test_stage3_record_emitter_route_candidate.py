#!/usr/bin/env python3
"""Regression guard for the accepted-ROM Stage-3 emitter-route candidate."""

from __future__ import annotations

import hashlib
import subprocess
import sys
import tempfile
from pathlib import Path

import build_stage3_record_emitter_route_candidate as candidate


ROOT = Path(__file__).resolve().parents[1]
ACTIVE = ROOT / "build" / "interp.sfc"
BUILDER = ROOT / "tools" / "build_stage3_record_emitter_route_candidate.py"


def main() -> None:
    assert hashlib.sha256(ACTIVE.read_bytes()).hexdigest() == candidate.ACTIVE_SHA256
    with tempfile.TemporaryDirectory(prefix="supermn-record-emitter-") as temporary:
        output = Path(temporary) / "candidate.sfc"
        subprocess.run(
            [sys.executable, str(BUILDER), "--input", str(ACTIVE), "--output", str(output)],
            cwd=ROOT,
            check=True,
            capture_output=True,
            text=True,
        )
        proposed = output.read_bytes()

    original = ACTIVE.read_bytes()
    assert hashlib.sha256(proposed).hexdigest() == candidate.REJECTED_SHA256
    parent = original.index(candidate.PARENT_OLD)
    start = candidate.ESC7_FILE_BASE + candidate.DISPATCH_START
    end = candidate.ESC7_FILE_BASE + candidate.DISPATCH_END
    assert proposed[parent : parent + len(candidate.PARENT_NEW)] == candidate.PARENT_NEW
    assert proposed[start : start + len(candidate.NEW_DISPATCH_PREFIX)] == candidate.NEW_DISPATCH_PREFIX
    emitter_at = candidate.ESC7_FILE_BASE + (0xDA9B - 0x8000)
    assert proposed[
        emitter_at : emitter_at + len(candidate.NEW_EMITTER_ROUTE_PREFIX)
    ] == candidate.NEW_EMITTER_ROUTE_PREFIX
    allowed = set(range(parent + 11, parent + 14))
    allowed.update(range(start, end))
    allowed.update(range(candidate.CHECKSUM_OFFSET, candidate.CHECKSUM_OFFSET + 4))
    changed = {i for i, (a, b) in enumerate(zip(original, proposed)) if a != b}
    assert changed <= allowed, sorted(changed - allowed)[:8]
    checked = bytearray(proposed)
    checked[candidate.CHECKSUM_OFFSET : candidate.CHECKSUM_OFFSET + 4] = bytes(4)
    total = sum(checked) & 0xFFFF
    assert proposed[candidate.CHECKSUM_OFFSET : candidate.CHECKSUM_OFFSET + 2] == ((~total) & 0xFFFF).to_bytes(2, "little")
    assert proposed[candidate.CHECKSUM_OFFSET + 2 : candidate.CHECKSUM_OFFSET + 4] == total.to_bytes(2, "little")
    print("Stage-3 record-emitter route candidate builder: green")


if __name__ == "__main__":
    main()
