#!/usr/bin/env python3
"""Generate the VTIME-only, interpreter-child `$02429C` root in bank $F3.

The production bank-$99 root is deliberately left byte-identical.  This copy
uses the transpiler's 35 exact original basic blocks, identifies each block by
ordinal at its existing charge seam, and flushes the parent ledger before all
eleven child transfers.  Children remain interpreted in this first common-
clock diagnostic so their work is charged by the per-fetch clock rather than
silently omitted or double-counted by a partial native ledger.
"""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

import audit_stage3_2429c_charge_blocks as audit


ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "src/vtime_esc5_root.pasm"
TRANSPILE = ROOT / "tools/transpile.py"
ESCBANK5 = ROOT / "src/escbank5.pasm"

FLAGS = (
    "--bank5",
    "--coroutine",
    "--xflag",
    "--exitccr",
    "--accharge",
    "--restore-static-residue",
)

REQUIRED_EQUATES = (
    "inext",
    "push32_l",
    "readbyte_l",
    "rdw_ea_l",
    "ojmp_hook",
    "ibridge",
)


def imported_equates() -> str:
    source = ESCBANK5.read_text(encoding="utf-8")
    lines: list[str] = []
    for name in REQUIRED_EQUATES:
        match = re.search(rf"(?m)^{re.escape(name)}=\$[0-9A-Fa-f]+$", source)
        if match is None:
            raise RuntimeError(f"missing current bank-$99 import {name}")
        lines.append(match.group(0))
    return "\n".join(lines)


def transpile() -> str:
    result = subprocess.run(
        [sys.executable, str(TRANSPILE), "02429c", *FLAGS],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=True,
    )
    if (
        "all 78 instrs transpiled" not in result.stderr
        or "UNIMPLEMENTED" in result.stdout
        or "BAIL" in result.stderr
    ):
        raise RuntimeError(result.stdout + result.stderr)
    return result.stdout.rstrip()


def ordinal_charges(body: str) -> str:
    blocks = audit.collect()["blocks"]
    pattern = re.compile(
        r"(?P<indent>    )lda #\$(?P<count>[0-9A-Fa-f]{4})\n"
        r"    jsr esc_ac_charge\n"
    )
    matches = list(pattern.finditer(body))
    if len(matches) != len(blocks) != 35:
        raise RuntimeError(f"unexpected root charge cardinality: {len(matches)}")
    pieces: list[str] = []
    cursor = 0
    for ordinal, (match, block) in enumerate(zip(matches, blocks), 1):
        observed_count = int(match.group("count"), 16)
        expected_count = int(block["logical_instruction_count"])
        if observed_count != expected_count:
            raise RuntimeError(
                f"block {ordinal} charge shape changed: "
                f"{observed_count} != {expected_count}"
            )
        pieces.append(body[cursor : match.start()])
        pieces.append(
            f"    lda #${ordinal:04X}\n"
            "    jsr vtime_esc5_charge_gateway\n"
        )
        cursor = match.end()
    pieces.append(body[cursor:])
    return "".join(pieces)


def repair_terminal_tst_byte(body: str) -> str:
    old = """    jsl.l readbyte_l
    and #$00FF
    eor #$0080
    sec
    sbc #$0080
    bne Lf2429c_3
    jmp L2429c_243da
Lf2429c_3:
"""
    new = """    jsl.l readbyte_l
    jmp vtime_h2429c_tst_byte19_branch
Lf2429c_3:
"""
    if body.count(old) != 1:
        raise RuntimeError("$02429C terminal TST.B repair seam changed")
    return body.replace(old, new, 1)


def child_returns() -> list[int]:
    """Return the eleven architectural post-call PCs in source order."""

    returns: list[int] = []
    for block in audit.collect()["blocks"]:
        terminal = block["terminal"]
        if int(terminal["pc"], 16) in audit.CHILD_HANDOFFS:
            returns.append(int(block["original_end_pc_exclusive"], 16))
    if len(returns) != 11 or len(set(returns)) != 11:
        raise RuntimeError(f"unexpected $02429C child returns: {returns}")
    return returns


