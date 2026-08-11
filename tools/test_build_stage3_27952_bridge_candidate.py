#!/usr/bin/env python3
"""Regression guard for the byte-minimal $027952 direct-child builder."""

from __future__ import annotations

import hashlib
import subprocess
import sys
import tempfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
BUILDER = ROOT / "tools/build_stage3_27952_bridge_candidate.py"
INPUT = ROOT / "build/interp.sfc"
OLD = bytes.fromhex("a9ea7a8540a9020085425cb3d100")
NEW = bytes.fromhex("a9ea7a8540a9020085425c00c09f")
CHECKSUM_OFFSET = 0xFFDC
ACTIVE_SHA256 = "a9765fbfbd2a0863f093ff1bb887cfd422ecde26e3c46bae0afd56bf8b1dac60"


def main() -> None:
    assert hashlib.sha256(INPUT.read_bytes()).hexdigest() == ACTIVE_SHA256
    with tempfile.TemporaryDirectory(prefix="supermn-27952-bridge-") as temporary:
        output = Path(temporary) / "candidate.sfc"
        subprocess.run(
            [sys.executable, str(BUILDER), "--input", str(INPUT), "--output", str(output)],
            cwd=ROOT,
            check=True,
            capture_output=True,
            text=True,
        )
        original = INPUT.read_bytes()
        candidate = output.read_bytes()

    offset = original.index(OLD)
    assert original.count(OLD) == 1
    assert candidate[offset : offset + len(NEW)] == NEW
    assert candidate.count(OLD) == 0
    differing = [i for i, (a, b) in enumerate(zip(original, candidate)) if a != b]
    allowed = set(range(offset + 11, offset + 14))
    allowed.update(range(CHECKSUM_OFFSET, CHECKSUM_OFFSET + 4))
    assert set(differing) <= allowed, differing[:8]
    assert set(range(offset + 11, offset + 14)) <= set(differing)
    checked = bytearray(candidate)
    checked[CHECKSUM_OFFSET : CHECKSUM_OFFSET + 4] = bytes(4)
    total = sum(checked) & 0xFFFF
    assert candidate[CHECKSUM_OFFSET : CHECKSUM_OFFSET + 2] == ((~total) & 0xFFFF).to_bytes(
        2, "little"
    )
    assert candidate[CHECKSUM_OFFSET + 2 : CHECKSUM_OFFSET + 4] == total.to_bytes(2, "little")
    print(
        "byte-minimal $027952 direct-child candidate: green "
        f"({hashlib.sha256(candidate).hexdigest()})"
    )


if __name__ == "__main__":
    main()
