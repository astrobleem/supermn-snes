#!/usr/bin/env python3
"""Source regression for the generated VTIME `$02429C` diagnostic root."""

from __future__ import annotations

import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

import gen_vtime_esc5_root as generator


def main() -> int:
    content = generator.generate()
    assert content.count("jsr vtime_esc5_charge_gateway") == 35
    assert content.count("jmp vtime_esc5_ojmp_gateway") == 11
    assert "vtime_esc5_ibridge_gateway" not in content
    assert "jml.l ibridge" not in content
    assert "lda #$00F7" not in content
    assert "lda #$00FA" not in content
    assert "jsr esc_ac_charge" not in content
    assert "vtime_h2429c_tst_byte19_branch:" in content
    assert content.count("jmp vtime_esc5_inext_gateway") == 1
    returns = generator.child_returns()
    assert returns == [
        0x0242AC,
        0x0242B2,
        0x0242B8,
        0x0242BE,
        0x0242C4,
        0x024306,
        0x024334,
        0x02436E,
        0x024378,
        0x0243B4,
        0x0243DA,
    ]
    for ordinal, return_pc in enumerate(returns, 1):
        assert content.count(f"cmp #${return_pc & 0xFFFF:04X}") == 1
        assert content.count(f"jmp br2429c_{ordinal}\n") == 1
    # Ten static bridges plus the rewritten indirect bridge push genuine
    # bank-$02 return values before exposing the child PC.
    assert content.count(
        "lda #$0002\n    sta $56\n    jsl.l push32_l"
    ) == 11
    assert content.count("jmp vtime_esc5_ojmp_gateway") == 11
    assert content.count("jsr vtime_esc5_restore_gate") == 11
    assert content.count("sta $071A") == 1
    assert content.count("stz $071A") == 2
    assert "VTIME_FLAG_INTERPRETER_ONLY=$0002" in content
    assert "and #VTIME_FLAG_INTERPRETER_ONLY" in content
    assert "jml.l $94F900" in content
    print("VTIME $02429C diagnostic-root generator: green")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
