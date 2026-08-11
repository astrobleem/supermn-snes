#!/usr/bin/env python3
"""Capture arcade $01E7C0 state immediately before its two DIVS opcodes."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MAME_TRACE = ROOT / "tools/mame-trace"
MAME_MCP = Path("/home/chad/mame-mcp")
DEFAULT_FIXTURE_DIR = (
    ROOT
    / "build/playtest-investigation-20260725"
    / "1e7c0-campaign-differential-a08508d-tick6619-v1-fixtures"
)
ENTRY_PC = 0x01E7C0
SEAMS = (
    0x01E94A,
    0x01E980,
    0x01E99C,
    0x01E9A4,
    0x01E9DA,
    0x01E9EA,
    0x01EA0A,
    0x01EA16,
    0x01EA3E,
    0x01EA48,
    0x01EA60,
    0x01EA6A,
    0x01EA8A,
    0x01EA96,
    0x01EAE0,
    0x01EB00,
    0x01EB10,
    0x01EB4E,
    0x01EB50,
    0x01EB8E,
    0x01EB96,
    0x01EB9E,
    0x01EBA8,
    0x01EBAE,
    0x01EBB2,
    0x01E7BE,
)
WORK_BASE = 0xF00000
MAPPED_WORK_SIZE = 0x4000
REG_NAMES = [f"D{index}" for index in range(8)] + [
    f"A{index}" for index in range(8)
]

sys.path.insert(0, str(MAME_MCP))
from mame_mcp.session import MameSession  # noqa: E402


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--fixture-dir", type=Path, default=DEFAULT_FIXTURE_DIR)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    metadata = args.fixture_dir / "case-00.json"
    work = args.fixture_dir / "case-00.work.bin"
    if not metadata.is_file() or not work.is_file():
        parser.error(f"missing case-00 fixture under {args.fixture_dir}")
    if args.output.exists():
        parser.error(f"output already exists: {args.output}")
    return args


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def main() -> int:
    args = parse_args()
    args.fixture_dir = args.fixture_dir.resolve()
    args.output = args.output.resolve()
    args.output.mkdir(parents=True)
    metadata_path = args.fixture_dir / "case-00.json"
    work_path = args.fixture_dir / "case-00.work.bin"
    fixture = json.loads(metadata_path.read_text(encoding="utf-8"))
    work = work_path.read_bytes()
    if hashlib.sha256(work).hexdigest() != fixture["work_sha256"]:
        raise RuntimeError("fixture work SHA-256 mismatch")
    regs = {name: int(fixture["regs"][name]) for name in REG_NAMES}
    sr = int(fixture["sr"])

    os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
    mame = MameSession(
        mame="/snap/bin/mame",
        system="superman",
        rompath=str(MAME_TRACE / "roms"),
        workdir=str(MAME_TRACE),
        state_directory=str(MAME_TRACE / "sta"),
        extra_args=["-video", "none", "-sound", "none", "-nothrottle"],
    )
    captures: list[dict] = []
    try:
        mame.launch(boot_wait=25)
        for seam in SEAMS:
            mame.pause()
            mame.write_block(WORK_BASE, work[:MAPPED_WORK_SIZE])
            for name in REG_NAMES[:-1]:
                mame.set_reg(name, regs[name])
            # Isolate the injected function from unrelated live IRQ6.
            mame.set_reg("SR", sr | 0x0700)
            mame.set_reg("USP", regs["A7"])
            mame.set_reg("SP", regs["A7"])
            mame.set_reg("PC", ENTRY_PC)
            captured = mame.cmd(
                "capture_at_pc",
                pc=seam,
                addr=WORK_BASE,
                len=MAPPED_WORK_SIZE,
                nth=1,
                maxFrames=60,
                timeout=60,
            )
            captured_regs = captured.get("registers")
            if not captured_regs:
                captures.append(
                    {
                        "pc": f"{seam:06X}",
                        "hit": False,
                        "response": captured,
                    }
                )
                continue
            work_hex = str(captured["hex"])
            seam_work = bytes.fromhex(work_hex)
            work_output = args.output / f"mame-{seam:06x}.work.bin"
            work_output.write_bytes(seam_work)
            captures.append(
                {
                    "pc": f"{seam:06X}",
                    "hit": True,
                    "registers": {
                        name: int(captured_regs[name]) & 0xFFFFFFFF
                        for name in REG_NAMES[:-1]
                    }
                    | {
                        "A7": int(captured_regs["SP"]) & 0xFFFFFFFF,
                    },
                    "sr": int(captured_regs["SR"]) & 0xFFFF,
                    "work_path": str(work_output),
                    "work_sha256": hashlib.sha256(seam_work).hexdigest(),
                }
            )
    finally:
        mame.stop()

    result = {
        "scope": (
            "MAME 0.287 original arcade code injected from the exact organic "
            "$01E7C0 campaign fixture; prefetch captures at both DIVS seams; "
            "function-local oracle evidence, not an organic playthrough"
        ),
        "mame": "/snap/bin/mame 0.287",
        "fixture_metadata": str(metadata_path),
        "fixture_metadata_sha256": sha256(metadata_path),
        "fixture_work": str(work_path),
        "fixture_work_sha256": sha256(work_path),
        "entry_pc": f"{ENTRY_PC:06X}",
        "entry_registers": regs,
        "entry_sr": sr,
        "captures": captures,
    }
    result_path = args.output / "result.json"
    result_path.write_text(
        json.dumps(result, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(
        json.dumps(
            {
                "result": str(result_path),
                "captures": [
                    {
                        "pc": capture["pc"],
                        "hit": capture["hit"],
                        **(
                            {
                                "d3": f"{capture['registers']['D3']:08X}",
                                "d4": f"{capture['registers']['D4']:08X}",
                                "d6": f"{capture['registers']['D6']:08X}",
                                "a7": f"{capture['registers']['A7']:08X}",
                                "sr": f"{capture['sr']:04X}",
                            }
                            if capture["hit"]
                            else {}
                        ),
                    }
                    for capture in captures
                ],
            },
            sort_keys=True,
        ),
        flush=True,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
