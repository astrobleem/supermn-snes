#!/usr/bin/env python3
"""Guard byte-width semantics throughout the $01E7C0 object processor.

The checked-in bank-$98 body is intentionally an older, heavily specialized
transpile.  Its original signed-byte tests and CMP.B/SUB.B lowerings consumed
16-bit flags, so preserved high bytes in D7/D3 could admit inactive objects,
suppress repeat-contact checks, select the death branch while health remained
positive, skip the $81/$82 response writes, or calculate the wrong death
vector.  This validator ties every repaired native seam to the corresponding
arcade instruction and fails if a future body rewrite drops an 8-bit
arithmetic/sign seam or overwrites a data register's preserved upper bytes.
"""

from __future__ import annotations

import argparse
import re
from pathlib import Path

import capstone


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SOURCE = ROOT / "src" / "escbank4.pasm"
DEFAULT_HOT_SOURCE = ROOT / "src" / "escbank3.pasm"
DEFAULT_PROGRAM = ROOT / "data" / "superman_m68k.bin"

# arcade PC -> (expected mnemonic, native basic-block label, SBC operand)
SEAMS = {
    0x01E7FA: ("cmpi.b", "Lf1e7c0_9", "#$05"),
    0x01E800: ("subq.b", "Lf1e7c0_12", "#$01"),
    0x01E958: ("cmpi.b", "Lf1e7c0_58", "#$81"),
    0x01E95E: ("cmpi.b", "Lf1e7c0_59", "#$82"),
    0x01E986: ("cmpi.b", "Lf1e7c0_63", "#$81"),
    0x01E98C: ("cmpi.b", "Lf1e7c0_64", "#$82"),
    0x01E9A4: ("cmp.b", "L1e7c0_1e9a4", "$9E"),
    0x01E9B0: ("cmpi.b", "Lf1e7c0_67", "#$9D"),
    0x01E9DA: ("cmpi.b", "L1e7c0_1e9da", "#$24"),
    0x01E9E0: ("cmpi.b", "Lf1e7c0_71", "#$44"),
    0x01E9EA: ("cmpi.b", "L1e7c0_1e9ea", "#$01"),
    0x01E9F4: ("cmpi.b", "L1e7c0_1e9f4", "#$02"),
    0x01EA0A: ("cmpi.b", "L1e7c0_1ea0a", "#$81"),
    0x01EA16: ("cmpi.b", "L1e7c0_1ea16", "#$82"),
    0x01EA48: ("sub.b", "L1e7c0_1ea48", "$0C"),
    0x01EA4E: ("cmpi.b", "Lf1e7c0_83", "#$01"),
    0x01EA6A: ("cmpi.b", "L1e7c0_1ea6a", "#$20"),
    0x01EA70: ("cmpi.b", "Lf1e7c0_85", "#$5F"),
    0x01EA76: ("cmpi.b", "Lf1e7c0_86", "#$40"),
    0x01EAB2: ("cmpi.b", "L1e7c0_1eab2", "#$20"),
    0x01EAB8: ("cmpi.b", "Lf1e7c0_91", "#$5F"),
    0x01EAC6: ("cmpi.b", "Lf1e7c0_92", "#$40"),
}

# arcade PC -> (expected mnemonic, native basic-block label, ADC operand)
ADD_SEAMS = {
    0x01EA9C: ("add.b", "L1e7c0_1ea98", "$9E"),
}

# Register-destination byte arithmetic also has to store only the low byte
# back into the split native Dn slot.
REGISTER_SUB_SEAMS = {
    0x01EB06: ("sub.b", "Lf1e7c0_95", "$9E", "$0C"),
}

STATIC_CALL_RESIDUE_SEAMS = (
    (0x01E9D0, "br1e7c0_1", 0x01E9D4),
    (0x01EAD6, "br1e7c0_2", 0x01EADA),
    (0x01EAFA, "br1e7c0_3", 0x01EAFE),
    (0x01EEE6, "br1e7c0_4", 0x01EEEA),
    (0x01EF2A, "br1e7c0_5", 0x01EF2E),
    (0x01EF36, "br1e7c0_6", 0x01EF3A),
    (0x01EF46, "br1e7c0_7", 0x01EF4A),
    (0x01EFA0, "br1e7c0_8", 0x01EFA4),
)
INDIRECT_CALL_RESIDUE_SEAMS = (
    ("generated", "br1e7c0_10", 0x01F098),
    ("hot", "h1e7c0_hot_return", 0x01F098),
)