def architectural_child_returns(body: str) -> str:
    """Replace private bank-$99 continuations with genuine 68000 returns.

    Ten static call bridges already push through $54/$56.  The indirect
    bridge normally leaves that push to ``ibridge``; materialize it here as
    well, then publish the dynamic child PC before the parent clock flush.
    An interpreted RTS later reaches the VTIME-only sparse return dispatcher.
    """

    returns = child_returns()
    static_pattern = re.compile(
        r"(?P<comment>    ; CALL-BRIDGE[^\n]*resume br2429c_(?P<ordinal>\d+)\n)"
        r"    lda #br2429c_(?P=ordinal)\n"
        r"    sta \$54\n"
        r"    lda #\$00FA\n"
        r"    sta \$56\n"
        r"    jsl\.l push32_l\n"
    )
    static_matches = list(static_pattern.finditer(body))
    if len(static_matches) != 10:
        raise RuntimeError(
            f"$02429C static child bridge count changed: {len(static_matches)}"
        )
    pieces: list[str] = []
    cursor = 0
    for match in static_matches:
        ordinal = int(match.group("ordinal"))
        return_pc = returns[ordinal - 1]
        pieces.append(body[cursor : match.start()])
        pieces.append(
            match.group("comment")
            + f"    lda #${return_pc & 0xFFFF:04X}\n"
            "    sta $54\n"
            f"    lda #${return_pc >> 16:04X}\n"
            "    sta $56\n"
            "    jsl.l push32_l\n"
        )
        cursor = match.end()
    pieces.append(body[cursor:])
    body = "".join(pieces)

    indirect_pattern = re.compile(
        r"(?P<comment>    ; INDIRECT-BRIDGE[^\n]*resume br2429c_8\n)"
        r"    lda #br2429c_8\n"
        r"    sta \$40\n"
        r"    lda #\$00FA\n"
        r"    sta \$42\n"
        r"    lda \$20\n"
        r"    sta \$52\n"
        r"    lda \$22\n"
        r"    sta \$50\n"
        r"    jml\.l ibridge\n"
    )
    indirect_matches = list(indirect_pattern.finditer(body))
    if len(indirect_matches) != 1:
        raise RuntimeError(
            "$02429C indirect child bridge shape changed: "
            f"{len(indirect_matches)}"
        )
    indirect_return = returns[7]
    body = indirect_pattern.sub(
        lambda match: (
            match.group("comment")
            + f"    lda #${indirect_return & 0xFFFF:04X}\n"
            "    sta $54\n"
            f"    lda #${indirect_return >> 16:04X}\n"
            "    sta $56\n"
            "    jsl.l push32_l\n"
            "    lda $20\n"
            "    sta $40\n"
            "    lda $22\n"
            "    sta $42\n"
            "    jmp vtime_esc5_ojmp_gateway\n"
        ),
        body,
        count=1,
    )
    return body


def transform() -> str:
    body = ordinal_charges(transpile())
    body = repair_terminal_tst_byte(body)
    body = architectural_child_returns(body)
    if body.count("entry_2429c:") != 1:
        raise RuntimeError("missing unique $02429C entry")
    body = body.replace(
        "entry_2429c:\n",
        "    .org $8000\n.a16\n.i16\nvtime_entry_2429c:\n",
        1,
    )
    if body.count("jml.l ojmp_hook") != 10:
        raise RuntimeError("$02429C static child-transfer count changed")
    body = body.replace(
        "jml.l ojmp_hook", "jmp vtime_esc5_ojmp_gateway"
    )
    if "jml.l ibridge" in body:
        raise RuntimeError("$02429C retained its private indirect bridge")
    if body.count("jml.l inext") != 1:
        raise RuntimeError("$02429C final interpreter handoff count changed")
    body = body.replace(
        "jml.l inext", "jmp vtime_esc5_inext_gateway", 1
    )
    return body


