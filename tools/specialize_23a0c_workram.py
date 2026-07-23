#!/usr/bin/env python3
"""Specialize fixed-record accesses in native $023A0C for canonical work RAM.

The generated body derives A1 from A5+$3592 and walks exactly four $20-byte
records.  Production uses the canonical A5=$00F00000 work-RAM base.  Guard that
contract after recreating the skipped JSR return frame, then replace only A1
record accesses with the established bank-$40 word/byte helpers.  ROM-table
reads and indirect callback dispatch remain generic.

On a guard miss, resume the legal interpreter at $023A0C with the already
materialized return frame.  The guard therefore broadens no address-space
assumption beyond the production state it proves.
"""

from __future__ import annotations

import argparse
import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SOURCE = ROOT / "src/escbank4.pasm"
START_MARKER = "; --- transpiled from $023A0C"
END_MARKER = "    .org $A900"

GUARD_NEEDLE = """    jsl.l push32_l
    lda $34
    clc
    adc #$3592
"""

GUARD_REPLACEMENT = """    jsl.l push32_l
    ; A1 is fixed at A5+$3592 for four $20-byte records.  Prove the
    ; canonical work-RAM base before using the direct bank-$40 helpers.
    lda $34
    beq h23a0c_guard_a5lo
    jmp h23a0c_guard_fallback
h23a0c_guard_a5lo:
    lda $36
    cmp #$00F0
    beq h23a0c_guard_done
h23a0c_guard_fallback:
    lda #$3A0C
    sta $40
    lda #$0002
    sta $42
    jml.l inext
h23a0c_guard_done:
    lda $34
    clc
    adc #$3592
"""

READ_WORD = re.compile(
    r"    lda \$24\n"
    r"    clc\n"
    r"    adc (?P<disp>#[^\n]+)\n"
    r"    sta \$54\n"
    r"    lda \$26\n"
    r"    adc #\$0000\n"
    r"    sta \$52\n"
    r"    jsl\.l rdw_ea_l"
)

READ_BYTE = re.compile(
    r"    lda \$24\n"
    r"    clc\n"
    r"    adc (?P<disp>#[^\n]+)\n"
    r"    sta \$54\n"
    r"    lda \$26\n"
    r"    adc #\$0000\n"
    r"    sta \$52\n"
    r"    jsl\.l readbyte_l"
)

WRITE_WORD = re.compile(
    r"    lda \$24\n"
    r"    clc\n"
    r"    adc (?P<disp>#[^\n]+)\n"
    r"    sta \$54\n"
    r"    lda \$26\n"
    r"    adc #\$0000\n"
    r"    sta \$52\n"
    r"    jsl\.l writeword_l"
)

WRITE_BYTE = re.compile(
    r"    lda \$24\n"
    r"    clc\n"
    r"    adc (?P<disp>#[^\n]+)\n"
    r"    sta \$54\n"
    r"    lda \$26\n"
    r"    adc #\$0000\n"
    r"    sta \$52\n"
    r"    jsl\.l writebyte_l"
)

EXPECTED = {
    "word_reads": 13,
    "byte_reads": 5,
    "word_writes": 3,
    "byte_writes": 4,
}


def specialize(body: str) -> tuple[str, dict[str, int]]:
    if "h23a0c_guard_done" in body:
        raise RuntimeError("$023A0C body is already work-RAM-specialized")
    if body.count(GUARD_NEEDLE) != 1:
        raise RuntimeError("current $023A0C entry does not match the guard seam")
    body = body.replace(GUARD_NEEDLE, GUARD_REPLACEMENT, 1)

    counts: dict[str, int] = {}

    def read_word(match: re.Match[str]) -> str:
        return (
            "    lda $24\n"
            "    clc\n"
            f"    adc {match.group('disp')}\n"
            "    tax\n"
            "    jsl.l rdw40_l\n"
            "    ora #$0000"
        )

    def read_byte(match: re.Match[str]) -> str:
        return (
            "    lda $24\n"
            "    clc\n"
            f"    adc {match.group('disp')}\n"
            "    tax\n"
            "    jsl.l rdb40_l"
        )

    def write_word(match: re.Match[str]) -> str:
        return (
            "    lda $24\n"
            "    clc\n"
            f"    adc {match.group('disp')}\n"
            "    tax\n"
            "    lda $80\n"
            "    jsl.l wrw40_l"
        )

    def write_byte(match: re.Match[str]) -> str:
        return (
            "    lda $24\n"
            "    clc\n"
            f"    adc {match.group('disp')}\n"
            "    tax\n"
            "    lda $80\n"
            "    jsl.l wrb40_l"
        )

    body, counts["word_reads"] = READ_WORD.subn(read_word, body)
    body, counts["byte_reads"] = READ_BYTE.subn(read_byte, body)
    body, counts["word_writes"] = WRITE_WORD.subn(write_word, body)
    body, counts["byte_writes"] = WRITE_BYTE.subn(write_byte, body)
    if counts != EXPECTED:
        raise RuntimeError(
            f"unexpected $023A0C record access inventory: {counts}; "
            f"expected {EXPECTED}"
        )
    return body, counts


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", type=Path, default=DEFAULT_SOURCE)
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Rewrite the source in place; otherwise only validate the seam.",
    )
    args = parser.parse_args()
    text = args.source.read_text(encoding="utf-8")
    start = text.index(START_MARKER)
    end = text.index(END_MARKER, start)
    body, counts = specialize(text[start:end])
    rewritten = text[:start] + body + text[end:]
    print(
        "$023A0C guarded work-RAM specialization: "
        + ", ".join(f"{name}={count}" for name, count in counts.items())
        + f", source delta {len(rewritten) - len(text)} bytes"
    )
    if args.apply:
        args.source.write_text(rewritten, encoding="utf-8")
        print(f"updated {args.source}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