# MOVE.B/TST.B must sign-extend bit 7 before a native signed branch consumes
# N.  Masking the loaded byte to $00FF and branching directly tests bit 15.
# arcade PC -> (expected mnemonic, expected operands, native block label)
SIGNED_BYTE_FLAG_SEAMS = {
    0x01E7F4: ("move.b", "$3(a0), d7", "L1e7c0_1e7f4"),
    0x01E844: ("tst.b", "$3(a0)", "Lf1e7c0_17"),
    0x01EB00: ("tst.b", "$3(a0)", "br1e7c0_3"),
    0x01EBD0: ("tst.b", "$d(a0)", "Lf1e7c0_109"),
    0x01ECB8: ("tst.b", "$d(a0)", "Lf1e7c0_137"),
}
SIGNED_TST_NORMALIZE = (
    "    and #$00FF\n"
    "    eor #$0080\n"
    "    sec\n"
    "    sbc #$0080\n"
)

# The two mirrored script-motion comparators operate exclusively on bytes
# even though D3/D4 retain nonzero upper bytes.  A stale native body tested
# and negated the whole low word, turning arcade D4.b=$FD (-3) into native
# D4.w=$3CFD (+) and selecting horizontal +5 instead of vertical -3.
MOTION_BYTE_ARCADE = {
    0x01EC44: ("move.b", "$c(a2), d6"),
    0x01EC4A: ("move.b", "d6, d3"),
    0x01EC4E: ("neg.b", "d3"),
    0x01EC50: ("move.b", "d7, d4"),
    0x01EC56: ("neg.b", "d4"),
    0x01EC58: ("cmp.b", "d4, d3"),
    0x01ED2C: ("move.b", "$c(a3), d6"),
    0x01ED32: ("move.b", "d6, d3"),
    0x01ED36: ("neg.b", "d3"),
    0x01ED38: ("move.b", "d7, d4"),
    0x01ED3E: ("neg.b", "d4"),
    0x01ED40: ("cmp.b", "d4, d3"),
}


def native_block(source: str, label: str) -> str:
    match = re.search(
        rf"(?m)^{re.escape(label)}:\n(?P<body>.*?)(?=^[A-Za-z_][A-Za-z0-9_]*:|\Z)",
        source,
        flags=re.DOTALL,
    )
    if match is None:
        raise AssertionError(f"missing native block {label}")
    return match.group("body")


def validate_arcade(program: bytes) -> None:
    md = capstone.Cs(capstone.CS_ARCH_M68K, capstone.CS_MODE_BIG_ENDIAN)
    for pc, (mnemonic, _label, _operand) in SEAMS.items():
        instruction = next(md.disasm(program[pc : pc + 8], pc), None)
        assert instruction is not None, f"arcade decode stalled at ${pc:06X}"
        assert instruction.address == pc
        assert instruction.mnemonic == mnemonic, (
            f"${pc:06X}: expected {mnemonic}, got "
            f"{instruction.mnemonic} {instruction.op_str}"
        )
    for pc, (mnemonic, _label, _operand) in ADD_SEAMS.items():
        instruction = next(md.disasm(program[pc : pc + 8], pc), None)
        assert instruction is not None, f"arcade decode stalled at ${pc:06X}"
        assert instruction.address == pc
        assert instruction.mnemonic == mnemonic, (
            f"${pc:06X}: expected {mnemonic}, got "
            f"{instruction.mnemonic} {instruction.op_str}"
        )
    for pc, (mnemonic, _label, _operand, _dest) in (
        REGISTER_SUB_SEAMS.items()
    ):
        instruction = next(md.disasm(program[pc : pc + 8], pc), None)
        assert instruction is not None, f"arcade decode stalled at ${pc:06X}"
        assert instruction.address == pc
        assert instruction.mnemonic == mnemonic, (
            f"${pc:06X}: expected {mnemonic}, got "
            f"{instruction.mnemonic} {instruction.op_str}"
        )
    for pc, (mnemonic, operands, _label) in (
        SIGNED_BYTE_FLAG_SEAMS.items()
    ):
        instruction = next(md.disasm(program[pc : pc + 8], pc), None)
        assert instruction is not None, f"arcade decode stalled at ${pc:06X}"
        assert instruction.address == pc
        assert instruction.mnemonic == mnemonic, (
            f"${pc:06X}: expected {mnemonic}, got "
            f"{instruction.mnemonic} {instruction.op_str}"
        )
        assert instruction.op_str == operands, (
            f"${pc:06X}: expected {operands}, got {instruction.op_str}"
        )
    for pc, (mnemonic, operands) in MOTION_BYTE_ARCADE.items():
        instruction = next(md.disasm(program[pc : pc + 8], pc), None)
        assert instruction is not None, f"arcade decode stalled at ${pc:06X}"
        assert instruction.address == pc
        assert instruction.mnemonic == mnemonic, (
            f"${pc:06X}: expected {mnemonic}, got "
            f"{instruction.mnemonic} {instruction.op_str}"
        )
        assert instruction.op_str == operands, (
            f"${pc:06X}: expected {operands}, got {instruction.op_str}"
        )
    for call_pc, _label, expected_return in STATIC_CALL_RESIDUE_SEAMS:
        instruction = next(
            md.disasm(program[call_pc : call_pc + 8], call_pc),
            None,
        )
        assert instruction is not None
        assert (
            instruction.mnemonic == "jsr"
            or instruction.mnemonic.startswith("bsr")
        ), (
            f"${call_pc:06X}: expected jsr/bsr, got "
            f"{instruction.mnemonic} {instruction.op_str}"
        )
        assert instruction.address + instruction.size == expected_return, (
            f"${call_pc:06X}: return moved from ${expected_return:06X}"
        )


