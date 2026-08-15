#!/usr/bin/env python3
"""Trace the first reset boot PPU initialization writes in Mesen 2.1.1."""

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

import mesen_mcp.session as _session  # noqa: E402

_session.validate_mesen_build = lambda *_args, **_kwargs: None
from mesen_mcp import McpSession  # noqa: E402


EXEC_HOOKS = {
    "video_boot_init_extended": 0xE9A081,
    "boot_screen_init": 0xE9F000,
    "boot_screen_init_end": 0xE9F13E,
}
WRITE_HOOKS = {
    "inidisp_write": 0x2100,
    "bgmode_write": 0x2105,
    "tm_write": 0x212C,
    "nmitimen_write": 0x4200,
    "mdmaen_write": 0x420B,
}


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def configure_dotnet8() -> None:
    dotnet8 = "/home/chad/.dotnet8"
    dotnet10 = "/home/chad/.dotnet10"
    os.environ["DOTNET_ROOT"] = dotnet8
    current = [
        item
        for item in os.environ.get("PATH", "").split(":")
        if item and item not in (dotnet8, dotnet10)
    ]
    os.environ["PATH"] = ":".join([dotnet8, dotnet10, *current])


def hook_events(
    notifications: list[dict[str, Any]], handles: dict[int, str]
) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    for notification in notifications:
        if notification.get("method") != "notifications/mesen/hookFired":
            continue
        params = notification.get("params", {})
        handle = int(params.get("handle", -1))
        label = handles.get(handle)
        if label is None:
            continue
        events.append(
            {
                "label": label,
                "frame": int(params.get("frame", 0)),
                "cycle_count": int(params.get("cycleCount", 0)),
                "address": int(params.get("address", 0)),
                "value": int(params.get("value", 0)),
                "cpu_type": params.get("cpuType"),
                "kind": params.get("kind"),
            }
        )
    return events


def ppu_summary(m: McpSession) -> dict[str, Any]:
    ppu = m.get_ppu_state()
    return {
        "frame": int(m.get_state().get("frameCount", 0)),
        "bg_mode": int(ppu.get("bgMode", -1)),
        "brightness": int(ppu.get("brightness", -1)),
        "forced_blank": bool(ppu.get("forcedBlank", False)),
        "main_screen_layers": int(ppu.get("mainScreenLayers", -1)),
        "boot_activity": int(m.read_memory("snesWorkRam", 0x1F1B, 1)[0]),
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--rom", type=Path, required=True)
    parser.add_argument("--movie", type=Path, required=True)
    parser.add_argument("--emulator", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--port", type=int, default=44050)
    parser.add_argument("--frames", type=int, default=2)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.frames <= 0:
        raise SystemExit("--frames must be positive")
    for path in (args.rom, args.movie, args.emulator):
        if not path.is_file():
            raise FileNotFoundError(path)
    if args.output.exists():
        raise SystemExit(f"output already exists: {args.output}")
    args.output.mkdir(parents=True)
    configure_dotnet8()
    handles: dict[int, str] = {}
    with McpSession(
        rom=args.rom.resolve(),
        mesen=args.emulator.resolve(),
        cwd=ROOT,
        port=args.port,
        boot_wait=6.0,
        socket_timeout=120.0,
        stderr_log=args.output / "emulator.stderr.log",
    ) as m:
        m.pause()
        reset_response = m.reset_emulator()
        m.pause()
        initial = ppu_summary(m)
        for label, address in EXEC_HOOKS.items():
            handles[m.add_exec_hook(address, cpu_type="Snes")] = label
        for label, address in WRITE_HOOKS.items():
            handles[m.add_write_hook(address, cpu_type="Snes")] = label
        m.drain_notifications(timeout=0.05)
        run_response = m.run_frames(args.frames)
        m.pause()
        notifications = m.drain_notifications(timeout=1.0)
        for handle in handles:
            m.remove_hook(handle)
        final = ppu_summary(m)

    events = hook_events(notifications, handles)
    counts = {
        label: sum(event["label"] == label for event in events)
        for label in (*EXEC_HOOKS, *WRITE_HOOKS)
    }
    report = {
        "schema": 1,
        "scope": (
            "same-emulator reset first-frame passive boot PPU initialization "
            "trace; movie hash is provenance only"
        ),
        "rom": str(args.rom.resolve()),
        "rom_sha256": sha256(args.rom),
        "movie": str(args.movie.resolve()),
        "movie_sha256": sha256(args.movie),
        "emulator": str(args.emulator.resolve()),
        "emulator_sha256": sha256(args.emulator),
        "runtime_memory_writes": [],
        "reset_response": reset_response,
        "run_response": run_response,
        "initial": initial,
        "final": final,
        "hook_addresses": {
            **{label: f"{address:06X}" for label, address in EXEC_HOOKS.items()},
            **{label: f"{address:04X}" for label, address in WRITE_HOOKS.items()},
        },
        "counts": counts,
        "events": events,
    }
    target = args.output / "results.json"
    target.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    print(json.dumps({"counts": counts, "final": final, "report": str(target)}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
