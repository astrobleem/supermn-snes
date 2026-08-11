#!/usr/bin/env python3
"""Guard the Stage-3 measurement harness's selected-oracle startup path.

The safe Nexen publish requires .NET 10 and the compatible MCP session shim.
Accidentally restoring the legacy Mesen-only imports/settings makes the harness
time out before it can load the retained state, which can otherwise be
misreported as a Stage-3 failure.
"""

from __future__ import annotations

import ast
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "tools" / "measure_stage3_checkpoint.py"


def main() -> int:
    text = SOURCE.read_text(encoding="utf-8")
    tree = ast.parse(text, filename=str(SOURCE))
    ast_names = {
        node.id
        for node in ast.walk(tree)
        if isinstance(node, ast.Name)
    }
    assert "nexen_base" in ast_names, "Nexen-compatible MCP session import vanished"
    assert "trace.configure_dotnet8()" not in text, (
        "selected Nexen oracle is being forced back onto the .NET-8 runtime"
    )
    assert "with nexen_base.McpSession(" in text, (
        "measurement no longer uses the Nexen-compatible MCP session"
    )
    assert "configure_dotnet(args.mesen)" in text, (
        "measurement no longer selects the requested emulator runtime"
    )
    assert "Nexen safe-checkpoint publish" in text, (
        "Nexen results would again be mislabeled as Mesen evidence"
    )
    print("Stage-3 measurement oracle regression guard OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
