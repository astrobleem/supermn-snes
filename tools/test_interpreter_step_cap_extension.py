#!/usr/bin/env python3
"""Pin the full-movie interpreter lifetime guard and v7 patch seams."""

from __future__ import annotations

import ast
import hashlib
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "src/interp.pasm"
BUILDER = ROOT / "tools/build_v7_step_cap_extended.py"
ORDINARY = ROOT / "build/interp.sfc"
V7 = (
    ROOT
    / "build/playback-watcher-20260811/"
    "v7-input-delayed-migrated14745-to14750-v2/run/campaign-rom.sfc"
)
V8 = (
    ROOT
    / "build/interp-vtime-interpreter-only-paced0818-dbcc-irq-entry-vpa-"
    "input-delayed-stepcap-v8.sfc"
)


def main() -> None:
    source = SOURCE.read_text(encoding="utf-8")
    assert (
        "cmp #$FFFF           ; lifetime guard (~4.29B): beyond the full retained movie"
        in source
    )
    assert "cmp #$0800           ; safety cap raised" not in source

    tree = ast.parse(BUILDER.read_text(encoding="utf-8"))
    constants: dict[str, object] = {}
    for node in tree.body:
        if not isinstance(node, ast.Assign) or len(node.targets) != 1:
            continue
        target = node.targets[0]
        if not isinstance(target, ast.Name):
            continue
        if target.id in {"V7_SHA256", "PATCH_OFFSETS"}:
            constants[target.id] = ast.literal_eval(node.value)
    assert constants == {
        "V7_SHA256": (
            "45c9096dfda3d4203878c18954725ff4814f23f4e28a1e623f3cf07b647e6c72"
        ),
        "PATCH_OFFSETS": (0x005143, 0x00D143),
    }, constants

    ordinary = ORDINARY.read_bytes()
    assert hashlib.sha256(ordinary).hexdigest() == (
        "11aefd2cfdc6a0c28ad6a69e607d4e5c7f1884db6757b8f385f675d51f965f90"
    )
    for offset in constants["PATCH_OFFSETS"]:
        assert ordinary[offset : offset + 2] == bytes.fromhex("ffff")

    v7 = V7.read_bytes()
    v8 = V8.read_bytes()
    assert len(v7) == len(v8) == 0x400000
    assert hashlib.sha256(v8).hexdigest() == (
        "162b757cef1f2976efe6199df7dba963253a1927fbb12cbcc807c5692ed2ad5c"
    )
    differences = [
        offset for offset, (before, after) in enumerate(zip(v7, v8))
        if before != after
    ]
    assert differences == [0x005143, 0x005144, 0x00D143, 0x00D144]
    for offset in constants["PATCH_OFFSETS"]:
        assert v7[offset : offset + 2] == bytes.fromhex("0008")
        assert v8[offset : offset + 2] == bytes.fromhex("ffff")

    print("interpreter lifetime-guard extension regression: green")


if __name__ == "__main__":
    main()
