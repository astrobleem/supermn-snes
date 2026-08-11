#!/usr/bin/env python3
"""Guard DBcc dynamic timing's four-byte emulated D-register stride."""

from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
VTIME = ROOT / "src" / "vtime.pasm"
VTIME_ENABLED = ROOT / "src" / "vtime_enabled.pasm"
BUILD = ROOT / "tools" / "build_interp.sh"


def body(source: str, start: str, end: str) -> str:
    return source[source.index(start) : source.index(end, source.index(start))]


def main() -> int:
    source = VTIME.read_text(encoding="utf-8")
    enabled = VTIME_ENABLED.read_text(encoding="utf-8")
    build = BUILD.read_text(encoding="utf-8")
    pre = body(
        source,
        "vtime_dbcc_condition_false:",
        "vtime_dbcc_expired:",
    )
    post = body(
        source,
        "vtime_dynamic_charge_post_dbcc:",
        "vtime_dynamic_charge_post_expired:",
    )
    register_lookup = (
        "and #$0007\n"
        "    asl a\n"
        ".ifdef VTIME_DBCC_REGISTER_STRIDE_FIX\n"
        "    asl a\n"
        ".endif\n"
        "    tax\n"
        "    lda $00,x"
    )
    assert register_lookup in pre, "pre-state DBcc lookup must index Dn at 4*n"
    assert register_lookup in post, "post-state DBcc lookup must index Dn at 4*n"
    assert "VTIME_DBCC_REGISTER_STRIDE_FIX=1" in enabled
    assert '.include "src/vtime.pasm"' in enabled
    assert 'vtime_source=src/vtime.pasm' in build
    assert 'vtime_source=src/vtime_enabled.pasm' in build
    assert [register * 4 for register in range(8)] == [
        0x00, 0x04, 0x08, 0x0C, 0x10, 0x14, 0x18, 0x1C
    ]
    print("VTIME DBcc register-stride regression: green")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
