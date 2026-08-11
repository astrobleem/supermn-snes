#!/usr/bin/env python3
"""Guard the opt-in VTIME interpreter-only correctness diagnostic.

The experiment must leave normal and ordinary VTIME images unchanged. Only an
explicit `VTIME_INTERPRETER_ONLY=1` pack may set the second enable-byte flag,
and the source must defer disabling gameplay-native gates until virtual timing
has initialized after the existing task-context gate.
"""

from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
VTIME = ROOT / "src" / "vtime.pasm"
VTIME_ESC5_ROOT = ROOT / "src" / "vtime_esc5_root.pasm"
PACKER = ROOT / "tools" / "build_interp_rom.py"


def main() -> int:
    vtime = VTIME.read_text(encoding="utf-8")
    esc5_root = VTIME_ESC5_ROOT.read_text(encoding="utf-8")
    packer = PACKER.read_text(encoding="utf-8")
    required_vtime = (
        "VTIME_FLAG_INTERPRETER_ONLY=$0002",
        "bit #VTIME_FLAG_INTERPRETER_ONLY",
        "stz $071A",
        "stz $073A",
        "stz $0736",
        "stz $073C",
    )
    for text in required_vtime:
        assert text in vtime, f"missing interpreter-only VTIME seam: {text}"
    activation = vtime.index("jsr vtime_load_initial_deadline")
    enforce = vtime.index("vtime_prepare_enforce_mode:")
    disable = vtime.index("bit #VTIME_FLAG_INTERPRETER_ONLY")
    assert activation < disable, "native gates must not change before VTIME initialization"
    assert "beq vtime_prepare_enforce_mode" in vtime
    assert activation < enforce < disable
    assert esc5_root.count("jsr vtime_esc5_restore_gate") == 11
    assert "and #VTIME_FLAG_INTERPRETER_ONLY" in esc5_root
    assert "vtime_esc5_restore_gate_off:\n    stz $071A" in esc5_root
    assert "VTIME_INTERPRETER_ONLY=1 requires VTIME=1" in packer
    assert "ROM[0x328000] = 0x03 if vtime_interpreter_only else 0x01" in packer
    print("VTIME interpreter-only pack regression guard OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
