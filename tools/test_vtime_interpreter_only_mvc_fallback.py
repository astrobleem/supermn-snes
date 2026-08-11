#!/usr/bin/env python3
"""Guard the diagnostic-only MOVE.L run-collapse fallback and pack seams."""

from __future__ import annotations

import hashlib
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
BASE = ROOT / "build/interp-vtime-e00f-gate-restore-scheduler-0818-mvc-fallback-v1.sfc"
CANDIDATE = ROOT / "build/interp-vtime-interpreter-only-e00f-gate-restore-scheduler-0818-mvc-fallback-v1.sfc"
BASE_SHA256 = "a4dd611eb7fdbb90faa9d6d47b9e3fdebe9e48172b58c32d3b7c2f13878b2cee"
CANDIDATE_SHA256 = "a49eedc775bc50e65b3740965ea857c1591c4a57f613616e4d1c69119d5abacf"


def body(source: str, start: str, end: str) -> str:
    begin = source.index(start)
    return source[begin : source.index(end, begin)]


def main() -> None:
    vtime = (ROOT / "src/vtime.pasm").read_text(encoding="utf-8")
    packer = (ROOT / "tools/build_interp_rom.py").read_text(encoding="utf-8")
    audit = (ROOT / "tools/audit_vtime_accelerated_boundaries.py").read_text(
        encoding="utf-8"
    )

    gateway = body(vtime, "vtime_mvc_gateway:\n", "vtime_mvc_gateway_end:\n")
    assert gateway.index("bit #VTIME_FLAG_INTERPRETER_ONLY") < gateway.index(
        "bne vtime_mvc_interpret"
    )
    assert "lda $44\n    jml.l $0095F2" in gateway
    assert "vtime_mvc_interpret:\n    jml.l $00FA00" in gateway

    assert 'mvc_check = interp_symbol("mvc_check")' in packer
    assert 'op_move_g = interp_symbol("op_move_g")' in packer
    assert 'mvc_prefix = bytes.fromhex("c230a544")' in packer
    assert 'mvc_vtime_gateway = bytes.fromhex("5cd1b4f2")' in packer
    assert "if vtime_enabled:\n        ROM[mvc_offset" in packer
    assert "vtime_mvc_payload_start" in packer
    assert "vtime_mvc_payload_end" in packer
    assert "move_l_run_collapse" in audit
    assert '"src/interp.pasm", "mvc_check"' in audit

    base = BASE.read_bytes()
    candidate = CANDIDATE.read_bytes()
    assert hashlib.sha256(base).hexdigest() == BASE_SHA256
    assert hashlib.sha256(candidate).hexdigest() == CANDIDATE_SHA256
    assert len(base) == len(candidate) == 0x400000
    assert [
        offset
        for offset, (before, after) in enumerate(zip(base, candidate, strict=True))
        if before != after
    ] == [0x328000]
    assert base[0x328000] == 0x01 and candidate[0x328000] == 0x03
    for offset in (0x0015EE, 0x0095EE):
        assert candidate[offset : offset + 4] == bytes.fromhex("5cd1b4f2")
    assert candidate[0x32B4D1 : 0x32B4E9] == bytes.fromhex(
        "c230af0080f229ff00890200d006a5445cf295005c00fa00"
    )
    print("VTIME interpreter-only mvc fallback source/pack guard: green")


if __name__ == "__main__":
    main()
