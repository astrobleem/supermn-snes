#!/usr/bin/env python3
"""Focused regression for terminal word-shift CCR materialization.

The Stage 3 lookup leaf at $02E49C ends in ``lsl.w #2,d0`` followed by a
flag-neutral MOVEA/RTS epilogue.  Its native body must export the shift's
N/Z/V/C/X rather than the flags left by later address calculations.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import transpile as T  # noqa: E402


class Capture(T.Emit):
    def __init__(self) -> None:
        super().__init__(pfx="shiftccr")


def capture_materializer() -> list[str]:
    emitter = Capture()
    T.emit_ccr_native(emitter, "shift")
    return [line.strip() for line in emitter.lines]


def check_materializer(lines: list[str]) -> None:
    required = [
        "and #$0002",
        "sta $60",
        "and #$0080",
        "sta $70",
        "stz $72",
        "and #$0001",
        "sta $6E",
        "sta $A2",
    ]
    pos = -1
    for instruction in required:
        try:
            pos = lines.index(instruction, pos + 1)
        except ValueError as exc:
            raise AssertionError(
                f"shift CCR materializer is missing ordered instruction {instruction!r}"
            ) from exc

    # The emitted masks map the live 65816 N/Z/C bits to the project's CCR
    # variables.  Exercise all combinations, including representations where
    # Z/N are stored as their native masks rather than normalized booleans.
    for native_n in (0, 1):
        for native_z in (0, 1):
            for native_c in (0, 1):
                p = (native_n << 7) | (native_z << 1) | native_c
                got = {
                    "n": p & 0x80,
                    "z": p & 0x02,
                    "v": 0,
                    "c": p & 0x01,
                    "x": p & 0x01,
                }
                expected = {
                    "n": 0x80 if native_n else 0,
                    "z": 0x02 if native_z else 0,
                    "v": 0,
                    "c": native_c,
                    "x": native_c,
                }
                assert got == expected, (p, got, expected)


def check_real_leaf() -> None:
    root = Path(__file__).resolve().parents[1]
    result = subprocess.run(
        [
            sys.executable,
            str(root / "tools" / "transpile.py"),
            "02E49C",
            "--bank2",
            "--table",
            "--rom=a4",
            "--exitccr",
            "--xflag",
        ],
        cwd=root,
        check=True,
        capture_output=True,
        text=True,
    )
    body = result.stdout
    marker = "    stz $72\n    lda $50\n    and #$0001\n    sta $6E\n    sta $A2"
    assert body.count(marker) == 1, (
        "expected exactly one terminal-shift CCR materializer in $02E49C; "
        f"found {body.count(marker)}"
    )
    assert "=== all 9 instrs transpiled ===" in result.stderr


def main() -> None:
    lines = capture_materializer()
    check_materializer(lines)
    check_real_leaf()
    print("terminal word-shift CCR regression: PASS")


if __name__ == "__main__":
    main()
