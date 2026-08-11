#!/usr/bin/env python3
"""Keep the Stage-3 span profiler on the emulator-launching MCP wrapper."""

from __future__ import annotations

from pathlib import Path


def main() -> int:
    source = (
        Path(__file__).resolve().parents[1] / "tools/profile_sa1_span.py"
    ).read_text(encoding="utf-8")
    assert "with base.McpSession(" in source
    assert "with controls.McpSession(" not in source
    print("SA-1 span-profiler launch regression: green")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
