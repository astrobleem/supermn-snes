#!/usr/bin/env python3
"""Extend the guarded $01E7C0 work-RAM specialization.

The first specialization proves the eight A0 list entries are bounded F0
work-RAM records.  This pass extends that read-only entry guard to the three
sub-record pointers at A0+$46/$4A/$4E, then folds the remaining generic A1,
A2, A3, and A5 reads plus A0/A5 byte writes that are covered by those guards.

The generated body is intentionally rewritten in place instead of regenerated;
its historical transpiler invocation predates unrelated code-generator changes.
"""

from __future__ import annotations

import argparse
import re
from collections import Counter
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SOURCE = ROOT / "src/escbank4.pasm"
START_MARKER = "; --- transpiled from $01E7C0"
END_MARKER = "; esc_udiv"

GUARD_NEEDLE = """h1e7c0_guard_ptrbank:
    lda $84
    cmp #$FF92
    bcc h1e7c0_guard_next
    jmp h1e7c0_guard_fallback
h1e7c0_guard_next:
"""

GUARD_REPLACEMENT = """h1e7c0_guard_ptrbank:
    lda $84
    cmp #$FF92
    bcc h1e7c0_guard_subrecords
    jmp h1e7c0_guard_fallback
h1e7c0_guard_subrecords:
    ; Every hot A2/A3 record access is at most +$0E (a word), so require
    ; each object-owned sub-record pointer to be F0:0000..F0:FFF0.  A4 also
    ; originates at +$4E on the work-record paths; validating it here keeps
    ; the complete object contract explicit even though ROM-script A4 reads
    ; remain on the generic helper.
    ldx $84
    lda $400046,x
    xba
    cmp #$00F0
    beq h1e7c0_guard_a2bank
    jmp h1e7c0_guard_fallback
h1e7c0_guard_a2bank:
    lda $400048,x
    xba
    cmp #$FFF1
    bcc h1e7c0_guard_a3
    jmp h1e7c0_guard_fallback
h1e7c0_guard_a3:
    lda $40004A,x
    xba
    cmp #$00F0
    beq h1e7c0_guard_a3bank
    jmp h1e7c0_guard_fallback
h1e7c0_guard_a3bank:
    lda $40004C,x
    xba
    cmp #$FFF1
    bcc h1e7c0_guard_a4
    jmp h1e7c0_guard_fallback
h1e7c0_guard_a4:
    lda $40004E,x
    xba
    cmp #$00F0
    beq h1e7c0_guard_a4bank
    jmp h1e7c0_guard_fallback
h1e7c0_guard_a4bank:
    lda $400050,x
    xba
    cmp #$FFF1
    bcc h1e7c0_guard_next
    jmp h1e7c0_guard_fallback
h1e7c0_guard_next:
"""

LOOP_NEEDLE = """    dey
    bne h1e7c0_guard_slot
    jmp h1e7c0_guard_done
"""

LOOP_REPLACEMENT = """    dey
    beq h1e7c0_guard_done
    jmp h1e7c0_guard_slot
"""

READ_PATTERN = re.compile(
    r"    lda \$(?P<lo>24|28|2C|34)\n"
    r"    clc\n"
    r"    adc (?P<disp>[^\n]+)\n"
    r"    sta \$54\n"
    r"    lda \$(?P<hi>26|2A|2E|36)\n"
    r"    adc #\$0000\n"
    r"    sta \$52\n"
    r"    jsl\.l (?P<helper>rdw_ea_l|readbyte_l)"
)

WRITE_PATTERN = re.compile(
    r"    lda \$(?P<lo>20|34)\n"
    r"    clc\n"
    r"    adc (?P<disp>[^\n]+)\n"
    r"    sta \$54\n"
    r"    lda \$(?P<hi>22|36)\n"
    r"    adc #\$0000\n"
    r"    sta \$52\n"
    r"    jsl\.l writebyte_l"
)

EXPECTED_READS = Counter(
    {
        ("24", "26", "rdw_ea_l"): 2,
        ("28", "2A", "rdw_ea_l"): 5,
        ("28", "2A", "readbyte_l"): 1,
        ("2C", "2E", "rdw_ea_l"): 6,
        ("2C", "2E", "readbyte_l"): 1,
        ("34", "36", "readbyte_l"): 8,
    }
)
EXPECTED_WRITES = Counter(
    {
        ("20", "22", "writebyte_l"): 6,
        ("34", "36", "writebyte_l"): 8,
    }
)

