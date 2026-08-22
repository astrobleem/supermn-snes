#!/usr/bin/env python3
"""Compact fresh-boot reset-loop diagnostic.

This is evidence gathering only: it runs a bounded fresh boot, samples coarse
state, counts selected loop-hook execs, and retains only first hook examples.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from collections import Counter
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, "/home/chad/Mesen2/python")

import mesen_mcp.session as _session  # noqa: E402

_session.validate_mesen_build = lambda *_args, **_kwargs: None
from mesen_mcp import McpSession  # noqa: E402


DEFAULT_EMULATOR = ROOT / "tools" / "mesen211_mcp_controller.sh"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--rom", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--state", type=Path)
    parser.add_argument("--emulator", type=Path, default=DEFAULT_EMULATOR)
    parser.add_argument("--port", type=int, default=7670)
    parser.add_argument("--frames", type=int, default=6000)
    parser.add_argument("--chunk", type=int, default=100)
    parser.add_argument("--sample-every", type=int, default=500)
    parser.add_argument("--save-sample-states", action="store_true")
    parser.add_argument("--progress", action="store_true")
    parser.add_argument("--no-hooks", action="store_true")
    parser.add_argument("--watch-only-work", action="store_true")
    parser.add_argument(
        "--single-step-entries",
        type=int,
        default=0,
        help=(
            "retained-state diagnostic: enable interpreter test mode and retain "
            "this many consecutive 68000 instruction boundaries"
        ),
    )
    return parser.parse_args()


def configure_runtime(emulator: Path) -> None:
    dotnet8 = "/home/chad/.dotnet8"
    dotnet10 = "/home/chad/.dotnet10"
    selected = dotnet8 if emulator.name == "mesen211_mcp_controller.sh" else dotnet10
    os.environ["DOTNET_ROOT"] = selected
    path = [
        item
        for item in os.environ.get("PATH", "").split(":")
        if item and item not in (dotnet8, dotnet10)
    ]
    os.environ["PATH"] = ":".join([selected, dotnet8, dotnet10, *path])


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def le16(data: bytes) -> int:
    return data[0] | (data[1] << 8)


def le32(data: bytes) -> int:
    return le16(data[:2]) | (le16(data[2:4]) << 16)


def snap(m: McpSession) -> dict[str, Any]:
    state = m.get_state()
    snes = dict(m.get_cpu_state("Snes"))
    dp = bytes(m.read_memory("Sa1Memory", 0, 0x100))
    pc = le32(dp[0x40:0x44]) & 0x00FFFFFF
    return {
        "frame": int(state.get("frameCount", 0)),
        "pc68k": pc,
        "opcode": bytes(m.read_memory("snesMemory", 0xC10000 + pc, 2)).hex()
        if pc < 0x80000
        else None,
        "tick": le16(bytes(m.read_memory("Sa1Memory", 0x0760, 2))),
        "halt": le16(dp[0x4E:0x50]),
        "task_mask": le16(bytes(m.read_memory("snesMemory", 0x400002, 2))),
        "snes_cpu": {
            key: snes.get(key)
            for key in ("pc", "k", "sp", "ps", "a", "x", "y", "d", "dbr", "stopState")
        },
        "nmitimen_4200": int(bytes(m.read_memory("snesMemory", 0x004200, 1))[0]),
        "sa1_irq_status_2300": bytes(m.read_memory("snesMemory", 0x002300, 1)).hex(),
        "work_1c60_1c68": bytes(
            m.read_memory("snesMemory", 0x401C60, 8)
        ).hex(),
        "regs": {
            **{f"D{index}": le32(dp[index * 4:index * 4 + 4]) for index in range(8)},
            **{
                f"A{index}": le32(dp[0x20 + index * 4:0x24 + index * 4])
                for index in range(8)
            },
        },
    }


def main() -> int:
    args = parse_args()
    if args.output.exists():
        raise SystemExit(f"output exists: {args.output}")
    args.output.mkdir(parents=True)
    configure_runtime(args.emulator)

    result: dict[str, Any] = {
        "scope": "fresh-boot reset-loop/gm_memset diagnostic; not acceptance evidence",
        "rom": str(args.rom.resolve()),
        "rom_sha256": sha256(args.rom),
        "state": str(args.state.resolve()) if args.state else None,
        "state_sha256": sha256(args.state) if args.state else None,
        "frames": args.frames,
        "chunk": args.chunk,
        "sample_every": args.sample_every,
        "hooks": {},
        "hook_counts": {},
        "first_events": [],
        "samples": [],
    }
    hook_names = {
        "gm_verify_stub": 0x00F602,
        "gm_verify_far": 0x99F4A0,
        "gm_memset_far": 0x99F5C0,
        "gms_no": 0x99F5CF,
        "gms_tail": 0x99F66C,
        "write_sa1_1c62": 0x401C62,
        "write_snes_1c62": 0x401C62,
    }
    if args.watch_only_work:
        hook_names = {
            name: address
            for name, address in hook_names.items()
                if name.startswith("write_")
        }
    if args.no_hooks:
        hook_names = {}

    with McpSession(
        rom=args.rom.resolve(),
        mesen=args.emulator.resolve(),
        cwd=ROOT,
        port=args.port,
        boot_wait=0.0,
        socket_timeout=180.0,
        stderr_log=args.output / "emulator.stderr.log",
    ) as m:
        m.pause()
        if args.state:
            result["load_state"] = m.load_state(args.state.resolve())
            m.pause()
        if args.single_step_entries:
            if not args.state:
                raise RuntimeError("--single-step-entries requires --state")
            # Current symbol in src/interp.sym.  Test mode finishes the current
            # instruction at test_idle, then advances one interpreted 68000
            # instruction per $A0 acknowledgement without changing ROM bytes.
            test_idle = 0x00D12C
            result["scope"] = (
                "retained-state interpreter single-step diagnostic; test mode "
                "mutates IRAM control only; not production acceptance"
            )
            result["single_step"] = {
                "requested": args.single_step_entries,
                "test_idle": f"{test_idle:06X}",
                "rows": [],
            }
            m.write_memory("Sa1Memory", 0x007E, "0100")
            m.write_memory("Sa1Memory", 0x004E, "0000")
            m.write_memory("Sa1Memory", 0x00A0, "0100")
            handle = m.add_exec_hook(test_idle, cpu_type="Sa1")
            for index in range(args.single_step_entries):
                run = dict(m.run_until(max_frames=8, hook_handle=handle))
                row = {"index": index, "run": run, "state": snap(m)}
                result["single_step"]["rows"].append(row)
                if run.get("reason") != "hookFired" or row["state"]["halt"] in (
                    0xDEAD,
                    0xCAFE,
                ):
                    break
                m.write_memory("Sa1Memory", 0x004E, "0000")
                m.write_memory("Sa1Memory", 0x00A0, "0100")
            m.remove_hook(handle)
            rows = result["single_step"]["rows"]
            result["single_step"]["retained"] = len(rows)
            result["single_step"]["terminal"] = rows[-1] if rows else None
            result["final"] = snap(m)
            result["hook_diag"] = m.hook_diag()
            report = args.output / "results.json"
            report.write_text(
                json.dumps(result, indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )
            print(json.dumps({
                "result": "ok",
                "report": str(report),
                "retained": len(rows),
                "tail": [row["state"] for row in rows[-8:]],
            }, sort_keys=True))
            return 0
        handles: dict[int, str] = {}
        for name, address in hook_names.items():
            if name.startswith("write_sa1_"):
                handle = m.add_write_hook(
                    address, end_address=address + 1, cpu_type="Sa1"
                )
            elif name.startswith("write_snes_"):
                handle = m.add_write_hook(
                    address, end_address=address + 1, cpu_type="Snes"
                )
            else:
                handle = m.add_exec_hook(address, cpu_type="Sa1")
            result["hooks"][name] = {"handle": handle, "address": f"{address:06X}"}
            handles[handle] = name
        m.drain_notifications(timeout=0.05)
        counts: Counter[str] = Counter()
        iterations = 0
        next_sample = args.sample_every if args.sample_every > 0 else args.frames
        while int(m.get_state().get("frameCount", 0)) < args.frames:
            iterations += 1
            if iterations > args.frames * 4:
                raise RuntimeError("frame advance made too little progress under hooks")
            current_before = int(m.get_state().get("frameCount", 0))
            m.run_frames(min(args.chunk, args.frames - current_before))
            m.pause()
            for note in m.drain_notifications(timeout=0.05):
                if note.get("method") != "notifications/mesen/hookFired":
                    continue
                params = note.get("params") or {}
                name = handles.get(int(params.get("handle", -1)), "unknown")
                counts[name] += 1
                if len(result["first_events"]) < 32:
                    compact = {key: params.get(key) for key in sorted(params)}
                    compact["name"] = name
                    result["first_events"].append(compact)
            current_frame = int(m.get_state().get("frameCount", 0))
            if current_frame >= next_sample or current_frame >= args.frames:
                row = snap(m)
                result["samples"].append(row)
                if args.save_sample_states:
                    sample_state = args.output / f"frame-{current_frame:06d}.mss"
                    m.save_state(sample_state.resolve())
                    row["state"] = str(sample_state)
                if args.progress:
                    print(json.dumps({"sample": row}, sort_keys=True), flush=True)
                while next_sample <= current_frame:
                    next_sample += args.sample_every if args.sample_every > 0 else args.frames
            if current_frame >= args.frames:
                break
        result["iterations"] = iterations
        result["hook_counts"] = dict(sorted(counts.items()))
        result["final"] = snap(m)
        result["hook_diag"] = m.hook_diag()
        shot = m.take_screenshot(format="path")
        screenshot = args.output / "final.png"
        Path(shot["path"]).replace(screenshot)
        state_path = args.output / "final.mss"
        m.save_state(state_path.resolve())
        result["artifacts"] = {
            "screenshot": str(screenshot),
            "state": str(state_path),
        }
    (args.output / "results.json").write_text(
        json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(json.dumps({
        "result": "ok",
        "report": str(args.output / "results.json"),
        "hook_counts": result["hook_counts"],
        "final": result["final"],
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
