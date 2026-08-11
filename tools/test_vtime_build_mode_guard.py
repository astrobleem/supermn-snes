#!/usr/bin/env python3
"""Guard the mutually exclusive normal and VTIME diagnostic pack checks."""

from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
BUILD = ROOT / "tools" / "build_interp.sh"


def main() -> None:
    source = BUILD.read_text(encoding="utf-8")
    expected = '''if [ "${VTIME:-0}" = "1" ]; then
  # The opt-in cycle-clock image deliberately replaces the legacy five-byte
  # countdown seam.  The ordinary-pack assertion must stay enabled for every
  # production build, but it is inapplicable to this explicitly diagnostic
  # image.
  echo "VTIME diagnostic pack: disabled-pack assertion intentionally skipped"
else
  python3 tools/test_vtime_disabled_pack.py
fi
'''
    if expected not in source:
        raise AssertionError(
            "build_interp.sh must skip only the disabled-pack assertion in "
            "an explicit VTIME=1 diagnostic build"
        )
    print("VTIME build-mode guard regression: green")


if __name__ == "__main__":
    main()
