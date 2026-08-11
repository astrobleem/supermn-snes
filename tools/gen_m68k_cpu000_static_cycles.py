#!/usr/bin/env python3
"""Generate the packed CPU-000 static-cycle baseline used by the SNES timer.

The virtual-IRQ implementation needs a compact, reproducible baseline for
every decoded MC68000 opcode.  This tool mirrors MAME 0.287's runtime opcode
table construction using its supplied ``m68kmake.py`` and ``m68k_in.lst`` and
writes precisely 65,536 unsigned-byte entries.  Dynamic forms are corrected
at runtime; this artifact is intentionally only the source-authenticated
static baseline.

It neither starts an emulator nor reads/writes an arcade ROM.  The caller must
provide the exact MAME source pair so generation is loud if the oracle changes.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

import audit_m68k_cycle_model as static_audit


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--m68kmake", type=Path, required=True)
    parser.add_argument("--m68k-list", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--manifest", type=Path, required=True)
    args = parser.parse_args()
    for label, path in (("MAME m68kmake.py", args.m68kmake), ("MAME m68k_in.lst", args.m68k_list)):
        if not path.is_file():
            parser.error(f"missing {label}: {path}")
    if args.output.exists() or args.manifest.exists():
        parser.error("refusing to overwrite a generated static-cycle artifact")
    root = args.m68kmake.parents[4]
    makefile = root / "makefile"
    if not makefile.is_file() or '#define BARE_BUILD_VERSION "0.287"' not in makefile.read_text(
        encoding="utf-8", errors="replace"
    ):
        parser.error(f"MAME source is not 0.287: {root}")
    return args


def main() -> int:
    args = parse_args()
    table = static_audit.build_static_cycles(
        static_audit.load_m68kmake(args.m68kmake), args.m68k_list
    )
    if len(table) != 0x10000 or any(value < 0 or value > 0xFF for value in table):
        raise RuntimeError("CPU-000 table is not a 64 KiB byte table")
    payload = bytes(table)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_bytes(payload)
    report = {
        "scope": (
            "source-authenticated MAME 0.287 CPU-000 static opcode-cycle baseline; "
            "runtime dynamic costs remain outside this generated table"
        ),
        "inputs": {
            "m68kmake": {"path": str(args.m68kmake.resolve()), "sha256": sha256(args.m68kmake)},
            "m68k_list": {"path": str(args.m68k_list.resolve()), "sha256": sha256(args.m68k_list)},
            "mame_makefile": {
                "path": str((args.m68kmake.parents[4] / "makefile").resolve()),
                "sha256": sha256(args.m68kmake.parents[4] / "makefile"),
            },
        },
        "output": {
            "path": str(args.output.resolve()),
            "sha256": sha256(args.output),
            "bytes": len(payload),
            "maximum_cycles": max(table),
            "zero_or_illegal_entries": table.count(0),
        },
    }
    args.manifest.parent.mkdir(parents=True, exist_ok=True)
    args.manifest.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({"output": report["output"], "manifest": str(args.manifest)}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
