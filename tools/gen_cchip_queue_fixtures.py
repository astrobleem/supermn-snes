#!/usr/bin/env python3
"""Convert retained organic MAME $F01B20 hits into three-way fixtures."""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
from pathlib import Path


REG_NAMES = tuple(f"D{index}" for index in range(8)) + tuple(
    f"A{index}" for index in range(8)
)
TARGET = 0xF01B20


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--capture", type=Path, required=True)
    parser.add_argument("--pre-failure-state", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    capture_log = args.capture / "capture.jsonl"
    for label, path in (
        ("capture log", capture_log),
        ("pre-failure state", args.pre_failure_state),
    ):
        if not path.is_file():
            parser.error(f"missing {label}: {path}")
    if args.output.exists():
        parser.error(f"output already exists: {args.output}")

    hits = [
        json.loads(line)
        for line in capture_log.read_text(encoding="utf-8").splitlines()
        if line.strip()
        and json.loads(line).get("event") == "generic_pc"
        and int(json.loads(line).get("offset", -1)) == TARGET
    ]
    if not hits:
        raise RuntimeError("capture contains no $F01B20 generic-PC hits")

    args.output.mkdir(parents=True)
    for hit in hits:
        ordinal = int(hit["ordinal"])
        name = f"f01b20-organic-hit-{ordinal:03d}"
        case_dir = args.output / name
        case_dir.mkdir()
        source_work = args.capture / f"{hit['name']}.work.bin"
        work = source_work.read_bytes()
        if len(work) != 0x10000:
            raise RuntimeError(f"{source_work} is not a 64 KiB work dump")
        work_path = case_dir / "entry.work.bin"
        shutil.copyfile(source_work, work_path)

        regs = {name: int(hit[name]) & 0xFFFFFFFF for name in REG_NAMES}
        sp = regs["A7"] & 0xFFFF
        return_pc = int.from_bytes(work[sp : sp + 4], "big") & 0xFFFFFF
        a4 = regs["A4"] & 0xFFFF
        metadata = {
            "event": "fixture",
            "target": f"{TARGET:06X}",
            "return_pc": f"{return_pc:06X}",
            "tick": int(hit["tick"]),
            "frame": int(hit["frame"]),
            "state": int.from_bytes(work[a4 : a4 + 2], "big"),
            "substate": int.from_bytes(work[a4 + 2 : a4 + 4], "big"),
            "sr": int(hit["SR"]) & 0xFFFF,
            "regs": regs,
            "a4": f"{regs['A4'] & 0xFFFFFF:06X}",
            "a7": f"{regs['A7'] & 0xFFFFFF:06X}",
            "work": str(work_path.resolve()),
            "work_sha256": sha256(work_path),
            "stack_window_hex": work[
                max(0, sp - 32) : min(len(work), sp + 64)
            ].hex(),
            "object_record_hex": work[
                max(0, a4 - 32) : min(len(work), a4 + 64)
            ].hex(),
            "pre_failure_state": str(args.pre_failure_state.resolve()),
            "pre_failure_state_sha256": sha256(args.pre_failure_state),
            "intervention": {
                "kind": "exact_mame_organic_pc_watch_fixture",
                "source_capture": str(capture_log.resolve()),
                "source_capture_sha256": sha256(capture_log),
                "source_work": str(source_work.resolve()),
                "source_work_sha256": sha256(source_work),
                "work_ram_injection": False,
            },
        }
        (case_dir / "entry.json").write_text(
            json.dumps(metadata, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )

    print(
        json.dumps(
            {
                "result": "green",
                "fixtures": len(hits),
                "output": str(args.output.resolve()),
                "pre_failure_state_sha256": sha256(args.pre_failure_state),
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