def residue_body(expected_return: int) -> str:
    return (
        "    lda $3C\n"
        "    sec\n"
        "    sbc #$0004\n"
        "    tax\n"
        f"    lda #${(expected_return >> 16) & 0xFFFF:04X}\n"
        "    xba\n"
        "    sta $400000,x\n"
        "    xba\n"
        "    inx\n"
        "    inx\n"
        f"    lda #${expected_return & 0xFFFF:04X}\n"
        "    xba\n"
        "    sta $400000,x\n"
        "    xba\n"
    )


def validate_native(source: str, hot_source: str) -> None:
    for pc, (_mnemonic, label, operand) in SEAMS.items():
        block = native_block(source, label)
        seam = (
            "    sep #$20\n"
            "    sec\n"
            f"    sbc {operand}\n"
            "    rep #$20\n"
        )
        count = block.count(seam)
        assert count == 1, (
            f"${pc:06X} / {label}: expected one exact byte-width "
            f"SEP/SBC {operand}/REP seam, found {count}"
        )
    for pc, (_mnemonic, label, operand) in ADD_SEAMS.items():
        block = native_block(source, label)
        seam = (
            "    lda $0C\n"
            "    sep #$20\n"
            "    clc\n"
            f"    adc {operand}\n"
            "    sta $0C\n"
            "    rep #$20\n"
        )
        count = block.count(seam)
        assert count == 1, (
            f"${pc:06X} / {label}: expected one exact register-preserving "
            f"SEP/ADC {operand}/STA/REP seam, found {count}"
        )
    for pc, (_mnemonic, label, operand, dest) in (
        REGISTER_SUB_SEAMS.items()
    ):
        block = native_block(source, label)
        seam = (
            f"    lda {dest}\n"
            "    sep #$20\n"
            "    sec\n"
            f"    sbc {operand}\n"
            f"    sta {dest}\n"
            "    rep #$20\n"
        )
        count = block.count(seam)
        assert count == 1, (
            f"${pc:06X} / {label}: expected one exact register-preserving "
            f"SEP/SBC {operand}/STA {dest}/REP seam, found {count}"
        )
    for pc, (_mnemonic, _operands, label) in (
        SIGNED_BYTE_FLAG_SEAMS.items()
    ):
        block = native_block(source, label)
        count = block.count(SIGNED_TST_NORMALIZE)
        assert count == 1, (
            f"${pc:06X} / {label}: expected one byte-sign normalization "
            f"before BMI/BPL, found {count}"
        )
        assert "    and #$00FF\n    bmi " not in block, (
            f"${pc:06X} / {label}: stale mask-then-BMI byte test remains"
        )
    shared_helper = native_block(
        source,
        "restore_1e7c0_call_residue",
    )
    expected_helper = (
        "    .a16\n"
        "    .i16\n"
        "    pha\n"
        "    lda $3C\n"
        "    sec\n"
        "    sbc #$0004\n"
        "    tax\n"
        "    lda #$0001\n"
        "    xba\n"
        "    sta $400000,x\n"
        "    xba\n"
        "    inx\n"
        "    inx\n"
        "    pla\n"
        "    xba\n"
        "    sta $400000,x\n"
        "    xba\n"
        "    rts\n"
    )
    assert shared_helper == expected_helper, (
        "shared static-call residue helper no longer matches the exact "
        "bank-$01 return writer"
    )
    for call_pc, label, expected_return in STATIC_CALL_RESIDUE_SEAMS:
        block = native_block(source, label)
        seam = (
            f"    lda #${expected_return & 0xFFFF:04X}\n"
            "    jsr restore_1e7c0_call_residue\n"
        )
        count = block.count(seam)
        assert count == 1, (
            f"${call_pc:06X} / {label}: expected one shared real-return "
            f"residue restore for ${expected_return:06X}, found {count}"
        )
    sources = {"generated": source, "hot": hot_source}
    for owner, label, expected_return in INDIRECT_CALL_RESIDUE_SEAMS:
        block = native_block(sources[owner], label)
        count = block.count(residue_body(expected_return))
        assert count == 1, (
            f"$01F096 / {owner}:{label}: expected one exact indirect-call "
            f"return residue restore for ${expected_return:06X}, found {count}"
        )

    load_byte_seams = (
        ("Lf1e7c0_121", "$18", "Lf1e7c0_122"),
        ("Lf1e7c0_122", "$0C", "Lf1e7c0_123"),
        ("L1e7c0_1ec50", "$10", "Lf1e7c0_124"),
        ("Lf1e7c0_149", "$18", "Lf1e7c0_150"),
        ("Lf1e7c0_150", "$0C", "Lf1e7c0_151"),
        ("L1e7c0_1ed38", "$10", "Lf1e7c0_152"),
    )
    for label, register, branch_label in load_byte_seams:
        block = native_block(source, label)
        seam = (
            "    sep #$20\n"
            f"    sta {register}\n"
            f"    lda {register}\n"
            "    rep #$20\n"
        )
        assert block.count(seam) == 1, (
            f"{label}: MOVE.B result must be reloaded in 8-bit mode before "
            f"branching to {branch_label}"
        )

    helper_calls = {
        "Lf1e7c0_123": ("neg_d3_byte_1e7c0", 5),
        "Lf1e7c0_125": ("neg_d4_byte_1e7c0", 5),
        "L1e7c0_1ec58": ("cmp_d3_d4_byte_1e7c0", 2),
        "Lf1e7c0_151": ("neg_d3_byte_1e7c0", 5),
        "Lf1e7c0_153": ("neg_d4_byte_1e7c0", 5),
        "L1e7c0_1ed40": ("cmp_d3_d4_byte_1e7c0", 2),
    }
    for label, (helper, padding) in helper_calls.items():
        block = native_block(source, label)
        seam = f"    jsr {helper}\n" + ("    nop\n" * padding)
        assert block.count(seam) == 1, (
            f"{label}: expected one address-stable {helper} call with "
            f"{padding} padding NOPs"
        )

    byte_helpers = {
        "neg_d3_byte_1e7c0": (
            "    .a16\n"
            "    .i16\n"
            "    sep #$20\n"
            "    lda #$00\n"
            "    sec\n"
            "    sbc $0C\n"
            "    sta $0C\n"
            "    rep #$20\n"
            "    rts\n"
        ),
        "neg_d4_byte_1e7c0": (
            "    .a16\n"
            "    .i16\n"
            "    sep #$20\n"
            "    lda #$00\n"
            "    sec\n"
            "    sbc $10\n"
            "    sta $10\n"
            "    rep #$20\n"
            "    rts\n"
        ),
        "cmp_d3_d4_byte_1e7c0": (
            "    .a16\n"
            "    .i16\n"
            "    sep #$20\n"
            "    lda $0C\n"
            "    sec\n"
            "    sbc $10\n"
            "    rep #$20\n"
            "    rts\n"
        ),
    }
    for label, expected in byte_helpers.items():
        assert native_block(source, label) == expected, (
            f"{label}: byte helper no longer preserves upper register bytes "
            "and 8-bit branch flags"
        )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", type=Path, default=DEFAULT_SOURCE)
    parser.add_argument("--hot-source", type=Path, default=DEFAULT_HOT_SOURCE)
    parser.add_argument("--program", type=Path, default=DEFAULT_PROGRAM)
    args = parser.parse_args()
    if not args.source.is_file():
        parser.error(f"missing native source: {args.source}")
    if not args.hot_source.is_file():
        parser.error(f"missing native hot-helper source: {args.hot_source}")
    if not args.program.is_file():
        parser.error(f"missing authenticated arcade program: {args.program}")

    validate_arcade(args.program.read_bytes())
    validate_native(
        args.source.read_text(encoding="utf-8"),
        args.hot_source.read_text(encoding="utf-8"),
    )
    print(
        "$01E7C0 collision byte-width regression: "
        f"PASS ({len(SEAMS) + len(ADD_SEAMS) + len(REGISTER_SUB_SEAMS)} "
        "arithmetic byte seams + "
        f"{len(SIGNED_BYTE_FLAG_SEAMS)} signed byte-flag seams + "
        f"{len(MOTION_BYTE_ARCADE)} script-motion byte instructions + "
        f"{len(STATIC_CALL_RESIDUE_SEAMS) + len(INDIRECT_CALL_RESIDUE_SEAMS)} "
        "call residues)"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
