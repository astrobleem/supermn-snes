#!/usr/bin/env python3
"""Test the prepared-BG DMA chunk budget from a retained Mesen checkpoint.

This is an intervened checkpoint diagnostic, never acceptance evidence.  It
patches only the WRAM mirror of ``bg_tile_run_dma_chunks`` and then checks the
four records that the exact d01db972 fresh run truncated at every $1500-byte
boundary.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
sys.path.insert(0, "/home/chad/Mesen2/python")

import capture_mesen211_transitions as capture  # noqa: E402
import mesen_mcp.session as _session  # noqa: E402

_session.validate_mesen_build = lambda *_args, **_kwargs: None
from mesen_mcp import McpSession  # noqa: E402


DEFAULT_MESEN = Path("/home/chad/Mesen2/bin/linux-x64/Release/Mesen")
WRAM_HELPER = 0x18A00  # $7F:8A00 in the linear WRAM domain
ORIGINAL = bytes.fromhex(
    "c220a5d6c90115901938e9001548e2209c0543a9158d0643"
    "20bd88c2206885d680e0e220a5d68d0543a5d78d064320bd882860"
)
EXPECTED_RECORDS = {
    42: "7877527f13ca5c43fc26d337850e529e2bd58560e979aecb1d947306e8499b21",
    84: "49b029b9077ed5e628ae23df25bb38fcca2923267d468df0ad7b94655e08c333",
    126: "01c8d3e68006eca9a84b71b03881352a88b3be2df224109eb0b9757558090336",
    168: "2e8359ae613c9c9698f6e94562025e22376c512a717fa9bc26234f33a7a543f0",
}


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--rom", type=Path, required=True)
    parser.add_argument("--state", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--frames", type=int, default=60)
    parser.add_argument("--chunk-size", type=lambda value: int(value, 0), default=0x1400)
    parser.add_argument("--mesen", type=Path, default=DEFAULT_MESEN)
    parser.add_argument("--port", type=int, default=44931)
    return parser.parse_args()


def patched_helper(chunk_size: int) -> bytes:
    if chunk_size <= 0 or chunk_size > 0xFF00 or chunk_size & 0xFF:
        raise ValueError("diagnostic chunk size must be a positive whole $100 bytes")
    data = bytearray(ORIGINAL)
    threshold = chunk_size + 1
    data[5:7] = threshold.to_bytes(2, "little")
    data[11:13] = chunk_size.to_bytes(2, "little")
    data[20] = chunk_size >> 8
    changed = [index for index, pair in enumerate(zip(ORIGINAL, data)) if pair[0] != pair[1]]
    if changed != [6, 12, 20]:
        raise AssertionError(f"unexpected helper patch byte offsets: {changed}")
    return bytes(data)


def main() -> int:
    args = parse_args()
    for path in (args.rom, args.state, args.mesen):
        if not path.is_file():
            raise FileNotFoundError(path)
    if args.frames <= 0:
        raise ValueError("--frames must be positive")
    output = args.output.resolve()
    if output.exists():
        raise SystemExit(f"refusing existing output: {output}")
    output.mkdir(parents=True)
    capture.configure_dotnet8()

    patched = patched_helper(args.chunk_size)
    with McpSession(
        rom=args.rom.resolve(),
        mesen=args.mesen.resolve(),
        cwd=ROOT,
        port=args.port,
        boot_wait=6.0,
        socket_timeout=120.0,
        stderr_log=output / "emulator.stderr.log",
    ) as m:
        m.pause()
        m.load_state(args.state.resolve())
        m.pause()
        start_frame = int(m.get_state().get("frameCount", 0))
        observed = bytes(m.read_memory("snesWorkRam", WRAM_HELPER, len(ORIGINAL)))
        if observed != ORIGINAL:
            raise RuntimeError(
                "checkpoint WRAM helper does not match d01db972 source: "
                f"{observed.hex()}"
            )
        m.write_memory("snesWorkRam", WRAM_HELPER, patched.hex())
        verified = bytes(m.read_memory("snesWorkRam", WRAM_HELPER, len(patched)))
        if verified != patched:
            raise RuntimeError("WRAM helper patch did not verify")

        target = start_frame + args.frames
        current = start_frame
        while current < target:
            m.run_frames(min(30, target - current))
            next_frame = int(m.get_state().get("frameCount", 0))
            if next_frame <= current:
                raise RuntimeError(f"video frame did not advance beyond {current}")
            current = next_frame
        m.pause()
        records = []
        for slot, expected in EXPECTED_RECORDS.items():
            raw = bytes(m.read_memory("snesVideoRam", 0x2000 + slot * 0x80, 0x80))
            observed_hash = hashlib.sha256(raw).hexdigest()
            records.append(
                {
                    "slot": slot,
                    "expected_sha256": expected,
                    "observed_sha256": observed_hash,
                    "match": observed_hash == expected,
                }
            )
        screenshot = capture.take_screenshot(m, output / "final.png")
        boundary = capture.snapshot(m)

    report = {
        "schema": 1,
        "scope": "intervened same-ROM checkpoint BG DMA budget diagnostic; not acceptance",
        "rom_sha256": sha256(args.rom),
        "state_sha256": sha256(args.state),
        "start_frame": start_frame,
        "end_frame": current,
        "chunk_size": args.chunk_size,
        "runtime_memory_writes": [
            {
                "region": "$7F:8A00-$7F:8A32 WRAM renderer mirror",
                "before_sha256": hashlib.sha256(ORIGINAL).hexdigest(),
                "after_sha256": hashlib.sha256(patched).hexdigest(),
                "reason": "reduce prepared-BG DMA chunk for focused VBlank-budget test",
            }
        ],
        "records": records,
        "all_records_match": all(row["match"] for row in records),
        "boundary": {
            key: boundary[key]
            for key in (
                "frame",
                "tick",
                "halt",
                "presented_scrollx",
                "obj_dma_pending",
                "obj_published_valid",
            )
        },
        "screenshot": screenshot,
    }
    (output / "results.json").write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(
        json.dumps(
            {
                "all_records_match": report["all_records_match"],
                "records": records,
                "results": str(output / "results.json"),
            },
            sort_keys=True,
        )
    )
    return 0 if report["all_records_match"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
