#!/usr/bin/env python3
"""Focused regression for MOVE.B-to-Dn flags consumed by a fused branch.

The organic $01EA40 path preserves D3[31:8], as required by MOVE.B, while the
following BEQ must consume N/Z from only the byte that was moved.  The pinned
bank-$98 body uses an eight-byte compact form; the general transpiler has more
room and uses the normal byte-N/Z materializer.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PROGRAM = ROOT / "data/superman_m68k.bin"
SOURCE = ROOT / "src/escbank4.pasm"


def meaningful_lines(text: str) -> list[str]:
    return [
        line.strip()
        for line in text.splitlines()
        if line.strip() and not line.lstrip().startswith(";")
    ]


def require_contiguous(lines: list[str], expected: list[str], context: str) -> None:
    for index in range(len(lines) - len(expected) + 1):
        if lines[index : index + len(expected)] == expected:
            return
    raise AssertionError(
        f"{context} does not contain the required sequence:\n"
        + "\n".join(expected)
    )


def check_arcade_instruction() -> None:
    program = PROGRAM.read_bytes()
    observed = program[0x01EA3E : 0x01EA48]
    expected = bytes.fromhex("1C14162C00016700016C")
    assert observed == expected, (
        "$01EA3E arcade bytes changed: "
        f"expected {expected.hex().upper()}, observed {observed.hex().upper()}"
    )


def check_general_codegen() -> None:
    result = subprocess.run(
        [
            sys.executable,
            str(ROOT / "tools/transpile.py"),
            "01E7C0",
            "--bank1",
            "--coroutine",
            "--bail",
            "--jt=1EE6C:-16:0,1F0B6:0:6",
            "--escapes=D96",
            "--restore-static-residue",
            "--restore-indirect-residue",
        ],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    assert "=== all 751 instrs transpiled ===" in result.stderr
    block = result.stdout.split("L1e7c0_1ea3e:\n", 1)[1].split(
        "Lf1e7c0_80:\n", 1
    )[0]
    require_contiguous(
        meaningful_lines(block),
        [
            "sep #$20",
            "sta $0C",
            "rep #$20",
            "lda $0C",
            "and #$00FF",
            "eor #$0080",
            "sec",
            "sbc #$0080",
            "bne Lf1e7c0_80",
            "jmp L1e7c0_1ebb2",
        ],
        "general $01EA40 MOVE.B/BEQ codegen",
    )


def check_pinned_body() -> None:
    source = SOURCE.read_text(encoding="utf-8")
    block = source.split("L1e7c0_1ea3e:\n", 1)[1].split(
        "Lf1e7c0_80:\n", 1
    )[0]
    lines = meaningful_lines(block)
    require_contiguous(
        lines,
        [
            "sep #$20",
            "sta $0C",
            "lda $0C",
            "rep #$20",
            "bne Lf1e7c0_80",
            "jmp L1e7c0_1ebb2",
        ],
        "pinned bank-$98 $01EA40 MOVE.B/BEQ body",
    )
    require_contiguous(
        lines,
        ["sep #$20", "sta $0C", "lda $0C", "rep #$20"],
        "compact byte-sized N/Z refresh",
    )


def main() -> None:
    check_arcade_instruction()
    check_general_codegen()
    check_pinned_body()
    print("MOVE.B fused-branch byte N/Z regression: PASS")


if __name__ == "__main__":
    main()