BTST11_LABELS = (
    "L1e7c0_1f104:",
    "Lf1e7c0_219:",
    "L1e7c0_1f11a:",
    "L1e7c0_1f170:",
)


def specialize(body: str) -> tuple[str, Counter, Counter]:
    if "h1e7c0_guard_subrecords" in body:
        raise RuntimeError("$01E7C0 body is already v2 work-RAM-specialized")
    if body.count(GUARD_NEEDLE) != 1:
        raise RuntimeError("current $01E7C0 guard does not match the v2 rewrite seam")
    body = body.replace(GUARD_NEEDLE, GUARD_REPLACEMENT, 1)
    if body.count(LOOP_NEEDLE) != 1:
        raise RuntimeError("current $01E7C0 guard loop does not match the v2 rewrite seam")
    body = body.replace(LOOP_NEEDLE, LOOP_REPLACEMENT, 1)
    # This historical body predates the transpiler fix for immediate BTST on
    # data-register destinations.  Capstone prints ``btst.b #$b,Dn``, but a
    # register target uses bit 11 (mask $0800), not memory-form bit 3.  Keep
    # the four original $01F10C/$01F112/$01F11A/$01F172 sites explicit.
    for label in BTST11_LABELS:
        start = body.index(label)
        end = body.find("\nL", start + len(label))
        if end < 0:
            end = len(body)
        block = body[start:end]
        if block.count("    and #$0008") != 1:
            raise RuntimeError(f"unexpected BTST #11 lowering in {label}")
        body = body[:start] + block.replace(
            "    and #$0008", "    and #$0800", 1
        ) + body[end:]

    reads: Counter = Counter()

    def replace_read(match: re.Match[str]) -> str:
        key = (match.group("lo"), match.group("hi"), match.group("helper"))
        reads[key] += 1
        tail = (
            "    xba\n    ora #$0000"
            if match.group("helper") == "rdw_ea_l"
            else "    and #$00FF"
        )
        return (
            f"    lda ${match.group('lo')}\n"
            "    clc\n"
            f"    adc {match.group('disp')}\n"
            "    tax\n"
            "    lda $400000,x\n"
            f"{tail}"
        )

    body = READ_PATTERN.sub(replace_read, body)
    if reads != EXPECTED_READS:
        raise RuntimeError(
            f"unexpected $01E7C0 v2 read inventory: {dict(reads)}; "
            f"expected {dict(EXPECTED_READS)}"
        )

    writes: Counter = Counter()

    def replace_write(match: re.Match[str]) -> str:
        key = (match.group("lo"), match.group("hi"), "writebyte_l")
        writes[key] += 1
        # writebyte_l leaves A.hi zero and native N/Z from the stored byte.
        # Clear B before entering 8-bit mode, then make the byte load the final
        # flag-producing instruction exactly as the helper does.
        return (
            f"    lda ${match.group('lo')}\n"
            "    clc\n"
            f"    adc {match.group('disp')}\n"
            "    tax\n"
            "    lda #$0000\n"
            "    sep #$20\n"
            "    lda $80\n"
            "    sta $400000,x\n"
            "    rep #$20"
        )

    body = WRITE_PATTERN.sub(replace_write, body)
    if writes != EXPECTED_WRITES:
        raise RuntimeError(
            f"unexpected $01E7C0 v2 write inventory: {dict(writes)}; "
            f"expected {dict(EXPECTED_WRITES)}"
        )
    return body, reads, writes


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", type=Path, default=DEFAULT_SOURCE)
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Rewrite the source in place; otherwise validate and report only.",
    )
    args = parser.parse_args()
    text = args.source.read_text()
    start = text.index(START_MARKER)
    end = text.index(END_MARKER, start)
    body, reads, writes = specialize(text[start:end])
    rewritten = text[:start] + body + text[end:]
    print(
        "$01E7C0 guarded work-RAM v2: "
        f"{sum(reads.values())} reads, {sum(writes.values())} writes, "
        f"source delta {len(rewritten) - len(text)} bytes"
    )
    if args.apply:
        args.source.write_text(rewritten)
        print(f"updated {args.source}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
