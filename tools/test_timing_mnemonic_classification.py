#!/usr/bin/env python3
"""Keep native and MAME timing reducers from treating every b* opcode as Bcc."""

from __future__ import annotations

import audit_m68k_cycle_model as cycle_audit
import audit_native_charge_blocks as native_audit


def main() -> int:
    for mnemonic in ("bclr.b", "bset.b", "btst.b", "bra.w", "bsr.w"):
        assert native_audit.dynamic_kind(mnemonic) is None, mnemonic
        assert cycle_audit.timing_class(f"{mnemonic} $1234") != "conditional_branch_or_loop", mnemonic
    for mnemonic in ("bcc.w", "bne.b", "bvs.w", "dbra"):
        assert native_audit.dynamic_kind(mnemonic) == "conditional_branch_or_loop", mnemonic
        assert cycle_audit.timing_class(f"{mnemonic} $1234") == "conditional_branch_or_loop", mnemonic
    print("Timing mnemonic classification regression: green")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
