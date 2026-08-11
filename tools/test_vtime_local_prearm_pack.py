#!/usr/bin/env python3
"""Guard the VTIME diagnostic's local pre-arm gateways.

The accepted ROM must retain the old instruction countdown.  The explicitly
named diagnostic is allowed to replace it, but it must avoid every cross-bank
timer call until the established post-self-test `$072E` gate is nonzero.  This
is a pack-layout regression only, not timer, gameplay, or rate acceptance.
"""

from __future__ import annotations

import hashlib
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PRODUCTION = ROOT / "build" / "interp.sfc"
DIAGNOSTIC = ROOT / "build" / "interp-vtime-local-prearm-experiment-v3.sfc"
EXPECTED_PRODUCTION_SHA256 = "5c7eeb37a1f532180a6c349718ccadb63ab1a30b9af215651b91dd3571c483d9"
EXPECTED_DIAGNOSTIC_SHA256 = "1ea6ff85e73103705d957b6cd3dbc9e103776ebbe2e2009ee2d25cd44f79e79b"

ILOOP_OFFSETS = (0x00A5, 0x80A5)
IFETCH_OFFSETS = (0x00EB, 0x80EB)
DBG_FETCH_OFFSETS = (0x6281, 0xE281)
LOCAL_CONSUME_CALL = bytes.fromhex("208be2eaea")
LEGACY_CONSUME = bytes.fromhex("a5ac3a85ac")
IFETCH_ORIGINAL = bytes.fromhex("2081e2ad2e07")
LOCAL_GATEWAYS = bytes.fromhex(
    "a52ef005220180f26060"
    "a52ef005220084f260a5ac3a85ac60"
)


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> None:
    if sha256(PRODUCTION) != EXPECTED_PRODUCTION_SHA256:
        raise AssertionError("active ROM is not the restored 5c7e production image")
    if sha256(DIAGNOSTIC) != EXPECTED_DIAGNOSTIC_SHA256:
        raise AssertionError("local-prearm diagnostic hash changed; revalidate it")
    production = PRODUCTION.read_bytes()
    diagnostic = DIAGNOSTIC.read_bytes()
    for offset in ILOOP_OFFSETS:
        if production[offset : offset + 5] != LEGACY_CONSUME:
            raise AssertionError(f"production legacy countdown moved at ${offset:06X}")
        if diagnostic[offset : offset + 5] != LOCAL_CONSUME_CALL:
            raise AssertionError(f"diagnostic local-consume call moved at ${offset:06X}")
    for offset in IFETCH_OFFSETS:
        if diagnostic[offset : offset + len(IFETCH_ORIGINAL)] != IFETCH_ORIGINAL:
            raise AssertionError(f"diagnostic fetch call was cross-bank patched at ${offset:06X}")
    for offset in DBG_FETCH_OFFSETS:
        if diagnostic[offset : offset + len(LOCAL_GATEWAYS)] != LOCAL_GATEWAYS:
            raise AssertionError(f"diagnostic local gateway body moved at ${offset:06X}")
    print("retained VTIME local pre-arm pack regression: green")


if __name__ == "__main__":
    main()
