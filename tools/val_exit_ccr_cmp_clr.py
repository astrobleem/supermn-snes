#!/usr/bin/env python3
"""Focused regression for CMP/X preservation and terminal CLR exit CCR.

Stage 3 leaf $02F542 exposed two generic ``--exitccr`` failures:

* a CMP-fed branch to RTS exported subtract-style C/X and corrupted X; and
* the in-range fallthrough ended in CLR.W D7, whose Z=1 result was never
  materialized before the native RTS machinery destroyed the host flags.

The organic $0133EA collision pass then exposed the equivalent loop form:
``CLR.W $E(A1); DBRA; RTS``.  DBRA preserves the preceding CLR flags, so the
transpiler must materialize the constant CLR result on the exhausted edge.

This guard checks the actual materializers and both actual generated bodies.
Exact MAME/native-off/native-on fixture differential remains the integration
gate; this script makes the code-generation contract cheap to rerun.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import transpile as T  # noqa: E402


class Capture(T.Emit):
    def __init__(self, pfx: str) -> None:
        super().__init__(pfx=pfx)


def stripped(emitter: T.Emit) -> list[str]:
    return [line.strip() for line in emitter.lines]


def check_compare_vs_sub_x() -> None:
    cmp_emitter = Capture("cmp")
    T.emit_ccr_native(cmp_emitter, "signed_cmp")
    cmp_lines = stripped(cmp_emitter)
    assert "sta $6E" in cmp_lines, "CMP exit must export C"
    assert "sta $A2" not in cmp_lines, "CMP exit must preserve X"

    sub_emitter = Capture("sub")
    T.emit_ccr_native(sub_emitter, "signed")
    sub_lines = stripped(sub_emitter)
    c_index = sub_lines.index("sta $6E")
    assert sub_lines[c_index + 1] == "sta $A2", "SUB exit must export X=C"


def check_zero_materializer() -> None:
    emitter = Capture("clr")
    T.emit_ccr_from_value(emitter, ("imm", 0, "w"))
    lines = stripped(emitter)
    expected = [
        "lda #$0000",
        "sta $70",
        "stz $72",
        "stz $6E",
        "lda #$0001",
        "sta $60",
    ]
    assert lines == expected, (lines, expected)
    assert "sta $A2" not in lines, "CLR must preserve X"


def check_real_stage3_leaf() -> None:
    root = Path(__file__).resolve().parents[1]
    result = subprocess.run(
        [
            sys.executable,
            str(root / "tools" / "transpile.py"),
            "02F542",
            "--bank7",
            "--table",
            "--exitccr",
            "--xflag",
            "--accharge",
            "--restore-static-residue",
        ],
        cwd=root,
        check=True,
        capture_output=True,
        text=True,
    )
    body = result.stdout
    assert "=== all 11 instrs transpiled ===" in result.stderr
    assert body.count("    sta $6E\n") == 3, (
        "expected exactly three CMP exit materializers"
    )
    assert "    sta $A2\n" not in body, (
        "$02F542 contains no X-setting 68000 instruction"
    )
    clr_marker = (
        "L2f542_2f566:\n"
        "    php\n"
        "    rep #$30\n"
        "    lda #$0001\n"
        "    jsr esc_ac_charge\n"
        "    plp\n"
        "    lda #$0000\n"
        "    sta $1C\n"
        "    lda #$0000\n"
        "    sta $70\n"
        "    stz $72\n"
        "    stz $6E\n"
        "    lda #$0001\n"
        "    sta $60\n"
    )
    assert body.count(clr_marker) == 1, (
        "terminal CLR.W D7 must export N=0,Z=1,V=0,C=0 before RTS"
    )


def check_real_stage3_clr_dbra_exit() -> None:
    root = Path(__file__).resolve().parents[1]
    result = subprocess.run(
        [
            sys.executable,
            str(root / "tools" / "transpile.py"),
            "0133EA",
            "--bank7",
            "--table",
            "--exitccr",
            "--xflag",
            "--accharge",
            "--restore-static-residue",
        ],
        cwd=root,
        check=True,
        capture_output=True,
        text=True,
    )
    body = result.stdout
    assert "=== all 37 instrs transpiled ===" in result.stderr
    marker = (
        "Lf133ea_9:\n"
        "    lda #$0000\n"
        "    sta $70\n"
        "    stz $72\n"
        "    stz $6E\n"
        "    lda #$0001\n"
        "    sta $60\n"
    )
    assert body.count(marker) == 1, (
        "$0133EA CLR.W/DBRA exhausted edge must export "
        "N=0,Z=1,V=0,C=0 before RTS"
    )
    assert "    sta $A2\n" in body, (
        "$0133EA contains arithmetic that updates X; regression must only "
        "prove the terminal CLR materializer leaves it untouched"
    )


def main() -> None:
    check_compare_vs_sub_x()
    check_zero_materializer()
    check_real_stage3_leaf()
    check_real_stage3_clr_dbra_exit()
    print("CMP/X and terminal-CLR/DBRA exit-CCR regression: PASS")


if __name__ == "__main__":
    main()
