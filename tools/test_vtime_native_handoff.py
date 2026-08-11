#!/usr/bin/env python3
"""Guard the cross-bank VTIME native->interpreter owner handoff contract."""

from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
VTIME = ROOT / "src/vtime.pasm"
VTIME_BIN = ROOT / "src/vtime.bin"
VTIME_SYMS = ROOT / "src/vtime.sym"
PACK = ROOT / "tools/build_interp_rom.py"


def symbol_offsets() -> dict[str, int]:
    result: dict[str, int] = {}
    for line in VTIME_SYMS.read_text(encoding="utf-8-sig").splitlines():
        fields = line.split()
        if len(fields) >= 2 and ":" in fields[0]:
            result[fields[1]] = int(fields[0].split(":", 1)[1], 16)
    return result


def main() -> int:
    source = VTIME.read_text(encoding="utf-8")
    pack = PACK.read_text(encoding="utf-8")
    start = source.index("vtime_native_handoff_to_interpreter:")
    end = source.index("vtime_native_handoff_to_interpreter_end:")
    handoff = source[start:end]
    for required in (
        "VT_OWNER_25110=$0003",
        "VT_OWNER_STAGE3_PLAYER=$0009",
        "cmp #VT_OWNER_25110",
        "cmp #VT_OWNER_STAGE3_PLAYER",
        "jsr vtime_esc3_charge_pending",
        "jsr vtime_esc9_charge_pending",
        "sta VT_VALID",
        "sta VT_NATIVE_PENDING",
        "sta VT_NATIVE_CURRENT",
        "sta VT_NATIVE_OWNER",
        "vtime_native_handoff_due:",
    ):
        assert required in source if required.startswith("VT_OWNER") else required in handoff, required
    assert "stz VT_" not in handoff, "BW-RAM state must use explicit long stores"
    assert "vtime_off(\"vtime_native_handoff_to_interpreter\") == 0xFE40" in pack
    assert "vtime_off(\"vtime_native_handoff_to_interpreter_end\")" in pack

    offsets = symbol_offsets()
    assert offsets["vtime_native_handoff_to_interpreter"] == 0xFE40
    assert offsets["vtime_native_handoff_to_interpreter_end"] == 0xFE94
    assert offsets["vtime_image_end"] == offsets["vtime_native_handoff_to_interpreter_end"]
    image = VTIME_BIN.read_bytes()
    start_offset = offsets["vtime_native_handoff_to_interpreter"] - 0x8000
    end_offset = offsets["vtime_native_handoff_to_interpreter_end"] - 0x8000
    helper = image[start_offset:end_offset]
    assert len(helper) == 0x54
    # The unknown-owner and the two result paths clear BW-RAM through actual
    # STA long encodings.  A source-only check would miss Poppy silently
    # truncating a store to SA-1 IRAM.
    for low_word in (0x4002, 0x4014, 0x4016, 0x401A):
        store = bytes((0x8F,)) + low_word.to_bytes(2, "little") + bytes((0x40,))
        assert store in helper, f"missing assembled handoff store to $40:{low_word:04X}"
    assert bytes((0x20, 0x86, 0x86)) in helper, "missing $025110 deferred-block flush"
    assert bytes((0x20, 0xA0, 0xB1)) in helper, "missing player deferred-block flush"
    assert helper.endswith(bytes.fromhex("a900008f144040386b")), (
        "handoff due path no longer clears only the pending native block"
    )
    print("VTIME native/interpreter handoff regression: green (assembled, unwired diagnostic helper)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
