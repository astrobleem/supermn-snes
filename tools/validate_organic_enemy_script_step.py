#!/usr/bin/env python3
"""Three-way regression for the second organic enemy-update divergence.

The retained cold-boot movie is byte-identical at MAME tick 919 / SNES replay
label 920.  The next arcade update executes ``TST.B $D(A0)`` with the byte
equal to ``$FF`` and therefore takes the negative/script-motion path.  The
older deployed $01E7C0 native body masked the byte to ``$00FF`` and tested the
65816 word sign, incorrectly treating it as positive.

This wrapper reuses the architectural checkpoint machinery from
``validate_organic_enemy_step.py`` while substituting the second exact
prestate, oracle, native entry, and byte-sign code-generation audit.
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
TST_SEAMS = {
    0x01EBD0: "Lf1e7c0_109",
    0x01ECB8: "Lf1e7c0_137",
}


def native_block(source: str, label: str) -> str:
    match = re.search(
        rf"(?ms)^{re.escape(label)}:\n(?P<body>.*?)(?=^[A-Za-z_][A-Za-z0-9_]*:|\Z)",
        source,
    )
    if match is None:
        raise AssertionError(f"missing native block {label}")
    return match.group("body")


def generated_block(source: str, label: str) -> str:
    return native_block(source, label)


def validate_codegen(source_path: Path, program_path: Path) -> dict[str, Any]:
    program = program_path.read_bytes()
    md = capstone.Cs(capstone.CS_ARCH_M68K, capstone.CS_MODE_BIG_ENDIAN)
    arcade: list[dict[str, Any]] = []
    arcade_green = True
    for pc, label in TST_SEAMS.items():
        instruction = next(md.disasm(program[pc : pc + 8], pc), None)
        row = {
            "pc": f"{pc:06X}",
            "label": label,
            "mnemonic": instruction.mnemonic if instruction else None,
            "operands": instruction.op_str if instruction else None,
        }
        arcade.append(row)
        arcade_green &= bool(
            instruction
            and instruction.address == pc
            and instruction.mnemonic == "tst.b"
            and instruction.op_str == "$d(a0)"
        )

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
    generated_counts: dict[str, int] = {}
    deployed_counts: dict[str, int] = {}
    stale_counts: dict[str, int] = {}
    for label in TST_SEAMS.values():
        generated_counts[label] = generated_block(
            generated.stdout, label
        ).count(SIGN_NORMALIZE)
        block = native_block(deployed, label)
        deployed_counts[label] = block.count(SIGN_NORMALIZE)
        stale_counts[label] = block.count(
            "    and #$00FF\n"
            "    bmi "
        )
    generated_green = all(count == 1 for count in generated_counts.values())
    deployed_green = all(count == 1 for count in deployed_counts.values())
    stale_green = all(count == 0 for count in stale_counts.values())
    green = arcade_green and generated_green and deployed_green and stale_green
    return {
        "arcade_instructions": arcade,
        "arcade_instruction_result": "green" if arcade_green else "red",
        "transpiler_command": command,
        "transpiler_stderr": generated.stderr.strip(),
        "transpiler_sign_normalize_counts": generated_counts,
        "transpiler_result": "green" if generated_green else "red",
        "deployed_sign_normalize_counts": deployed_counts,
        "deployed_stale_mask_then_bmi_counts": stale_counts,
        "deployed_result": (
            "green" if deployed_green and stale_green else "red"
        ),
        "result": "green" if green else "red",
    }


base.DEFAULT_STATE = (
    EVIDENCE
    / "organic-enemy-second-step-snes-pre-4620485-nexen-v1"
    / "states"
    / "snes-tick-00920.mss"
)
base.DEFAULT_MAME_DIR = EVIDENCE / "organic-enemy-second-step-mame-writes-v1"
base.DEFAULT_SOURCE = ROOT / "src" / "escbank4.pasm"
base.MAME_PRE_TICK = 919
base.MAME_POST_TICK = 920
base.SNES_PRE_LABEL = 920
base.NATIVE_ENTRY = 0x98AE00
base.CASE_SCOPE = (
    "focused state-loaded three-way differential from the exact second "
    "organic enemy-update divergence prestate; not fresh-boot proof"
)
base.validate_codegen = validate_codegen


if __name__ == "__main__":
    raise SystemExit(base.main())