TAIL = r"""

; Preserve the active a976 terminal TST.B CCR repair in the diagnostic copy.
vtime_h2429c_tst_byte19_branch:
    stz $70
    stz $72
    stz $6E
    stz $60
    and #$00FF
    beq vtime_h2429c_tst_byte19_zero
    and #$0080
    beq vtime_h2429c_tst_byte19_nonzero
    inc $70
vtime_h2429c_tst_byte19_nonzero:
    jmp Lf2429c_3
vtime_h2429c_tst_byte19_zero:
    inc $60
    jmp L2429c_243da

; The generated block prologue has PHP immediately before the local JSR.
; A due result discards both frames and resumes the interpreter at the exact
; original block PC selected by the F2 ledger.
vtime_esc5_charge_gateway:
    rep #$30
    jsl.l VTIME_ESC5_CHARGE
    cmp #$0001
    beq vtime_esc5_charge_due
    rts
vtime_esc5_charge_due:
    pla
    plp
    jml.l inext

; Each child bridge has already pushed its genuine 68000 return and published
; the child PC.  Flush the completed parent JSR/BSR block, then deliberately
; interpret the direct child.  A due result keeps that exact PC/stack state
; for IRQ delivery; both paths use inext and therefore bypass native dispatch
; for the child entry itself.
vtime_esc5_ojmp_gateway:
    rep #$30
    jsl.l VTIME_ESC5_FINISH
    stz $071A
    jml.l inext

; The terminal trap/yield PC is already in $40:$42.  Commit the last block and
; leave through the ordinary interpreter path regardless of whether it became
; the deadline-crossing block.
vtime_esc5_inext_gateway:
    rep #$30
    jsl.l VTIME_ESC5_FINISH
    jml.l inext

; op_rts has already consumed the genuine child return when the VTIME-only
; bank-$00 patch reaches this front end.  Child execution temporarily clears
; the native gate, so recognize these exact bank-$02 returns before consulting
; that gate, restore the mode-appropriate value, and resume the matching
; bank-$F3 continuation.  Ordinary VTIME restores the native gate; the explicit
; interpreter-only diagnostic must leave it clear.  Every miss reproduces
; op_rts_sentinel/op_rts_norm: $00FF is a local bank-$00 continuation, gate-on
; uses xlat_dispatch, and gate-off interprets.
vtime_esc5_return_dispatch:
    rep #$30
    lda $42
    cmp #$0002
    beq vtime_esc5_return_bank2
    jmp vtime_esc5_return_miss
vtime_esc5_return_bank2:
    lda $40
""" + "".join(
    f"    cmp #${return_pc & 0xFFFF:04X}\n"
    f"    bne vtime_esc5_return_next_{ordinal}\n"
    f"    jsr vtime_esc5_restore_gate\n"
    f"    jmp br2429c_{ordinal}\n"
    f"vtime_esc5_return_next_{ordinal}:\n"
    for ordinal, return_pc in enumerate(child_returns(), 1)
) + r"""vtime_esc5_return_miss:
    lda $42
    cmp #$00FF
    bne vtime_esc5_return_normal
    jmp ($0040)
vtime_esc5_return_normal:
    lda $071A
    beq vtime_esc5_return_interpret
    jml.l $94F900
vtime_esc5_return_interpret:
    jml.l inext

; The enable byte is followed immediately by executable code, so mask only the
; interpreter-only bit from the 16-bit long read.  Normal VTIME keeps the
; established native child/parent behavior; flag $0002 prevents this diagnostic
; root from leaking a global $071A=1 back into an interpreter-only campaign.
vtime_esc5_restore_gate:
    lda.l VTIME_ENABLE
    and #VTIME_FLAG_INTERPRETER_ONLY
    bne vtime_esc5_restore_gate_off
    lda #$0001
    sta $071A
    rts
vtime_esc5_restore_gate_off:
    stz $071A
    rts
vtime_esc5_return_dispatch_end:
vtime_esc5_root_end:
"""


def generate() -> str:
    return (
        "; Generated by tools/gen_vtime_esc5_root.py; do not edit.\n"
        "; VTIME-only bank $F3 diagnostic; production routing remains bank $99.\n"
        + imported_equates()
        + "\nVTIME_ESC5_CHARGE=$F28900\n"
        + "VTIME_ESC5_FINISH=$F28B00\n\n"
        + "VTIME_ENABLE=$F28000\n"
        + "VTIME_FLAG_INTERPRETER_ONLY=$0002\n\n"
        + ".snes\n"
        + transform()
        + TAIL
    )


def main() -> int:
    content = generate()
    OUTPUT.write_text(content, encoding="utf-8")
    print(
        "gen_vtime_esc5_root: generated 35-block/11-handoff "
        "interpreter-child diagnostic"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
