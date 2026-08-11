#!/usr/bin/env python3
"""Pack regression for the VTIME-only bank-$F3 `$02429C` root."""

from __future__ import annotations

import os
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
ROM_PATH = Path(
    os.environ.get("ROM_PATH", str(ROOT / "build/interp.sfc"))
).resolve()


def symbol(path: Path, name: str) -> int:
    for line in path.read_text(encoding="utf-8-sig").splitlines():
        fields = line.split()
        if len(fields) >= 2 and fields[1] == name:
            return int(fields[0].split(":", 1)[1], 16)
    raise AssertionError(f"missing {name} in {path}")


def main() -> int:
    enabled = os.environ.get("VTIME", "0") == "1"
    rom = ROM_PATH.read_bytes()
    if len(rom) != 0x400000:
        raise AssertionError(f"unexpected ROM size: {len(rom)}")

    vtime = (ROOT / "src/vtime.bin").read_bytes()
    root = (ROOT / "src/vtime_esc5_root.bin").read_bytes()
    vtime_syms = ROOT / "src/vtime.sym"
    root_syms = ROOT / "src/vtime_esc5_root.sym"
    esc2_syms = ROOT / "src/escbank2.sym"
    esc5_syms = ROOT / "src/escbank5.sym"
    interp_syms = ROOT / "src/interp.sym"

    charge = symbol(vtime_syms, "vtime_esc5_charge")
    metadata_end = symbol(vtime_syms, "vtime_esc5_metadata_end")
    charge_slice = slice(0x328000 + charge - 0x8000, 0x328000 + metadata_end - 0x8000)
    f3_slice = slice(0x338000, 0x338000 + len(root))
    esc2_route = 0x2A0000 + symbol(esc2_syms, "xd_sparse_direct") - 0x8000
    esc5_entry = 0x2C8000 + symbol(esc5_syms, "entry_2429c") - 0x8000
    op_rts = symbol(interp_syms, "op_rts_sentinel")
    op_rts_offsets = (op_rts - 0x8000, op_rts)
    return_dispatch = symbol(root_syms, "vtime_esc5_return_dispatch")
    restore_gate = symbol(root_syms, "vtime_esc5_restore_gate")
    restore_gate_off = symbol(root_syms, "vtime_esc5_restore_gate_off")
    restore_gate_end = symbol(root_syms, "vtime_esc5_return_dispatch_end")
    op_rts_vtime = bytes((
        0x5C,
        return_dispatch & 0xFF,
        return_dispatch >> 8,
        0xF3,
    ))
    restore_call = bytes((0x20, restore_gate & 0xFF, restore_gate >> 8))
    return_dispatch_bytes = root[
        return_dispatch - 0x8000:restore_gate - 0x8000
    ]
    if return_dispatch_bytes.count(restore_call) != 11:
        raise AssertionError("F3 child returns lost mode-aware gate restoration")
    expected_restore = bytes.fromhex(
        "af0080f2"      # LDA.l $F28000
        "290200"        # AND #VTIME_FLAG_INTERPRETER_ONLY
        "d007"          # BNE restore-off
        "a90100"        # ordinary VTIME: LDA #1
        "8d1a07"        # STA $071A
        "60"            # RTS
        "9c1a07"        # interpreter-only: STZ $071A
        "60"            # RTS
    )
    if root[restore_gate - 0x8000:restore_gate_end - 0x8000] != expected_restore:
        raise AssertionError("F3 mode-aware gate helper encoding changed")
    if restore_gate_off != restore_gate + 0x10:
        raise AssertionError("F3 interpreter-only gate-off branch moved unexpectedly")

    if rom[esc2_route:esc2_route + 4] != bytes.fromhex("5c00da9d"):
        raise AssertionError("ordinary sparse xlat route changed")

    if enabled:
        if rom[0x328000] not in (1, 3):
            raise AssertionError("VTIME pack did not enable the diagnostic")
        expected_charge = vtime[charge - 0x8000:metadata_end - 0x8000]
        if rom[charge_slice] != expected_charge:
            raise AssertionError("bank-$F2 `$02429C` ledger was not packed exactly")
        if rom[f3_slice] != root:
            raise AssertionError("bank-$F3 `$02429C` root was not packed exactly")
        if any(rom[offset:offset + 4] != op_rts_vtime for offset in op_rts_offsets):
            raise AssertionError("op_rts did not route through the F3 return dispatcher")
        if rom[esc5_entry:esc5_entry + 4] != bytes.fromhex("5c0080f3"):
            raise AssertionError("bank-$99 `$02429C` did not route to the F3 root")
        mode = "enabled"
    else:
        if any(rom[charge_slice]):
            raise AssertionError("ordinary ROM packed the `$02429C` F2 ledger")
        if any(rom[f3_slice]):
            raise AssertionError("ordinary ROM packed the `$02429C` F3 root")
        if any(
            rom[offset:offset + 4] != bytes.fromhex("a542c9ff")
            for offset in op_rts_offsets
        ):
            raise AssertionError("ordinary op_rts_sentinel entry changed")
        if rom[esc5_entry:esc5_entry + 4] != bytes.fromhex("c230a534"):
            raise AssertionError("ordinary bank-$99 `$02429C` entry changed")
        mode = "disabled"

    print(f"VTIME `$02429C` root pack regression: green ({mode})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
