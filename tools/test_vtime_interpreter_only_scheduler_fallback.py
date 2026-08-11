#!/usr/bin/env python3
"""Guard the diagnostic-only scheduler fallback before any timing claim."""

from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def body(source: str, start: str, end: str) -> str:
    return source[source.index(start) : source.index(end, source.index(start))]


def main() -> None:
    vtime = (ROOT / "src/vtime.pasm").read_text(encoding="utf-8")
    interp = (ROOT / "src/interp.pasm").read_text(encoding="utf-8")
    escbank = (ROOT / "src/escbank.pasm").read_text(encoding="utf-8")

    prepare = body(vtime, "vtime_prepare_active:", "vtime_prepare_have_state:")
    assert prepare.index("jsr vtime_load_initial_deadline") < prepare.index(
        "vtime_prepare_enforce_mode:"
    )
    assert "beq vtime_prepare_enforce_mode" in prepare
    assert prepare.index("vtime_prepare_enforce_mode:") < prepare.index(
        "bit #VTIME_FLAG_INTERPRETER_ONLY"
    )
    for gate in ("$071A", "$073A", "$0736", "$073C"):
        assert prepare.count(f"stz {gate}") == 1

    scan = body(interp, "lh_sched:\n", "lh_sched_vtime_go:\n")
    assert "lda $0736" in scan
    assert "bne lh_sched_vtime_go" in scan
    assert "clc\n    rts" in scan

    scan_body = body(interp, "lh_sched_vtime_go:\n", "lh_sched_end:\n")
    assert "lhs_rdbe leaves X=a5+2" in scan_body
    assert "txa\n    inc a\n    inc a" in scan_body
    assert scan_body.index("    tay") < scan_body.index("    txa")

    switch_out = body(
        escbank, "entry_swo:\n", "entry_swo_vtime_go:\n"
    )
    assert "lda.l $F28000" in switch_out
    assert "and #$0002" in switch_out
    assert "jml.l lh_nofire" in switch_out
    assert escbank.index("entry_swo_vtime_go:") < escbank.index("ora #$0007")

    # Select and switch-in already have fail-before-commit gates; the VTIME
    # prepare path clears these exact gate words only in interpreter-only mode.
    select = body(escbank, "lhs_sel:\n", "lsel_go:\n")
    assert "lda $0736" in select and "jml.l irq_none" in select
    switch_in = body(escbank, "entry_swin:\n", "swin_go:\n")
    assert "lda $073C" in switch_in and "jml.l lh_nofire" in switch_in
    print("VTIME interpreter-only scheduler fallback source guard: green")


if __name__ == "__main__":
    main()
