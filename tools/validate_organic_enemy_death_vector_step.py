#!/usr/bin/env python3
"""Three-way regression for the organic $01EB00 byte-sign divergence.

At retained movie tick 2054, MAME, native-off SNES, and native-on SNES have
byte-identical player, first-enemy, and collision records.  The enemy has just
crossed zero health, so the original object processor executes::

    TST.B $3(A0)
    BGT    $01EB10
    SUB.B  $3(A0),D3
    MULU.W #3,D3

With ``$3(A0) == $FF`` and ``D3.b == $14``, arcade code takes the signed
negative path and derives ``D3 == $003F``.  The stale specialized native body
zero-extended ``$FF`` before a 16-bit BMI and therefore kept ``D3 == $0014``.
That wrong value was stored in object byte ``$F002DE`` and changed later enemy
motion/collision state.

This wrapper reuses the exact checkpointed MAME/native-off/native-on machinery
from ``validate_organic_enemy_step.py`` and adds original-code, transpiler, and
deployed-body checks for both the signed TST.B and register-preserving SUB.B.
It is focused checkpoint evidence, not fresh-boot or performance evidence.
"""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path
from typing import Any

import capstone

import validate_organic_enemy_step as base


ROOT = Path(__file__).resolve().parents[1]
EVIDENCE = ROOT / "build" / "playtest-investigation-20260725"
SIGN_NORMALIZE = (
    "    and #$00FF\n"
    "    eor #$0080\n"
    "    sec\n"
    "    sbc #$0080\n"
)
BYTE_SUB = (
    "    lda $0C\n"
    "    sep #$20\n"
    "    sec\n"
    "    sbc $9E\n"
    "    sta $0C\n"
    "    rep #$20\n"
)
RETURN_RESIDUE = (
    "    lda #$EAFE\n"
    "    jsr restore_1e7c0_call_residue\n"
)


def native_block(source: str, label: str) -> str:
    match = re.search(
        rf"(?ms)^{re.escape(label)}:\n"
        rf"(?P<body>.*?)(?=^[A-Za-z_][A-Za-z0-9_]*:|\Z)",
        source,
    )
    if match is None:
        raise AssertionError(f"missing native block {label}")
    return match.group("body")


def validate_codegen(source_path: Path, program_path: Path) -> dict[str, Any]:
    program = program_path.read_bytes()
    md = capstone.Cs(capstone.CS_ARCH_M68K, capstone.CS_MODE_BIG_ENDIAN)
    actual = [
        (instruction.address, instruction.mnemonic, instruction.op_str)
        for instruction in md.disasm(program[0x01EB00:0x01EB0E], 0x01EB00)
    ]
    expected = [
        (0x01EB00, "tst.b", "$3(a0)"),
        (0x01EB04, "bgt.b", "$1eb10"),
        (0x01EB06, "sub.b", "$3(a0), d3"),
        (0x01EB0A, "mulu.w", "#$3, d3"),
    ]
    arcade_green = actual == expected

    command = [
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
    generated = subprocess.run(
        command,
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    deployed = source_path.read_text(encoding="utf-8")

    generated_branch = native_block(generated.stdout, "br1e7c0_3")
    generated_sub = native_block(generated.stdout, "Lf1e7c0_95")
    deployed_branch = native_block(deployed, "br1e7c0_3")
    deployed_sub = native_block(deployed, "Lf1e7c0_95")

    generated_counts = {
        "signed_tst": generated_branch.count(SIGN_NORMALIZE),
        "byte_sub": generated_sub.count(BYTE_SUB),
    }
    deployed_counts = {
        "signed_tst": deployed_branch.count(SIGN_NORMALIZE),
        "byte_sub": deployed_sub.count(BYTE_SUB),
        "real_return_residue": deployed_branch.count(RETURN_RESIDUE),
    }
    stale_counts = {
        "mask_then_bmi": deployed_branch.count(
            "    and #$00FF\n"
            "    bmi "
        ),
        "word_sub": deployed_sub.count(
            "    lda $0C\n"
            "    sec\n"
            "    sbc $9E\n"
            "    sta $0C\n"
        ),
    }
    generated_green = generated_counts == {
        "signed_tst": 1,
        "byte_sub": 1,
    }
    deployed_green = (
        deployed_counts
        == {
            "signed_tst": 1,
            "byte_sub": 1,
            "real_return_residue": 1,
        }
        and all(count == 0 for count in stale_counts.values())
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
        "transpiler_command": command,
        "transpiler_stderr": generated.stderr.strip(),
        "transpiler_counts": generated_counts,
        "transpiler_result": (
            "green" if generated_green else "red"
        ),
        "deployed_counts": deployed_counts,
        "deployed_stale_counts": stale_counts,
        "deployed_result": "green" if deployed_green else "red",
        "result": "green" if green else "red",
    }


base.DEFAULT_STATE = (
    EVIDENCE
    / "failure-3043-current-806e636-bisect-2050-2075-on-v1"
    / "states"
    / "snes-tick-02054.mss"
)
base.DEFAULT_MAME_DIR = (
    EVIDENCE
    / "failure-3043-current-mame-enemy-writes-2054-2055-v1"
)
base.DEFAULT_SOURCE = ROOT / "src" / "escbank4.pasm"
base.MAME_PRE_TICK = 2054
base.MAME_POST_TICK = 2055
base.SNES_PRE_LABEL = 2054
base.NATIVE_ENTRY = 0x98AE00
base.CASE_SCOPE = (
    "focused state-loaded three-way differential from the exact organic "
    "$01EB00 signed-byte death-vector divergence prestate; not fresh-boot "
    "or performance proof"
)
base.validate_codegen = validate_codegen


if __name__ == "__main__":
    raise SystemExit(base.main())
