#!/usr/bin/env python3
"""Regression guard for the byte-minimal terminal-TST.B candidate builder."""

from __future__ import annotations

import hashlib
import subprocess
import sys
import tempfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
BUILDER = ROOT / "tools/build_2429c_tstb_ccr_candidate.py"
INPUT = ROOT / "build/interp-current-5c7e-before-vtime-esc9.sfc"


def main() -> None:
    with tempfile.TemporaryDirectory(prefix="supermn-2429c-tstb-") as temporary:
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
    differing = [i for i, (a, b) in enumerate(zip(original, candidate)) if a != b]
    allowed = set(range(0x2C868D, 0x2C8692))
    allowed.update(range(0x2C96E3, 0x2C96E8))
    allowed.update(range(0x2CFD00, 0x2CFD38))
    allowed.update(range(0xFFDC, 0xFFE0))
    assert set(differing) <= allowed, differing[:8]
    assert len(differing) == 66, len(differing)
    assert candidate[0x2C868D:0x2C8692] == bytes.fromhex("4c00fdeaea")
    assert candidate[0x2C96E3:0x2C96E8] == bytes.fromhex("4c1cfdeaea")
    assert candidate[0x2CFD00:0x2CFD38] == bytes.fromhex(
        "64706472646e646029ff00f00a298000f002e6704c9286e6604c2f8b"
        "64706472646e646029ff00f00a298000f002e6704ce896e6604c5e98"
    )
    checked = bytearray(candidate)
    checked[0xFFDC:0xFFE0] = bytes(4)
    total = sum(checked) & 0xFFFF
    assert candidate[0xFFDC:0xFFDE] == ((~total) & 0xFFFF).to_bytes(2, "little")
    assert candidate[0xFFDE:0xFFE0] == total.to_bytes(2, "little")
    print(
        "byte-minimal $02429C/$0259CA terminal-TST.B candidate: green "
        f"({hashlib.sha256(candidate).hexdigest()})"
    )


if __name__ == "__main__":
    main()
