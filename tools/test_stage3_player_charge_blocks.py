#!/usr/bin/env python3
"""Regression guard for the active Stage-3 player native-charge inventory."""

from __future__ import annotations

import importlib.util
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "stage3_player_charge_audit", ROOT / "tools" / "audit_stage3_player_charge_blocks.py"
)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError("cannot import the Stage-3 player charge audit")
AUDIT = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(AUDIT)


def main() -> int:
    transpiler = AUDIT.load_transpiler()
    shapes = []
    nonterminal_shifts = []
    for entry, _start, _end, expected_instructions, expected_blocks in AUDIT.SPECS:
        blocks = AUDIT.basic_blocks(transpiler, entry)
        assert sum(map(len, blocks)) == expected_instructions
        assert len(blocks) == expected_blocks
        shapes.append((entry, len(blocks)))
        for block in blocks:
            for index, instruction in enumerate(block):
                if AUDIT.timing_kind(instruction) == "shift_or_rotate" and index != len(block) - 1:
                    nonterminal_shifts.append(AUDIT.immediate_shift_units(instruction))
    assert shapes == [
        (0x013282, 9), (0x013314, 9), (0x01337E, 9),
        (0x0133EA, 17), (0x013468, 24), (0x013538, 15),
    ]
    assert nonterminal_shifts == [1, 1, 4, 2]
    assert AUDIT.timing_kind(type("I", (), {"mnemonic": "bclr.b"})()) is None
    assert AUDIT.timing_kind(type("I", (), {"mnemonic": "bsr.w"})()) is None
    assert AUDIT.timing_kind(type("I", (), {"mnemonic": "bne.w"})()) == "conditional_branch_or_loop"
    print("Stage-3 player native-charge inventory regression: green")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
