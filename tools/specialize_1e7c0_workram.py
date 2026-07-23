#!/usr/bin/env python3
"""Specialize guarded A0 reads in the generated $01E7C0 native body.

The object-list contract makes every non-null A0 a bounded $F0xxxx work-RAM
record.  A single read-only entry guard proves that contract for all eight list
slots; the hot body can then replace generic ROM/IO-aware reads through A0 with
direct bank-$40 loads.  A guard miss re-enters the interpreter at $01E7C0 before
any emulated register or memory write.

This deliberately rewrites only the already-generated escbank4 body.  It does
not regenerate that body with the newer transpiler, whose output has unrelated
semantic and layout changes.
"""

from __future__ import annotations

import argparse
import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SOURCE = ROOT / "src/escbank4.pasm"
START_MARKER = "; --- transpiled from $01E7C0"
END_MARKER = "; esc_udiv"
EXPECTED_WORD_READS = 107
EXPECTED_BYTE_READS = 47

ENTRY_NEEDLE = """entry_1e7c0:
    rep #$30
    ; coroutine task body: NO return-push (entered by the op_rte resume hook, not a jsr)
"""

ENTRY_REPLACEMENT = """entry_1e7c0:
    rep #$30
    ; Guard the A0 work-RAM specialization before the original body performs
    ; any emulated register or memory write.  A5 must be the canonical work
    ; base; A6 owns the eight-pointer list at [A6-$20].  Every non-null record
    ; must be bank $F0 and leave room for the body's highest $6E byte access.
    lda $34
    beq h1e7c0_guard_a5lo
    jmp h1e7c0_guard_fallback
h1e7c0_guard_a5lo:
    lda $36
    cmp #$00F0
    beq h1e7c0_guard_a5hi
    jmp h1e7c0_guard_fallback
h1e7c0_guard_a5hi:
    lda $3A
    cmp #$00F0
    beq h1e7c0_guard_a6bank
    jmp h1e7c0_guard_fallback
h1e7c0_guard_a6bank:
    lda $38
    cmp #$0020
    bcs h1e7c0_guard_list
    jmp h1e7c0_guard_fallback
h1e7c0_guard_list:
    sec
    sbc #$0020
    sta $80
    ldy #$0008
h1e7c0_guard_slot:
    ldx $80
    lda $400000,x
    xba
    sta $82
    inx
    inx
    lda $400000,x
    xba
    sta $84
    ora $82
    beq h1e7c0_guard_next
    lda $82
    cmp #$00F0
    beq h1e7c0_guard_ptrbank
    jmp h1e7c0_guard_fallback
h1e7c0_guard_ptrbank:
    lda $84
    cmp #$FF92
    bcc h1e7c0_guard_next
    jmp h1e7c0_guard_fallback
h1e7c0_guard_next:
    lda $80
    clc
    adc #$0004
    sta $80
    dey
    bne h1e7c0_guard_slot
    jmp h1e7c0_guard_done
h1e7c0_guard_fallback:
    lda #$E7C0
    sta $40
    lda #$0001
    sta $42
    jml.l inext
h1e7c0_guard_done:
    ; coroutine task body: NO return-push (entered by the op_rte resume hook, not a jsr)
"""

READ_PATTERN = re.compile(
    r"    lda \$20\n"
    r"    clc\n"
    r"    adc (?P<disp>#[^\n]+)\n"
    r"    sta \$54\n"
    r"    lda \$22\n"
    r"    adc #\$0000\n"
    r"    sta \$52\n"
    r"    jsl\.l (?P<helper>readbyte_l|rdw_ea_l)"
)


def specialize(body: str) -> tuple[str, int, int]:
    if "h1e7c0_guard_done" in body:
        raise RuntimeError("$01E7C0 body is already work-RAM-specialized")
    if body.count(ENTRY_NEEDLE) != 1:
        raise RuntimeError("current $01E7C0 entry does not match the guarded rewrite seam")
    body = body.replace(ENTRY_NEEDLE, ENTRY_REPLACEMENT, 1)
    word_reads = 0
    byte_reads = 0

    def replace(match: re.Match[str]) -> str:
        nonlocal word_reads, byte_reads
        helper = match.group("helper")
        if helper == "rdw_ea_l":
            word_reads += 1
            # XBA sets native N/Z from only the exchanged low byte.  rdw_ea's
            # final 16-bit ORA set N/Z from the complete 68K word, and some
            # generated branches consume those flags immediately.
            tail = "    xba\n    ora #$0000"
        else:
            byte_reads += 1
            tail = "    and #$00FF"
        return (
            "    lda $20\n"
            "    clc\n"
            f"    adc {match.group('disp')}\n"
            "    tax\n"
            "    lda $400000,x\n"
            f"{tail}"
        )

    body = READ_PATTERN.sub(replace, body)
    if (word_reads, byte_reads) != (EXPECTED_WORD_READS, EXPECTED_BYTE_READS):
        raise RuntimeError(
            "unexpected $01E7C0 A0 read inventory: "
            f"word={word_reads}, byte={byte_reads}; expected "
            f"{EXPECTED_WORD_READS}/{EXPECTED_BYTE_READS}"
        )
    return body, word_reads, byte_reads


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", type=Path, default=DEFAULT_SOURCE)
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Rewrite the source in place; without this flag, validate and report only.",
    )
    args = parser.parse_args()
    text = args.source.read_text()
    start = text.index(START_MARKER)
    end = text.index(END_MARKER, start)
    body, word_reads, byte_reads = specialize(text[start:end])
    rewritten = text[:start] + body + text[end:]
    print(
        f"$01E7C0 guarded A0 specialization: {word_reads} word reads, "
        f"{byte_reads} byte reads, source delta {len(rewritten) - len(text)} bytes"
    )
    if args.apply:
        args.source.write_text(rewritten)
        print(f"updated {args.source}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
