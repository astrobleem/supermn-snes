#!/usr/bin/env python3
"""Guard the VTIME-only `$0818` hardware-deadline handoff pack.

The check intentionally distinguishes the restored production ROM from the
explicitly named diagnostic.  It does not make a gameplay or timing-acceptance
claim; it prevents either image from silently borrowing the other image's
countdown seam.
"""

from __future__ import annotations

import hashlib
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PRODUCTION = ROOT / "build" / "interp.sfc"
DIAGNOSTIC = ROOT / "build" / "interp-vtime-taskmask-pacing-experiment-v2.sfc"
EXPECTED_PRODUCTION_SHA256 = "5c7eeb37a1f532180a6c349718ccadb63ab1a30b9af215651b91dd3571c483d9"
EXPECTED_DIAGNOSTIC_SHA256 = "0de24905e8cf45ba58623b4d1905676f2beec63f843f8dc6a7fcdfc69f7ea016"

ESC5_RELEASE_FILE = 0x2C8000 + 0x7BA1  # $99:FBA1
VTIME_RELEASE_FILE = 0x328000 + 0x3400  # $F2:B400
LEGACY_RELEASE = bytes.fromhex("a9010085ac")
VTIME_RELEASE_JSL = bytes.fromhex("2200b4f2ea")
VTIME_RELEASE_BODY = bytes.fromhex(
    "c230af0080f2f017af004040c91ec7d00eaf024040f008"
    "a901008f1840406ba9010085ac6b"
)


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> None:
    if sha256(PRODUCTION) != EXPECTED_PRODUCTION_SHA256:
        raise AssertionError("active ROM is not the restored 5c7e production image")
    if sha256(DIAGNOSTIC) != EXPECTED_DIAGNOSTIC_SHA256:
        raise AssertionError("VTIME handoff diagnostic hash changed; revalidate it")
    production = PRODUCTION.read_bytes()
    diagnostic = DIAGNOSTIC.read_bytes()
    if production[ESC5_RELEASE_FILE : ESC5_RELEASE_FILE + 5] != LEGACY_RELEASE:
        raise AssertionError("production `$0818` release no longer writes legacy `$AC=1`")
    if diagnostic[ESC5_RELEASE_FILE : ESC5_RELEASE_FILE + 5] != VTIME_RELEASE_JSL:
        raise AssertionError("diagnostic `$0818` release no longer JSLs to `$F2:B400`")
    if diagnostic[VTIME_RELEASE_FILE : VTIME_RELEASE_FILE + len(VTIME_RELEASE_BODY)] != VTIME_RELEASE_BODY:
        raise AssertionError("diagnostic `$F2:B400` release helper changed")
    if diagnostic[0x328000] != 1 or production[0x328000] != 0:
        raise AssertionError("VTIME enable byte leaked between diagnostic and production")
    source = (ROOT / "src" / "vtime.pasm").read_text(encoding="utf-8")
    required_source = (
        "lda $0734",
        "lda $400002",
        "vtime_paced_release:",
        "sta VT_DUE",
        ".org $B400",
        ".org $B500",
    )
    missing = [text for text in required_source if text not in source]
    if missing:
        raise AssertionError("VTIME activation/release source lost: " + ", ".join(missing))
    print("VTIME post-boot `$0818` handoff pack regression: green")


if __name__ == "__main__":
    main()
