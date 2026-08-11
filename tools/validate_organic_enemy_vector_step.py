#!/usr/bin/env python3
"""Three-way regression for the organic $01E7C0 long-vector divergence.

At retained movie tick 1321 the MAME and SNES player, first enemy, and
collision records are identical.  During the next update, original PCs
$01EB76-$01EB84 scale two signed 32-bit table vectors with six ``ADD.L``
instructions.  The stale deployed native body changed only each register's
low word, so a $00010000 input remained $00010000 instead of becoming
$00060000.  The following DIVS then wrote $00000444/$00000001 where the
arcade and the all-native-off interpreter both wrote
$00001999/$00000006.

This wrapper reuses the exact checkpoint/MAME/native-off/native-on machinery
from ``validate_organic_enemy_step.py`` and adds focused original-code,
transpiler, deployed-body, carry, and X-publication checks.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path
from typing import Any

import capstone

import validate_organic_enemy_step as base


ROOT = Path(__file__).resolve().parents[1]
EVIDENCE = ROOT / "build" / "playtest-investigation-20260725"

COMPACT_SCALE = """\
    asl $18
    rol $1A
    lda $18
    sta $1C
    lda $1A
    sta $1E
    asl $18
    rol $1A
    lda $18
    clc
    adc $1C
    sta $18
    lda $1A
    adc $1E
    sta $1A
    asl $10
    rol $12
    lda $10
    sta $1C
    lda $12
    sta $1E
    asl $10
    rol $12
    lda $10
    clc
    adc $1C
    sta $10
    lda $12
    adc $1E
    sta $12
"""

X_PUBLISH = """\
    php
    lda #$0000
    rol a
    sta $A2
    plp
"""

STALE_LOW_WORD_SCALE = """\
    lda $18
    clc
    adc $18
    sta $18
    lda $18
    sta $9A
"""

TRANSPILE_COMMAND = [
    sys.executable,
    str(ROOT / "tools" / "transpile.py"),
    "01E7C0",
    "--bank1",
    "--coroutine",
    "--bail",
    "--jt=1EE6C:-16:0,1F0B6:0:6",
    "--escapes=D96",
    "--restore-static-residue",
    "--restore-indirect-residue",
]


def scale_block(source: str) -> str:
    start = source.index("L1e7c0_1eb6a:")
    end = source.index(
        "    ; BAIL to interp @ $01EB8E: divs.w d3, d6",
        start,
    )
    return source[start:end]


def generated_high_word_counts(block: str) -> dict[str, int]:
    return {
        "d6_double_high": block.count(
            "    lda $1A\n"
            "    adc $1A\n"
            "    sta $1A\n"
        ),
        "d6_add_saved_high": block.count(
            "    lda $1A\n"
            "    adc $1E\n"
            "    sta $1A\n"
        ),
        "d4_double_high": block.count(
            "    lda $12\n"
            "    adc $12\n"
            "    sta $12\n"
        ),
        "d4_add_saved_high": block.count(
            "    lda $12\n"
            "    adc $1E\n"
            "    sta $12\n"
        ),
    }


def validate_codegen(
    source_path: Path,
    program_path: Path,
) -> dict[str, Any]:
    program = program_path.read_bytes()
    md = capstone.Cs(
        capstone.CS_ARCH_M68K,
        capstone.CS_MODE_BIG_ENDIAN,
    )
    decoded = list(
        md.disasm(program[0x01EB76:0x01EB86], 0x01EB76)
    )
    actual = [
        (instruction.address, instruction.mnemonic, instruction.op_str)
        for instruction in decoded
    ]
    expected = [
        (0x01EB76, "add.l", "d6, d6"),
        (0x01EB78, "move.l", "d6, d7"),
        (0x01EB7A, "add.l", "d6, d6"),
        (0x01EB7C, "add.l", "d7, d6"),
        (0x01EB7E, "add.l", "d4, d4"),
        (0x01EB80, "move.l", "d4, d7"),
        (0x01EB82, "add.l", "d4, d4"),
        (0x01EB84, "add.l", "d7, d4"),
    ]
    arcade_green = actual == expected

    generated = subprocess.run(
        TRANSPILE_COMMAND,
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    generated_counts = generated_high_word_counts(
        scale_block(generated.stdout)
    )
    generated_green = generated_counts == {
        "d6_double_high": 2,
        "d6_add_saved_high": 1,
        "d4_double_high": 2,
        "d4_add_saved_high": 1,
    }

    deployed_block = scale_block(
        source_path.read_text(encoding="utf-8")
    )
    deployed_compact_count = deployed_block.count(COMPACT_SCALE)
    deployed_x_count = deployed_block.count(X_PUBLISH)
    deployed_stale_count = deployed_block.count(STALE_LOW_WORD_SCALE)
    deployed_green = (
        deployed_compact_count == 1
        and deployed_x_count == 1
        and deployed_stale_count == 0
    )
    green = arcade_green and generated_green and deployed_green
    return {
        "arcade_instructions": [
            {
                "pc": f"{pc:06X}",
                "mnemonic": mnemonic,
                "operands": operands,
            }
            for pc, mnemonic, operands in actual
        ],
        "arcade_instruction_result": (
            "green" if arcade_green else "red"
        ),
        "transpiler_command": TRANSPILE_COMMAND,
        "transpiler_stderr": generated.stderr.strip(),
        "transpiler_high_word_counts": generated_counts,
        "transpiler_result": (
            "green" if generated_green else "red"
        ),
        "deployed_compact_scale_count": deployed_compact_count,
        "deployed_x_publish_count": deployed_x_count,
        "deployed_stale_low_word_count": deployed_stale_count,
        "deployed_result": "green" if deployed_green else "red",
        "result": "green" if green else "red",
    }


base.DEFAULT_STATE = (
    EVIDENCE
    / "failure-3043-snes-bisect-1300-1325-on-9a68dc4-v1"
    / "states"
    / "snes-tick-01321.mss"
)
base.DEFAULT_MAME_DIR = (
    EVIDENCE / "failure-3043-mame-bisect-1300-1325-v1"
)
base.DEFAULT_SOURCE = ROOT / "src" / "escbank4.pasm"
base.MAME_PRE_TICK = 1321
base.MAME_POST_TICK = 1322
base.SNES_PRE_LABEL = 1321
base.NATIVE_ENTRY = 0x98AE00
base.CASE_SCOPE = (
    "focused state-loaded three-way differential from the exact organic "
    "$01E7C0 long-vector divergence prestate; not fresh-boot proof"
)
base.validate_codegen = validate_codegen


if __name__ == "__main__":
    raise SystemExit(base.main())
