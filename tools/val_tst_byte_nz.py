#!/usr/bin/env python3
"""Focused codegen regression for signed branches after 68000 TST.B."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import transpile as T  # noqa: E402


NORMALIZE = (
    "    and #$00FF\n"
    "    eor #$0080\n"
    "    sec\n"
    "    sbc #$0080\n"
)


def check_materializer() -> None:
    emitter = T.Emit(pfx="tstb")
    T.normalize_tst_nz(emitter, "b")
    assert emitter.lines == [
        "    and #$00FF",
        "    eor #$0080",
        "    sec",
        "    sbc #$0080",
    ], emitter.lines


def check_organic_body() -> None:
    root = Path(__file__).resolve().parents[1]
    result = subprocess.run(
        [
            sys.executable,
            str(root / "tools" / "transpile.py"),
            "2335e",
            "--bank2",
            "--video",
        ],
        cwd=root,
        check=True,
        capture_output=True,
        text=True,
    )
    body = result.stdout
    assert "=== all 124 instrs transpiled ===" in result.stderr
    marker = "    jsl.l readbyte_l\n" + NORMALIZE
    assert body.count(marker) == 4, (
        "the four $02335E TST.B memory reads must normalize bit 7 "
        "before their fused branches"
    )

    deployed = (root / "src" / "escbank4.pasm").read_text(
        encoding="utf-8"
    )
    start = deployed.index(
        "; --- transpiled from $02335E (124 instrs) "
        "by tools/transpile.py [bank1] ---"
    )
    end = deployed.index("    .org $8E53", start)
    deployed_body = deployed[start:end]
    compact_call = "    jsr readbyte_tst\n    nop\n"
    assert deployed_body.count(compact_call) == 4, (
        "the four pinned $02335E TST.B reads must use the compact "
        "sign-normalizing helper"
    )
    helper = (
        "readbyte_tst_native:\n"
        "    jsl.l readbyte_l\n"
        + NORMALIZE
        + "    rts\n"
        "readbyte_tst_end:\n"
    )
    assert deployed.count(helper) == 1, (
        "the deployed compact TST.B helper does not match "
        "normalize_tst_nz('b')"
    )
    final_iteration = (
        "readbyte_tst:\n"
        "    .a16\n"
        "    .i16\n"
        "    lda $18\n"
        "    bne readbyte_tst_native\n"
        "    pla\n"
        "    lda #$3366\n"
        "    sta $40\n"
        "    lda #$0002\n"
        "    sta $42\n"
        "    jsr restore_2335e_call_residue\n"
        "    jml.l inext\n"
    )
    assert deployed.count(final_iteration) == 1, (
        "the final $02335E DBRA iteration no longer rejoins the interpreter "
        "before its first TST.B"
    )


def main() -> None:
    check_materializer()
    check_organic_body()
    print("byte TST signed-branch regression: PASS")


if __name__ == "__main__":
    main()
