#!/usr/bin/env python3
"""Cycle-profile the SA-1 production renderer-manifest phases.

This loads a production checkpoint and records non-pausing execution hooks for
the boundary manifest while holding real Right+B input.  It is checkpointed
phase attribution, not FPS evidence.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import statistics
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
HOOK_LABELS = {
    "manifest_entry": ("render_manifest_build", 0),
    "bg_select": ("rmb_bg_select", 0),
    "prepare_entry": ("rmb_prepare_bg", 0),
    "prepare_collect": ("rpb_collect_cell", 0),
    "prepare_collect_done": ("rpb_collect_done", 0),
    "prepare_sort_done": ("rpb_sort_done", 0),
    "prepare_hash_built": ("rpb_hash_built", 0),
    "prepare_map": ("rpb_map_cell", 0),
    "prepare_success": ("rpb_success", 0),
    "obj_begin": ("rmb_obj_begin", 0),
    "obj_done": ("rmb_obj_done", 0),
    # The assembler's end label is one byte past RTL.
    "manifest_end": ("render_manifest_build_end", -1),
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--rom", type=Path, required=True)
    parser.add_argument("--state", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--nexen", type=Path, default=DEFAULT_NEXEN)
    parser.add_argument(
        "--symbols", type=Path, default=ROOT / "src/escbank8.sym"
    )
    parser.add_argument("--port", type=int, default=7969)
    parser.add_argument("--frames", type=int, default=240)
    parser.add_argument("--chunk-frames", type=int, default=60)
    return parser.parse_args()


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def manifest_hooks(symbols: Path) -> dict[str, int]:
    labels: dict[str, int] = {}
    pattern = re.compile(r"^([0-9A-Fa-f]{2}):([0-9A-Fa-f]{4})\s+(\S+)$")
    for line in symbols.read_text(encoding="utf-8").splitlines():
        match = pattern.match(line.strip())
        if match:
            labels[match.group(3)] = int(match.group(2), 16)
    missing = [label for label, _ in HOOK_LABELS.values() if label not in labels]
    if missing:
        raise SystemExit(f"missing manifest symbols in {symbols}: {', '.join(missing)}")
    return {
        phase: 0x9E0000 | ((labels[label] + adjustment) & 0xFFFF)
        for phase, (label, adjustment) in HOOK_LABELS.items()
    }


def summary(values: list[int]) -> dict[str, Any]:
    return {
        "count": len(values),
        "minimum": min(values, default=None),
        "median": statistics.median(values) if values else None,
        "mean": statistics.fmean(values) if values else None,
        "maximum": max(values, default=None),
    }


def main() -> int:
    args = parse_args()
    for path in (args.rom, args.state, args.nexen, args.symbols):
        if not path.is_file():
            raise SystemExit(f"missing input: {path}")
    if args.output.exists():
        raise SystemExit(f"refusing existing output: {args.output}")
    args.output.mkdir(parents=True)

    hooks = manifest_hooks(args.symbols)
    events: list[dict[str, Any]] = []
    with McpSession(
        rom=args.rom.resolve(),
        mesen=args.nexen.resolve(),
        cwd=ROOT,
        port=args.port,
        boot_wait=6.0,
        socket_timeout=300.0,
        stderr_log=args.output / "nexen.stderr.log",
    ) as m:
        m.pause()
        m.load_state(args.state.resolve())
        m.pause()
        handles = {
            m.add_exec_hook(address, cpu_type="Sa1"): label
            for label, address in hooks.items()
        }
        m.drain_notifications(timeout=0.05)
        m.tool(
            "set_input",
            {
                "port": 0,
                "buttons": McpSession.BTN_RIGHT | McpSession.BTN_B,
                "hold": True,
            },
        )
        remaining = args.frames
        while remaining:
            count = min(args.chunk_frames, remaining)
            result = m.run_frames(count)
            advanced = int(result.get("framesAdvanced", 0))
            if advanced <= 0:
                raise RuntimeError(f"no frame progress: {result!r}")
            remaining -= advanced
            for notification in m.drain_notifications(timeout=0.10):
                if notification.get("method") != "notifications/mesen/hookFired":
                    continue
                params = dict(notification.get("params", {}))
                label = handles.get(int(params.get("handle", -1)))
                if label is None:
                    continue
                events.append(
                    {
                        "label": label,
                        "address": int(params.get("address", 0)),
                        "cycle": int(params.get("cycleCount", 0)),
                        "frame": int(params.get("frame", 0)),
                    }
                )
        final_tick = int.from_bytes(m.read_memory("Sa1Memory", 0x0760, 2), "little")

    raw = args.output / "hooks.jsonl"
    raw.write_text("".join(json.dumps(event, sort_keys=True) + "\n" for event in events))
    manifests = []
    current: dict[str, Any] | None = None
    for event in events:
        if event["label"] == "manifest_entry":
            current = {"entry": event}
            continue
        if current is None:
            continue
        current.setdefault(event["label"], event)
        if event["label"] == "manifest_end":
            if "obj_begin" in current and "obj_done" in current:
                current["cycles"] = event["cycle"] - current["entry"]["cycle"]
                current["pre_obj_cycles"] = (
                    current["obj_begin"]["cycle"] - current["entry"]["cycle"]
                )
                current["obj_scan_cycles"] = (
                    current["obj_done"]["cycle"] - current["obj_begin"]["cycle"]
                )
                current["epilogue_cycles"] = (
                    event["cycle"] - current["obj_done"]["cycle"]
                )
                manifests.append(current)
            current = None

    result = {
        "scope": "checkpointed SA-1 renderer-manifest cycle attribution; not FPS",
        "rom": str(args.rom),
        "rom_sha256": sha256(args.rom),
        "state": str(args.state),
        "state_sha256": sha256(args.state),
        "nexen_sha256": sha256(args.nexen),
        "frames": args.frames,
        "final_tick": final_tick,
        "event_counts": {
            label: sum(event["label"] == label for event in events)
            for label in hooks
        },
        "hook_addresses": {label: f"{address:06X}" for label, address in hooks.items()},
        "symbols": str(args.symbols),
        "symbols_sha256": sha256(args.symbols),
        "manifest_cycles": summary([item["cycles"] for item in manifests]),
        "pre_obj_cycles": summary([item["pre_obj_cycles"] for item in manifests]),
        "obj_scan_cycles": summary([item["obj_scan_cycles"] for item in manifests]),
        "epilogue_cycles": summary([item["epilogue_cycles"] for item in manifests]),
        "manifests": manifests,
        "hooks": {"path": str(raw), "sha256": sha256(raw)},
    }
    target = args.output / "results.json"
    target.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
    print(
        json.dumps(
            {
                "manifest_cycles": result["manifest_cycles"],
                "obj_scan_cycles": result["obj_scan_cycles"],
                "pre_obj_cycles": result["pre_obj_cycles"],
                "results": str(target),
            },
            sort_keys=True,
        ),
        flush=True,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
