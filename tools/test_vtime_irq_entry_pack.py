#!/usr/bin/env python3
"""Guard VTIME reload ownership and the diagnostic-only IRQ entry hook."""

from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def body(source: str, start: str, end: str) -> str:
    return source[source.index(start):source.index(end)]


def symbol(path: Path, name: str) -> int:
    for line in path.read_text(encoding="utf-8-sig").splitlines():
        fields = line.split()
        if len(fields) >= 2 and fields[1] == name:
            return int(fields[0].split(":", 1)[1], 16)
    raise AssertionError(f"missing symbol {name} in {path}")


def main() -> None:
    vtime_source = (ROOT / "src/vtime.pasm").read_text(encoding="utf-8")
    enabled_source = (ROOT / "src/vtime_enabled.pasm").read_text(
        encoding="utf-8"
    )
    interp_source = (ROOT / "src/interp.pasm").read_text(encoding="utf-8")
    packer = (ROOT / "tools/build_interp_rom.py").read_text(encoding="utf-8")

    reload_body = body(
        vtime_source, "vtime_reload_virtual:\n", "vtime_reload_end:\n"
    )
    assert "sta VT_TMP" in reload_body
    assert "sbc VT_TMP" in reload_body
    reload_clear = reload_body[reload_body.index("vtime_reload_clear:\n"):]
    assert "sta VT_COST" in reload_clear
    assert "sta VT_COST\n    lda VT_REMAIN_LO" not in reload_body
    assert "VTIME_IRQ_ENTRY_ACCOUNTING_FIX=1" in enabled_source

    assert "VT_CLOCK_PHASE=$40401C" in vtime_source
    assert "VT_CLOCK_VALID=$40401E" in vtime_source
    assert "VT_CLOCK_INITIAL_PHASE=$0001" in vtime_source
    ensure_body = body(
        vtime_source, "vtime_clock_ensure:\n", "vtime_mod5:\n"
    )
    assert "cmp VT_PHASE" in ensure_body
    assert "adc #VT_FRACTION_INCREMENT" in ensure_body
    assert "adc VT_CLOCK_PHASE" in ensure_body
    assert "ora #$8000" in ensure_body
    assert "sta VT_CLOCK_VALID" in ensure_body

    consume_body = body(
        vtime_source, "vtime_consume_virtual:\n", "vtime_consume_end:\n"
    )
    assert "vtime_clock_" not in consume_body

    charge_body = body(
        vtime_source, "vtime_charge_units:\n", "vtime_charge_units_due:\n"
    )
    assert "vtime_clock_" not in charge_body
    assert "jsr vtime_clock_ensure" in reload_body
    assert "jsr vtime_clock_finish_interval" in reload_body
    assert "jsr vtime_clock_load_next_deadline" in reload_body

    irq_body = body(
        vtime_source, "vtime_irq_enter:\n", "vtime_irq_enter_end:\n"
    )
    assert "jsr vtime_clock_current_phase" in irq_body
    assert irq_body.index("sta VT_COST") < irq_body.index("lda #$001B")
    assert "sbc VT_TMP" in irq_body
    assert "cmp #$0019" in irq_body
    assert "adc #$0005" in irq_body
    assert "#$0021" not in irq_body
    assert irq_body.count("jsr vtime_charge_units") == 1
    assert "lda VT_COST" not in irq_body
    assert "sta VT_COST" in irq_body
    assert "jsl.l $F28500" in irq_body
    assert "jsl.l $E98000" in irq_body

    seam = body(
        interp_source,
        "take_irq_vtime_entry_seam:\n",
        "take_irq_vtime_entry_seam_end:\n",
    )
    assert seam.count("    nop\n") == 9
    assert 'if vtime_enabled:' in packer
    assert 'vtime_off("vtime_irq_enter")' in packer

    assert symbol(ROOT / "src/vtime.sym", "vtime_irq_enter") == 0x85A0
    assert symbol(ROOT / "src/vtime.sym", "vtime_load_next_deadline_end") <= 0x85A0
    assert symbol(ROOT / "src/vtime.sym", "vtime_irq_enter_end") <= 0x8600
    start = symbol(ROOT / "src/interp.sym", "take_irq_vtime_entry_seam")
    end = symbol(ROOT / "src/interp.sym", "take_irq_vtime_entry_seam_end")
    assert end - start == 9

    rom = (ROOT / "build/interp.sfc").read_bytes()
    diagnostic = rom[0x328000] & 0x01
    expected = bytes.fromhex("22a085f2") if diagnostic else bytes.fromhex("ea" * 4)
    for offset in (start - 0x8000, start):
        assert rom[offset:offset + 4] == expected

    if diagnostic:
        assert symbol(ROOT / "src/vtime.sym", "vtime_clock_ensure") == 0x8200
        assert symbol(ROOT / "src/vtime.sym", "vtime_clock_finish_interval") < 0x8400
        assert symbol(ROOT / "src/vtime.sym", "vtime_clock_current_phase") < 0x8400
        assert symbol(ROOT / "src/vtime.sym", "vtime_clock_load_next_deadline") < 0x8400
        vtime_bin = (ROOT / "src/vtime.bin").read_bytes()
        irq_start = symbol(ROOT / "src/vtime.sym", "vtime_irq_enter") - 0x8000
        irq_end = symbol(ROOT / "src/vtime.sym", "vtime_irq_enter_end") - 0x8000
        irq_bytes = vtime_bin[irq_start:irq_end]
        assert bytes.fromhex("20") in irq_bytes
        charge_start = symbol(ROOT / "src/vtime.sym", "vtime_charge_units") - 0x8000
        assert vtime_bin[charge_start:charge_start + 4] == bytes.fromhex("8f124040")

    print("VTIME IRQ entry ownership/pack regression: green")


if __name__ == "__main__":
    main()
