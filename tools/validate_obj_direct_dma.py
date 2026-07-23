#!/usr/bin/env python3
"""Compare two renderer ROMs at the same completed visual generation.

Both variants resume one organic production checkpoint, finish its in-flight
render before replacing the WRAM video-code mirror, hold real Right+B input,
and stop only when the requested generation completes.  CGRAM, OAM, and full
VRAM must then be byte-identical.  This is checkpointed renderer evidence, not
an end-to-end FPS measurement.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
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
RENDER_COMPLETE = 0x7F8924


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--baseline-rom", type=Path, required=True)
    parser.add_argument("--candidate-rom", type=Path, required=True)
    parser.add_argument("--state", type=Path, required=True)
    parser.add_argument("--generation", type=lambda value: int(value, 0), required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--nexen", type=Path, default=DEFAULT_NEXEN)
    parser.add_argument("--port", type=int, default=7951)
    return parser.parse_args()


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256(path: Path) -> str:
    return digest(path.read_bytes())


def le16(data: bytes) -> int:
    return int.from_bytes(data, "little")


def first_differences(left: bytes, right: bytes, limit: int = 64) -> list[int]:
    return [
        index
        for index, (a, b) in enumerate(zip(left, right))
        if a != b
    ][:limit]


def run_variant(
    label: str,
    rom: Path,
    args: argparse.Namespace,
    port: int,
) -> dict[str, Any]:
    with McpSession(
        rom=rom.resolve(),
        mesen=args.nexen.resolve(),
        cwd=ROOT,
        port=port,
        boot_wait=6.0,
        socket_timeout=300.0,
        stderr_log=args.output / f"{label}.stderr.log",
    ) as m:
        m.pause()
        m.load_state(args.state.resolve())
        m.pause()
        completion = m.add_exec_hook(RENDER_COMPLETE, cpu_type="Snes")
        m.drain_notifications(timeout=0.05)

        stale_result = m.run_until(max_frames=20, hook_handle=completion)
        m.pause()
        if (stale_result or {}).get("reason") != "hookFired":
            raise RuntimeError(f"{label}: in-flight checkpoint render did not complete")

        mirror = rom.read_bytes()[0x298000 : 0x298000 + 0x3000]
        for offset in range(0, len(mirror), 0x1000):
            m.write_memory(
                "snesWorkRam",
                0x18000 + offset,
                mirror[offset : offset + 0x1000].hex(),
            )
        if m.read_memory("snesWorkRam", 0x18000, len(mirror)) != mirror:
            raise RuntimeError(f"{label}: WRAM video mirror did not verify")
        m.tool(
            "set_input",
            {
                "port": 0,
                "buttons": McpSession.BTN_RIGHT | McpSession.BTN_B,
                "hold": True,
            },
        )

        completions = []
        for _ in range(128):
            result = m.run_until(max_frames=20, hook_handle=completion)
            m.pause()
            if (result or {}).get("reason") != "hookFired":
                raise RuntimeError(f"{label}: render timed out: {result!r}")
            generation = le16(m.read_memory("snesWorkRam", 0x89A4, 2))
            completions.append(
                {
                    "generation": generation,
                    "frame": int(m.get_state().get("frameCount", 0)),
                    "obj_slots": le16(m.read_memory("snesWorkRam", 0x00DE, 2)),
                    "queued_tiles": le16(
                        m.read_memory("snesWorkRam", 0x89C6, 2)
                    ),
                    "frames_advanced": int(result.get("framesAdvanced", 0)),
                }
            )
            if generation == args.generation:
                break
            if generation > args.generation:
                raise RuntimeError(
                    f"{label}: skipped target generation {args.generation}, "
                    f"observed {generation}"
                )
        else:
            raise RuntimeError(f"{label}: target generation was not reached")

        regions = {
            "cgram": m.read_memory("snesCgRam", 0, 0x0200),
            "oam": m.read_memory("snesSpriteRam", 0, 0x0220),
            "vram": m.read_memory("snesVideoRam", 0, 0x10000),
            "cgram_staging": m.read_memory("snesWorkRam", 0x8000, 0x0200),
            "oam_staging": m.read_memory("snesWorkRam", 0x8600, 0x0220),
            "obj_hash": m.read_memory("snesWorkRam", 0xA800, 0x0800),
        }
        region_records = {}
        for name, data in regions.items():
            target = args.output / f"{label}-{name}.bin"
            target.write_bytes(data)
            region_records[name] = {
                "path": str(target),
                "length": len(data),
                "sha256": digest(data),
            }
        screenshot_response = m.take_screenshot(format="path")
        screenshot = args.output / f"{label}.png"
        shutil.copy2(Path(screenshot_response["path"]), screenshot)
        return {
            "rom": str(rom),
            "rom_sha256": sha256(rom),
            "stale_result": stale_result,
            "completions": completions,
            "regions": region_records,
            "screenshot": str(screenshot),
            "screenshot_sha256": sha256(screenshot),
        }


def main() -> int:
    args = parse_args()
    for path in (args.baseline_rom, args.candidate_rom, args.state, args.nexen):
        if not path.is_file():
            raise SystemExit(f"missing input: {path}")
    if args.output.exists():
        raise SystemExit(f"refusing existing output: {args.output}")
    args.output.mkdir(parents=True)

    variants = {
        "baseline": run_variant("baseline", args.baseline_rom, args, args.port),
        "candidate": run_variant(
            "candidate", args.candidate_rom, args, args.port + 1
        ),
    }
    comparisons = {}
    for name in variants["baseline"]["regions"]:
        left = Path(variants["baseline"]["regions"][name]["path"]).read_bytes()
        right = Path(variants["candidate"]["regions"][name]["path"]).read_bytes()
        offsets = first_differences(left, right)
        comparisons[name] = {
            "equal": left == right,
            "differing_bytes": sum(a != b for a, b in zip(left, right)),
            "first_differing_offsets": offsets,
        }
    required = ["cgram", "oam", "vram"]
    result = {
        "scope": "same-generation checkpointed renderer differential; not FPS",
        "generation": args.generation,
        "state": str(args.state),
        "state_sha256": sha256(args.state),
        "variants": variants,
        "comparisons": comparisons,
        "hardware_equal": all(comparisons[name]["equal"] for name in required),
    }
    target = args.output / "results.json"
    target.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
    print(
        json.dumps(
            {
                "hardware_equal": result["hardware_equal"],
                "comparisons": comparisons,
                "results": str(target),
            },
            sort_keys=True,
        ),
        flush=True,
    )
    return int(not result["hardware_equal"])


if __name__ == "__main__":
    raise SystemExit(main())
