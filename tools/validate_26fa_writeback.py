#!/usr/bin/env python3
"""Focused regression for the native $0026FA screen-shake RMW path.

The arcade routine performs two conditional ``SUBI.W #1,$1B18(A5)``
operations.  A stale native body evaluated those subtractions in the SA-1
accumulator but never committed the result to work RAM, leaving the shake
duration permanently at eight.  This validator combines a source/layout
guard with captured MAME/native-off/native-on boundary states.  SNES boundary
``T`` is paired with MAME's completed update ``T-1``; the two configurations
must agree with the arcade on the shake words at both supplied boundaries.

The capture directories are intentionally supplied by the caller.  This
keeps the validator honest about provenance and lets it reject a missing or
non-resumable focused run instead of silently treating a visual match as
proof.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
WORK_SIZE = 0x10000
SHAKE_OFFSETS = (0x1B16, 0x1B18, 0x1B1A)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--mame-dir", type=Path)
    parser.add_argument("--native-off-dir", type=Path)
    parser.add_argument("--native-on-dir", type=Path)
    parser.add_argument("--ticks", default="1,2")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument(
        "--source-only",
        action="store_true",
        help="run only the packed-source guard; no capture directories are needed",
    )
    args = parser.parse_args()
    ticks = sorted({int(item, 0) for item in args.ticks.split(",")})
    if not args.source_only:
        if len(ticks) < 2 or any(tick < 1 for tick in ticks):
            parser.error("--ticks must contain at least two positive SNES boundary ticks")
        missing = [
            name
            for name in ("mame_dir", "native_off_dir", "native_on_dir")
            if getattr(args, name) is None
        ]
        if missing:
            parser.error("capture mode requires --mame-dir, --native-off-dir, and --native-on-dir")
    args.ticks = ticks
    if args.output.exists():
        parser.error(f"output already exists: {args.output}")
    return args


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def read_work(path: Path) -> bytes:
    data = path.read_bytes()
    if len(data) != WORK_SIZE:
        raise RuntimeError(f"{path}: expected 64 KiB work RAM, got {len(data)}")
    return data


def be16(data: bytes, offset: int) -> int:
    return int.from_bytes(data[offset : offset + 2], "big")


def shake(data: bytes) -> dict[str, int]:
    return {
        f"F0{offset:04X}": be16(data, offset)
        for offset in SHAKE_OFFSETS
    }


def read_summary(directory: Path) -> dict[str, Any]:
    path = directory / "summary.json"
    if not path.is_file():
        raise RuntimeError(f"missing capture summary: {path}")
    return json.loads(path.read_text(encoding="utf-8"))


def capture_state(directory: Path, prefix: str, tick: int) -> tuple[Path, bytes]:
    path = directory / f"{prefix}-tick-{tick:05d}.work.bin"
    if not path.is_file():
        raise RuntimeError(f"missing captured work state: {path}")
    return path, read_work(path)


def source_guard() -> dict[str, Any]:
    source_path = ROOT / "src" / "escbank.pasm"
    source = source_path.read_text(encoding="utf-8")
    segments = {
        "zero_offset_branch": source.split("Lf26fa_3:", 1)[1].split(
            "L26fa_2718:", 1
        )[0],
        "equal_offset_branch": source.split("Lf26fa_4:", 1)[1].split(
            "L26fa_272c:", 1
        )[0],
    }
    checks = {}
    for name, segment in segments.items():
        checks[f"{name}_subtract_present"] = "sbc #$0001" in segment
        checks[f"{name}_result_stored"] = "sta $80" in segment
        checks[f"{name}_shake_address_rebuilt"] = "adc #$1B18" in segment
        checks[f"{name}_writeback_present"] = "jsl.l writeword_l" in segment
        checks[f"{name}_x_published"] = "sta $A2" in segment
    expected_generated = {
        "source_subtract_count": sum(
            segment.count("sbc #$0001") for segment in segments.values()
        ),
        "source_writeword_count": sum(
            segment.count("jsl.l writeword_l") for segment in segments.values()
        ),
    }
    return {
        "path": str(source_path.resolve()),
        "sha256": sha256(source_path),
        "checks": checks,
        "counts": expected_generated,
        "green": all(checks.values()) and expected_generated == {
            "source_subtract_count": 2,
            "source_writeword_count": 2,
        },
    }


def main() -> int:
    args = parse_args()
    source = source_guard()
    if args.source_only:
        summary = {
            "result": "green" if source["green"] else "red",
            "classification": "native-HLE-RMW-writeback-source-guard",
            "scope": "packed $0026FA source/layout guard only; dynamic three-way capture is separate",
            "source_guard": source,
        }
        args.output.mkdir(parents=True)
        (args.output / "summary.json").write_text(
            json.dumps(summary, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        print(json.dumps({"result": summary["result"], "source_only": True}, sort_keys=True))
        return 0 if source["green"] else 1
    summaries = {
        "native_off": read_summary(args.native_off_dir),
        "native_on": read_summary(args.native_on_dir),
    }
    modes_green = (
        summaries["native_off"].get("gameplay_native") in {"off", "all-off"}
        and summaries["native_on"].get("gameplay_native") == "on"
    )
    rows = []
    for tick in args.ticks:
        mame_path, mame_work = capture_state(args.mame_dir, "mame", tick - 1)
        off_path, off_work = capture_state(args.native_off_dir, "snes", tick)
        on_path, on_work = capture_state(args.native_on_dir, "snes", tick)
        mame_shake = shake(mame_work)
        off_shake = shake(off_work)
        on_shake = shake(on_work)
        rows.append(
            {
                "snes_boundary_tick": tick,
                "mame_completion_tick": tick - 1,
                "mame": mame_shake,
                "native_off": off_shake,
                "native_on": on_shake,
                "mame_vs_native_off_equal": mame_shake == off_shake,
                "mame_vs_native_on_equal": mame_shake == on_shake,
                "native_off_vs_on_equal": off_shake == on_shake,
                "inputs": {
                    "mame": {"path": str(mame_path), "sha256": sha256(mame_path)},
                    "native_off": {"path": str(off_path), "sha256": sha256(off_path)},
                    "native_on": {"path": str(on_path), "sha256": sha256(on_path)},
                },
            }
        )
    state_green = all(
        row["mame_vs_native_off_equal"]
        and row["mame_vs_native_on_equal"]
        and row["native_off_vs_on_equal"]
        for row in rows
    )
    result = "green" if source["green"] and modes_green and state_green else "red"
    summary = {
        "result": result,
        "classification": "native-HLE-RMW-writeback" if result == "green" else "unresolved-screen-shake-differential",
        "scope": "focused $0026FA screen-shake duration writeback at paired MAME completion/SNES entry boundaries; not full-playthrough or FPS proof",
        "source_guard": source,
        "capture_modes_green": modes_green,
        "ticks": rows,
        "rom_hashes": {
            "native_off": summaries["native_off"].get("rom_sha256"),
            "native_on": summaries["native_on"].get("rom_sha256"),
        },
    }
    args.output.mkdir(parents=True)
    (args.output / "summary.json").write_text(
        json.dumps(summary, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(json.dumps({"result": result, "ticks": args.ticks}, sort_keys=True))
    return 0 if result == "green" else 1


if __name__ == "__main__":
    raise SystemExit(main())
