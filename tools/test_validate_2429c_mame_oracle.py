#!/usr/bin/env python3
"""Ensure `$02429C` three-way fixtures cannot use mutable MAME by accident."""

from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "tools/validate_2429c_native.py"


def main() -> int:
    source = SOURCE.read_text(encoding="utf-8")
    for required in (
        "from mame_0287 import MAME, environment as mame_environment",
        "from mame_0287 import identity as mame_identity",
        "oracle = mame_identity()",
        "os.environ.update(mame_environment())",
        '"mame": oracle',
        "mame=str(MAME)",
        "--prestate-dir",
        "pre-execution MAME and Nexen states",
        "pre_state=pre_state",
    ):
        assert required in source, f"missing exact-MAME guard: {required}"
    assert 'mame="/snap/bin/mame"' not in source
    print("$02429C three-way MAME oracle guard: pinned 0.287 required")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
