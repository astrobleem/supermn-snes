#!/usr/bin/env python3
"""Guard the diagnostic-only `$0818` pre-mutation interpreter fallback."""

from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def body(source: str, start: str, end: str) -> str:
    begin = source.index(start)
    return source[begin : source.index(end, begin)]


def main() -> None:
    interp = (ROOT / "src/interp.pasm").read_text(encoding="utf-8")
    esc5 = (ROOT / "src/escbank5.pasm").read_text(encoding="utf-8")
    generator = (ROOT / "tools/gen_escbank5_syms.py").read_text(encoding="utf-8")
    packer = (ROOT / "tools/build_interp_rom.py").read_text(encoding="utf-8")

    idle = body(interp, "    cmp #$0818\n", "lh_chk_3b84:\n")
    assert "jml $99FBB0" in idle
    assert "lh_0818_after_gateway:\n    bcc lh818_pass" in idle

    gateway = body(
        esc5, "lh_0818_vtime_gateway:\n", "lh_0818_vtime_gateway_end:\n"
    )
    assert gateway.index("lda.l $F28000") < gateway.index("and #$0002")
    assert gateway.index("jml.l lh_nofire") < gateway.index("jsl.l $99FB00")
    assert gateway.index("jsl.l $99FB00") < gateway.index(
        "jml.l lh_0818_after_gateway"
    )
    for symbol in ("lh_nofire", "lh_0818_after_gateway"):
        assert f'"{symbol}"' in generator
    assert 'VTIME_0818_INTERPRETER_FALLBACK' in packer
    assert 'vtime_mode |= 0x04' in packer
    assert 'gateway_mode_immediate = paced_gateway - 0x8000 + 5' in packer
    assert 'esc5_packed[gateway_mode_immediate] = 0x04' in packer
    print("VTIME opt-in $0818 fallback source guard: green")


if __name__ == "__main__":
    main()
