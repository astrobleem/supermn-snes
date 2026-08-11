#!/usr/bin/env python3
"""Focused regression for complete-word TST N/Z after big-endian loads."""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import transpile as T  # noqa: E402
import gen_escbank6_bodies as G  # noqa: E402


def check_materializer() -> None:
    emitter = T.Emit(pfx="tstw")
    T.normalize_tst_nz(emitter, "w")
    assert emitter.lines == ["    inc a", "    dec a"], emitter.lines


def check_real_stage3_body() -> None:
    root = Path(__file__).resolve().parents[1]
    result = subprocess.run(
        [
            sys.executable,
            str(root / "tools" / "transpile.py"),
            "01337E",
            "--bank7",
            "--table",
            "--exitccr",
            "--xflag",
            "--accharge",
            "--restore-static-residue",
            "--restore-indirect-residue",
            "--bail",
        ],
        cwd=root,
        check=True,
        capture_output=True,
        text=True,
    )
    body = result.stdout
    assert "=== all 32 instrs transpiled ===" in result.stderr
    for displacement, branch in (("FFB0", "Lf1337e_1"), ("FF98", "Lf1337e_2")):
        marker = (
            f"    adc #${displacement}\n"
            "    tax\n"
            "    lda $400000,x\n"
            "    xba\n"
            "    inc a\n"
            "    dec a\n"
            f"    bne {branch}\n"
        )
        assert body.count(marker) == 1, (
            f"TST.W -${(-int(displacement, 16)) & 0xFFFF:04X}(A6) "
            "does not refresh full-word N/Z"
        )


