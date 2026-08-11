#!/usr/bin/env python3
"""Regression guard for the parent-local `$02E524` candidate bridge."""

import hashlib
import subprocess
import sys
import tempfile
from pathlib import Path

import build_stage3_parent_local_draw_candidate as candidate


ROOT = Path(__file__).resolve().parents[1]
INPUT = ROOT / "build" / "interp-stage3-parent-local-record-emitter-current-a976-v1.sfc"
BUILDER = ROOT / "tools" / "build_stage3_parent_local_draw_candidate.py"


def main() -> None:
    original = INPUT.read_bytes()
    assert hashlib.sha256(original).hexdigest() == candidate.INPUT_SHA256
    with tempfile.TemporaryDirectory(prefix="supermn-parent-local-draw-") as temporary:
        output = Path(temporary) / "candidate.sfc"
        subprocess.run([sys.executable, str(BUILDER), "--input", str(INPUT), "--output", str(output)], cwd=ROOT, check=True)
        proposed = output.read_bytes()
    offset = 0x2A39C0
    assert proposed[offset:offset + len(candidate.NEW)] == candidate.NEW
    allowed = set(range(offset + 11, offset + 14))
    allowed.update(range(candidate.base.CHECKSUM_OFFSET, candidate.base.CHECKSUM_OFFSET + 4))
    assert {i for i, (a, b) in enumerate(zip(original, proposed)) if a != b} <= allowed
    print("Stage-3 parent-local draw candidate builder: green")


if __name__ == "__main__":
    main()
