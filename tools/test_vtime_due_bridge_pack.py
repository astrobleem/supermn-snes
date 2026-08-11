#!/usr/bin/env python3
"""Guard the VTIME due-to-retained-IRQ delivery bridge.

The check is deliberately structural: it proves that both a native block
deadline and the `$0818` hardware-paced release arm the one-countdown legacy
entrance in the isolated diagnostic.  It does not claim that the diagnostic is
correct, that it has common native coverage, or that the ROM is releasable.
"""

from __future__ import annotations

import hashlib
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PRODUCTION = ROOT / "build" / "interp.sfc"
DIAGNOSTIC = ROOT / "build" / "interp-vtime-choke-gateway-experiment-v7.sfc"
PRODUCTION_SHA256 = "5c7eeb37a1f532180a6c349718ccadb63ab1a30b9af215651b91dd3571c483d9"
DIAGNOSTIC_SHA256 = "b28f72c7f74f5cb35f9e5908f74b363bd5b15e3873d9b489f049202eb78d8209"
VTIME_FILE_BASE = 0x328000


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def symbol(name: str) -> int:
    for line in (ROOT / "src" / "vtime.sym").read_text(encoding="utf-8-sig").splitlines():
        fields = line.split()
        if len(fields) >= 2 and fields[1] == name:
            return int(fields[0].split(":", 1)[1], 16)
    raise AssertionError(f"missing VTIME symbol: {name}")


def body(rom: bytes, name: str, size: int) -> bytes:
    offset = symbol(name)
    if not 0x8000 <= offset < 0x10000:
        raise AssertionError(f"VTIME symbol outside F2 payload: {name}=${offset:04X}")
    file_offset = VTIME_FILE_BASE + offset - 0x8000
    return rom[file_offset : file_offset + size]


def main() -> None:
    if sha256(PRODUCTION) != PRODUCTION_SHA256:
        raise AssertionError("active ROM is not the restored production image")
    if sha256(DIAGNOSTIC) != DIAGNOSTIC_SHA256:
        raise AssertionError("due-bridge diagnostic hash changed; revalidate it")
    diagnostic = DIAGNOSTIC.read_bytes()
    bridge = bytes.fromhex("a901008f18404085ac")
    for name in ("vtime_charge_units_due", "vtime_paced_release"):
        # Both tails must raise VT_DUE then arm `$AC=1` before their carry/RTL.
        if bridge not in body(diagnostic, name, 0x80):
            raise AssertionError(f"{name} no longer bridges a virtual due event to `$AC=1`")
    print("VTIME due-to-retained-IRQ bridge pack regression: green")


if __name__ == "__main__":
    main()
