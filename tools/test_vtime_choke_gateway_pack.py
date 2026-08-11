#!/usr/bin/env python3
"""Guard the VTIME-only choke-gateway experiment's exact ROM seams.

This verifies packaging and long-bank targets only.  It deliberately makes no
claim about timer correctness, fresh boot, Stage 3, rate, or promotion.
"""

from __future__ import annotations

import hashlib
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PRODUCTION = ROOT / "build" / "interp.sfc"
DIAGNOSTIC = ROOT / "build" / "interp-vtime-choke-gateway-experiment-v6.sfc"
PRODUCTION_SHA256 = "5c7eeb37a1f532180a6c349718ccadb63ab1a30b9af215651b91dd3571c483d9"
DIAGNOSTIC_SHA256 = "d4bc57e6610d148db6200b5096a589a4630db5fc0a9d7395f527541476a2a863"

ILOOP_OFFSETS = (0x00A5, 0x80A5)
IFETCH_OFFSETS = (0x00EB, 0x80EB)
CHOKE_OFFSETS = (0x7980, 0xF980)
DBG_FETCH_OFFSETS = (0x6281, 0xE281)
VTIME_CHOKE_FILE = 0x32B480

LEGACY_CONSUME = bytes.fromhex("a5ac3a85ac")
FETCH_SKIP = bytes.fromhex("8001eaad2e07")
LEGACY_CHOKE = bytes.fromhex(
    "c230ad3a07f020a542f0034c20d3a540c9e40cf00dc9be13f008"
    "c9fa08f0034ce8d2685c00f99460eaea"
)
CHOKE_GATEWAY = bytes.fromhex(
    "c230a52ef00f2280b4f2d005685ca580005c81e20060"
) + bytes(42 - 22)
VTIME_CHOKE = bytes.fromhex(
    "c230af004040c91ec7f01c220180f2af004040c91ec7d024"
    "af024040f01ea9007085aca901006baf024040f0de220084f2"
    "f00d220180f2a9007085aca901006b220085f2a9010085aa"
    "220080e9a900006b"
)


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> None:
    if sha256(PRODUCTION) != PRODUCTION_SHA256:
        raise AssertionError("active ROM is not the restored production image")
    if sha256(DIAGNOSTIC) != DIAGNOSTIC_SHA256:
        raise AssertionError("choke-gateway diagnostic hash changed; revalidate it")
    production = PRODUCTION.read_bytes()
    diagnostic = DIAGNOSTIC.read_bytes()
    for offset in ILOOP_OFFSETS:
        if production[offset : offset + 5] != LEGACY_CONSUME:
            raise AssertionError(f"production countdown changed at ${offset:06X}")
        if diagnostic[offset : offset + 5] != LEGACY_CONSUME:
            raise AssertionError(f"diagnostic countdown is not legacy at ${offset:06X}")
    for offset in IFETCH_OFFSETS:
        if diagnostic[offset : offset + len(FETCH_SKIP)] != FETCH_SKIP:
            raise AssertionError(f"diagnostic still calls dbg_fetch at ${offset:06X}")
    for offset in CHOKE_OFFSETS:
        if production[offset : offset + len(LEGACY_CHOKE)] != LEGACY_CHOKE:
            raise AssertionError(f"production choke moved at ${offset:06X}")
        if diagnostic[offset : offset + len(CHOKE_GATEWAY)] != CHOKE_GATEWAY:
            raise AssertionError(f"diagnostic choke gateway moved at ${offset:06X}")
    for offset in DBG_FETCH_OFFSETS:
        if diagnostic[offset : offset + len(LEGACY_CHOKE)] != LEGACY_CHOKE:
            raise AssertionError(f"diagnostic relocated choke moved at ${offset:06X}")
    actual_helper = diagnostic[VTIME_CHOKE_FILE : VTIME_CHOKE_FILE + len(VTIME_CHOKE)]
    if actual_helper != VTIME_CHOKE:
        raise AssertionError("diagnostic `$F2:B480` helper or a long-bank call changed")
    if bytes.fromhex("22018000") in actual_helper or bytes.fromhex("22008400") in actual_helper:
        raise AssertionError("diagnostic choke helper leaked a bank-$00 local JSL target")
    source = (ROOT / "src" / "vtime.pasm").read_text(encoding="utf-8")
    for target in ("jsl.l $F28001", "jsl.l $F28400", "jsl.l $F28500"):
        if target not in source:
            raise AssertionError(f"explicit VTIME long-bank target missing: {target}")
    print("VTIME choke-gateway pack regression: green")


if __name__ == "__main__":
    main()