def check_organic_enemy_body() -> None:
    """Keep the deployed $01770E continuation aligned with the generator.

    The organic Stage-1 fixture reaches TST.W $5E(A1) with $01FD.  XBA's
    byte-sized flags classify that value as negative unless the generated
    word materializer refreshes N/Z before the BLE pair.  The same fixture
    then executes MOVE.W D0,$36(A1) with $00BD; rereading the big-endian
    destination ends in XBA and must refresh full-word flags before BPL or
    native code spuriously negates D0 and overwrites the animation pointer.
    """

    root = Path(__file__).resolve().parents[1]
    command = [
        sys.executable,
        str(root / "tools" / "transpile.py"),
        "0176F6",
        "--bank6",
        "--coroutine",
        "--exitccr",
        "--xflag",
        "--workram=a1",
        "--bail",
        "--accharge",
        "--restore-indirect-residue",
        "--restore-static-residue",
        "--real-return-calls=01770C",
        "--jt=01772A:0:16,0177A4:0:16",
    ]
    generated = subprocess.run(
        command,
        cwd=root,
        check=True,
        capture_output=True,
        text=True,
    ).stdout
    routed = G.transpile(
        0x0176F6,
        "coroutine",
        [
            "--workram=a1",
            "--bail",
            "--accharge",
            "--restore-indirect-residue",
            "--restore-static-residue",
            "--real-return-calls=01770C",
            "--jt=01772A:0:16,0177A4:0:16",
        ],
    )
    deployed = (root / "src" / "escbank6.pasm").read_text(encoding="utf-8")
    marker = (
        "L176f6_177b6:\n"
        "    php\n"
        "    rep #$30\n"
        "    lda #$0002\n"
        "    jsr esc_ac_charge\n"
        "    plp\n"
        "    lda $24\n"
        "    clc\n"
        "    adc #$005E\n"
        "    tax\n"
        "    lda $400000,x\n"
        "    xba\n"
        "    inc a\n"
        "    dec a\n"
        "    beq Lf176f6_32\n"
        "    bmi Lf176f6_32\n"
    )
    assert generated.count(marker) == 1, (
        "generated $01770E TST.W $5E(A1) does not refresh full-word N/Z"
    )
    deployed_marker = marker.replace(
        "    jsr esc_ac_charge\n", "    jsr esc6_ac_charge\n"
    )
    assert deployed.count(deployed_marker) == 1, (
        "deployed $01770E TST.W $5E(A1) is stale or lacks full-word N/Z"
    )

    move_branch_marker = (
        "L176f6_177cc:\n"
        "    php\n"
        "    rep #$30\n"
        "    lda #$0002\n"
        "    jsr esc_ac_charge\n"
        "    plp\n"
        "    lda $00\n"
        "    pha\n"
        "    lda $24\n"
        "    clc\n"
        "    adc #$0036\n"
        "    tax\n"
        "    pla\n"
        "    xba\n"
        "    sta $400000,x\n"
        "    xba\n"
        "    lda $24\n"
        "    clc\n"
        "    adc #$0036\n"
        "    tax\n"
        "    lda $400000,x\n"
        "    xba\n"
        "    inc a\n"
        "    dec a\n"
        "    bmi Lf176f6_33\n"
    )
    assert generated.count(move_branch_marker) == 1, (
        "generated $01770E MOVE.W D0,$36(A1) branch does not refresh "
        "full-word N/Z"
    )
    deployed_move_marker = move_branch_marker.replace(
        "    jsr esc_ac_charge\n", "    jsr esc6_ac_charge\n"
    )
    assert deployed.count(deployed_move_marker) == 1, (
        "deployed $01770E MOVE.W D0,$36(A1) branch is stale or lacks "
        "full-word N/Z"
    )

    generated_rdw_labels = re.findall(
        r"    jsl\.l rdw_ea_l\n"
        r"    inc a\n"
        r"    dec a\n"
        r"    bne (Lf176f6_\d+)\n",
        generated,
    )
    assert len(generated_rdw_labels) == 2, (
        "generated $01770E TST.W callback paths lack full-word N/Z"
    )
    for label in generated_rdw_labels:
        branch_marker = (
            "    jsl.l rdw_ea_l\n"
            "    inc a\n"
            "    dec a\n"
            f"    bne {label}\n"
        )
        assert deployed.count(branch_marker) == 1, (
            f"deployed $01770E {label} TST.W path lacks full-word N/Z"
        )

    callback_blocks = (
        ("L176f6_17814:\n", "L176f6_17838:\n"),
        ("L176f6_17838:\n", "L176f6_1785c:\n"),
    )
    move_one = (
        "    lda #$0001\n"
        "    pha\n"
        "    ldx $24\n"
        "    pla\n"
        "    xba\n"
        "    sta $400000,x\n"
        "    xba\n"
        "    jmp h176f6_move_one_root\n"
    )
    for text, source_name in (
        (routed, "generator-transformed"),
        (deployed, "deployed"),
    ):
        for start_label, end_label in callback_blocks:
            start = text.find(start_label)
            end = text.find(end_label, start + len(start_label))
            assert start >= 0 and end >= 0, (
                f"{source_name} callback block labels changed: "
                f"{start_label.strip()}..{end_label.strip()}"
            )
            block = text[start:end]
            assert block.count("    jsl.l rdw_ea_l\n") == 1
            assert block.count(
                "    jmp h176f6_tstw_zero_root\n"
            ) == 1, (
                f"{source_name} {start_label.strip()} zero TST backedge "
                "does not publish CCR"
            )
            assert block.count(move_one) == 1, (
                f"{source_name} {start_label.strip()} MOVE.W #1 backedge "
                "does not publish CCR"
            )
        assert text.count("    jmp h176f6_tstw_zero_root\n") == 2
        assert text.count("    jmp h176f6_move_one_root\n") == 2

    helper_start = deployed.index("h176f6_tstw_zero_root:\n")
    helper_end = deployed.index(
        "h176f6_backedge_ccr_end:\n", helper_start
    )
    helper = deployed[helper_start:helper_end]
    expected_helper = (
        "h176f6_tstw_zero_root:\n"
        "    rep #$30\n"
        "    .a16\n"
        "    .i16\n"
        "    lda #$0002\n"
        "    sta $60\n"
        "    bra h176f6_backedge_common\n"
        "\n"
        "h176f6_move_one_root:\n"
        "    rep #$30\n"
        "    .a16\n"
        "    .i16\n"
        "    stz $60\n"
        "\n"
        "h176f6_backedge_common:\n"
        "    stz $70\n"
        "    stz $72\n"
        "    stz $6E\n"
        "    jmp L176f6_176f6\n"
    )
    assert helper == expected_helper, (
        "deployed $176F6 callback helper no longer publishes exact "
        "TST-zero/MOVE-one N/Z/V/C semantics"
    )
    assert "$A2" not in helper, (
        "$176F6 callback helper must preserve the 68000 X flag"
    )


def main() -> None:
    check_materializer()
    check_real_stage3_body()
    check_organic_enemy_body()
    print("complete-word TST N/Z regression: PASS")


if __name__ == "__main__":
    main()
