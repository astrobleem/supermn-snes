#!/usr/bin/env python3
"""Dump IRAM and SA-1 DMA registers from two same-ROM diagnostic states."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, "/home/chad/Mesen2/python")

import mesen_mcp.session as _session

_session.validate_mesen_build = lambda *_args, **_kwargs: None
from mesen_mcp import McpSession


DEFAULT_NEXEN = Path(
    "/mnt/sdc1/Nexen-r5-20260712/"
    "bin/linux-x64/Release/linux-x64/publish/Nexen"
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--rom", type=Path, default=ROOT / "build/interp.sfc")
    parser.add_argument("--before", type=Path, required=True)
    parser.add_argument("--after", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--nexen", type=Path, default=DEFAULT_NEXEN)
    parser.add_argument("--port", type=int, default=7494)
    return parser.parse_args()


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def changed_runs(left: bytes, right: bytes) -> list[dict[str, Any]]:
    runs: list[dict[str, Any]] = []
    start: int | None = None
    for index, (a, b) in enumerate(zip(left, right)):
        if a != b and start is None:
            start = index
        if a == b and start is not None:
            runs.append(
                {
                    "start": start,
                    "end": index,
                    "before": left[start:index].hex(),
                    "after": right[start:index].hex(),
                }
            )
            start = None
    if start is not None:
        runs.append(
            {
                "start": start,
                "end": len(left),
                "before": left[start:].hex(),
                "after": right[start:].hex(),
            }
        )
    return runs


def main() -> int:
    args = parse_args()
    rom = args.rom.resolve()
    before_path = args.before.resolve()
    after_path = args.after.resolve()
    nexen = args.nexen.resolve()
    output = args.output.resolve()
    for label, path in (
        ("ROM", rom),
        ("before state", before_path),
        ("after state", after_path),
        ("Nexen", nexen),
    ):
        if not path.is_file() or path.stat().st_size == 0:
            raise SystemExit(f"{label} missing or empty: {path}")
    if output.exists():
        raise SystemExit(f"refusing existing output: {output}")
    output.mkdir(parents=True)
    os.environ["DOTNET_ROOT"] = "/home/chad/.dotnet10"
    os.environ["PATH"] = "/home/chad/.dotnet10:" + os.environ.get("PATH", "")

    snapshots: dict[str, dict[str, Any]] = {}
    with McpSession(
        rom=rom,
        mesen=nexen,
        cwd=ROOT,
        port=args.port,
        boot_wait=8.0,
        socket_timeout=180.0,
        stderr_log=output / "nexen.stderr.log",
    ) as m:
        for label, path in (("before", before_path), ("after", after_path)):
            m.pause()
            m.load_state(path)
            m.pause()
            iram = bytes(m.read_memory("Sa1Memory", 0, 0x800))
            snes_view = bytes(m.read_memory("snesMemory", 0x3000, 0x800))
            dma = bytes(m.read_memory("Sa1Memory", 0x2230, 0x0A))
            cpu = dict(m.get_cpu_state("Sa1"))
            (output / f"{label}.iram.bin").write_bytes(iram)
            (output / f"{label}.snes-iram-view.bin").write_bytes(snes_view)
            snapshots[label] = {
                "state": str(path),
                "state_sha256": sha256(path),
                "iram_sha256": hashlib.sha256(iram).hexdigest(),
                "views_match": iram == snes_view,
                "mailbox_0300_0303": iram[0x300:0x304].hex(),
                "window_02e0_0340": iram[0x2E0:0x340].hex(),
                "dma_2230_2239": dma.hex(),
                "sa1_cpu": cpu,
            }

    before = (output / "before.iram.bin").read_bytes()
    after = (output / "after.iram.bin").read_bytes()
    result = {
        "rom": str(rom),
        "rom_sha256": sha256(rom),
        "nexen": str(nexen),
        "nexen_sha256": sha256(nexen),
        "snapshots": snapshots,
        "changed_bytes": sum(a != b for a, b in zip(before, after)),
        "changed_runs": changed_runs(before, after),
    }
    (output / "comparison.json").write_text(
        json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(json.dumps(result, sort_keys=True), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
