#!/usr/bin/env python3
"""Project MCP bridge for the MCP-enabled Nexen build.

The reusable ``mesen_mcp`` package owns the stdio/TCP transport, but its build
validator only accepts the older split-file Mesen layout (Mesen + Mesen.dll +
MesenCore.so).  Nexen's Linux publish is a self-contained executable, so use the
same transport with a layout-appropriate validation shim.

Configuration remains compatible with ``mesen_mcp``:
MESEN_EXE, MESEN_ROM, MESEN_CWD, and optional MESEN_PORT.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

from mesen_mcp import bridge


def validate_nexen_build(executable: Path | str) -> None:
    """Fail early on a missing or obviously wrong Nexen executable."""
    path = Path(executable)
    if not path.is_file():
        raise RuntimeError(f"Nexen executable not found: {path}")
    if not os.access(path, os.X_OK):
        raise RuntimeError(f"Nexen executable is not executable: {path}")
    if path.name != "Nexen":
        raise RuntimeError(f"expected a Nexen executable, got: {path}")


bridge.validate_mesen_build = validate_nexen_build


if __name__ == "__main__":
    sys.exit(bridge.main())
